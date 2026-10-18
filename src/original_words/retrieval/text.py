"""CJK-aware text normalization and FTS5 query building.

SQLite's ``unicode61`` tokenizer does not split Chinese: ``设备采购方案`` becomes
one token, so ``采购`` cannot match it.  We therefore write a pre-tokenized copy
(one token per CJK character, one per Latin word) into FTS5 and turn a query
into an FTS5 phrase such as ``"采 购"``.  The original message text is never
modified or replaced by this tokenized copy.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3040, 0x30FF),
    (0xAC00, 0xD7AF),
)

_LATIN_WORD = re.compile(r"[a-z0-9_]+")
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_FILE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9_\-]{2,}\."
    r"(?:pdf|docx?|xlsx?|pptx?|txt|md|csv|json|jsonl|png|jpe?g|gif|webp|zip|rar|7z)",
    re.IGNORECASE,
)
_CODE = re.compile(r"\b[A-Za-z]{2,}[_-]\d{2,}\b")
_ENTITY = re.compile(r"[A-Za-z][A-Za-z0-9_.\-/]{2,}")

_STOP_ENTITIES = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "http",
    "https",
    "www",
}

_FILE_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "txt",
    "md",
    "csv",
    "json",
    "jsonl",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "zip",
    "rar",
    "7z",
}


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(low <= cp <= high for low, high in _CJK_RANGES)


def normalize(text: str) -> str:
    """NFKC, lower-case, collapse whitespace.  Keeps the original length shape."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> str:
    """Return a space-separated token copy suitable for FTS5 ``unicode61``."""
    if not text:
        return ""
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append("".join(buf))
            buf.clear()

    for ch in normalize(text):
        if is_cjk(ch):
            flush()
            out.append(ch)
        elif ch.isalnum() or ch in "_":
            buf.append(ch)
        else:
            flush()
    flush()
    return " ".join(out)


def token_count(text: str) -> int:
    return len(tokenize(text).split())


def _cjk_terms(run: str, mode: str) -> list[str]:
    if not run:
        return []
    if len(run) <= 1:
        return [f'"{run}"']
    if mode == "or" and len(run) > 4:
        # Long natural-language runs rarely match as one strict phrase.  Bigram
        # ORs are the recall fallback used by hybrid.search when AND returns 0.
        return [f'"{run[i]} {run[i + 1]}"' for i in range(len(run) - 1)]
    joined = " ".join(run)
    return [f'"{joined}"']


def build_fts_query(text: str, mode: str = "and") -> str:
    """Build a safe FTS5 expression.

    ``mode="and"`` is the default precision query.  ``mode="or"`` is the recall
    fallback: CJK runs longer than four characters become overlapping bigrams.
    """
    normalized = normalize(text)
    if not normalized:
        return ""
    mode = mode.lower()
    if mode not in {"and", "or"}:
        raise ValueError(f"unknown FTS mode: {mode!r}")

    terms: list[str] = []
    cjk_buf: list[str] = []
    latin_buf: list[str] = []

    def flush_cjk() -> None:
        if cjk_buf:
            terms.extend(_cjk_terms("".join(cjk_buf), mode))
            cjk_buf.clear()

    def flush_latin() -> None:
        if latin_buf:
            word = "".join(latin_buf)
            # Prefix query keeps file names and English terms useful without
            # turning the whole query into a wildcard soup.
            terms.append(f"{word}*")
            latin_buf.clear()

    for ch in normalized:
        if is_cjk(ch):
            flush_latin()
            cjk_buf.append(ch)
        elif ch.isalnum() or ch == "_":
            flush_cjk()
            latin_buf.append(ch)
        else:
            flush_cjk()
            flush_latin()
    flush_cjk()
    flush_latin()

    # Preserve order while removing duplicate terms: a duplicated phrase only
    # makes the query longer, never more precise.
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)
    if not unique:
        return ""
    joiner = " OR " if mode == "or" else " AND "
    return joiner.join(unique)


def extract_entities(text: str) -> list[str]:
    """Exact-match candidates: error codes, file names, URLs, Latin identifiers.

    These feed a separate exact channel.  They are not used to infer relevance;
    they only prevent an exact code/file name from being buried by fuzzy scores.
    """
    if not text:
        return []
    found: list[str] = []

    def add(value: str) -> None:
        value = value.strip().strip(".,;:!?()[]{}<>\"'")
        if len(value) < 3:
            return
        lowered = value.lower()
        if lowered in _STOP_ENTITIES or lowered in _FILE_EXTENSIONS:
            return
        if value not in found:
            found.append(value)

    # Consume whole URLs/file names first so their components are not also
    # emitted as separate entities (e.g. "example.com/a" or "xlsx").
    working = text
    for pattern in (_URL, _FILE, _CODE):
        for match in pattern.finditer(working):
            add(match.group(0))
        working = pattern.sub(" ", working)
    for match in _ENTITY.finditer(working):
        add(match.group(0))

    # Longest first: a file name containing a code should win over its fragment.
    found.sort(key=len, reverse=True)
    return found[:8]


def parse_timestamp(value: object) -> float | None:
    """Parse a timestamp into UTC epoch seconds.

    Accepts epoch numbers, ISO-8601 strings, ``Z`` suffixes and common date
    formats.  Naive values are treated as UTC; callers that own local-time
    conversion (the query parser) must do it before calling this function.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return float(raw)
    raw = raw.replace("Z", "+00:00").replace("/", "-")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
            try:
                parsed = dt.datetime.strptime(raw[: len(fmt) + 2], fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def date_label(timestamp: float | None) -> str:
    if timestamp is None:
        return "未知时间"
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%Y-%m-%d")


def datetime_label(timestamp: float | None) -> str:
    if timestamp is None:
        return "未知时间"
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
