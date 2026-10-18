from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .jsonl import Message

# The other workstream turns chat history into Markdown. We do not know its exact
# shape yet, so accept the three common layouts and fall back to "one document".

_FM_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$")
_HEAD_DATE = re.compile(
    r"^#{1,6}\s*(?P<y>\d{4})[-/年](?P<m>\d{1,2})[-/月](?P<d>\d{1,2})"
)
_BOLD = re.compile(
    r"^\*\*(?P<sender>[^*]{1,40})\*\*\s*(?P<time>\d{1,2}:\d{2}(?::\d{2})?)?\s*$"
)
# QQ export style: **11:50:12 · 无关风月**
_BOLD_TS = re.compile(
    r"^\*\*(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*[·|]\s*(?P<sender>.+?)\*\*\s*$"
)
_BRACKET = re.compile(
    r"^\[(?P<date>\d{4}[-/]\d{1,2}[-/]\d{1,2})[ T](?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]\s*"
    r"(?P<sender>[^:：]{1,40})[:：]\s*(?P<text>.+)$"
)
_QUOTE = re.compile(
    r"^>\s*(?P<date>\d{4}[-/]\d{1,2}[-/]\d{1,2})[ T](?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*"
    r"[·|]\s*(?P<sender>.+?)\s*$"
)


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, str] = {}
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1 :])
        m = _FM_KEY.match(line)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip().strip("'\"")
    return {}, text


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(s: str | None) -> dt.time:
    if not s:
        return dt.time(0, 0)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return dt.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return dt.time(0, 0)


def _ts(day: dt.date | None, clock: dt.time, order: int) -> float:
    if day is None:
        return float(order)  # keep file order when no date is available
    return dt.datetime.combine(day, clock).timestamp() + order / 1000.0


def _read(path: Path) -> tuple[dict[str, str], str]:
    raw = path.read_text("utf-8", errors="ignore")
    return _front_matter(raw)


def parse_markdown(path: str | Path, *, platform: str | None = None) -> list[Message]:
    p = Path(path)
    meta, body = _read(p)
    conv = meta.get("conversation") or meta.get("chat") or _first_heading(body) or p.stem
    plat = platform or meta.get("platform") or "chat-md"
    lines = body.splitlines()

    msgs: list[Message] = []
    cur_day: dt.date | None = _parse_date(meta.get("date"))

    def emit(sender: str, text: str, day: dt.date | None, clock: str | None) -> None:
        text = text.strip()
        if not text:
            return
        msgs.append(
            Message(
                platform=plat,
                conversation=conv,
                sender=sender.strip() or "未知",
                ts=_ts(day, _parse_time(clock), len(msgs)),
                text=text,
                attachments=[],
                source_id=f"{p.name}:{len(msgs)}",
            )
        )

    # format 1: [2025-10-12 15:28] 张经理: 文本
    for line in lines:
        m = _BRACKET.match(line)
        if m:
            emit(m.group("sender"), m.group("text"), _parse_date(m.group("date")), m.group("time"))

    if not msgs:
        # format 2: **张经理** 15:28  + following paragraph(s)
        i = 0
        while i < len(lines):
            line = lines[i]
            hm = _HEAD_DATE.match(line)
            if hm:
                cur_day = dt.date(int(hm.group("y")), int(hm.group("m")), int(hm.group("d")))
                i += 1
                continue
            m = _BOLD_TS.match(line) or _BOLD.match(line)
            if m:
                sender, clock = m.group("sender"), m.group("time")
                i += 1
                buf: list[str] = []
                while i < len(lines):
                    nxt = lines[i]
                    if _BOLD.match(nxt) or _BOLD_TS.match(nxt) or _HEAD_DATE.match(nxt) or nxt.startswith("# "):
                        break
                    if nxt.strip():
                        buf.append(nxt.lstrip("> ").rstrip())
                    i += 1
                emit(sender, "\n".join(buf), cur_day, clock)
                continue
            i += 1

    if not msgs:
        # format 3: > 2025-10-12 15:28 · 张经理  + following "> " lines
        i = 0
        while i < len(lines):
            m = _QUOTE.match(lines[i])
            if m:
                day = _parse_date(m.group("date"))
                clock = m.group("time")
                sender = m.group("sender")
                i += 1
                buf = []
                while i < len(lines) and lines[i].startswith(">"):
                    buf.append(lines[i].lstrip(">").strip())
                    i += 1
                emit(sender, "\n".join(buf), day, clock)
                continue
            i += 1

    if not msgs:
        # fallback: one document unit, still searchable, just not per-message
        text = body.strip()
        if text:
            msgs.append(
                Message(
                    platform=plat,
                    conversation=conv,
                    sender="文件",
                    ts=_ts(cur_day, dt.time(0, 0), 0),
                    text=text,
                    attachments=[],
                    source_id=f"{p.name}:doc",
                )
            )
    return msgs


def parse_dir(directory: str | Path, *, platform: str | None = None) -> list[Message]:
    root = Path(directory)
    out: list[Message] = []
    for p in sorted(root.rglob("*.md")):
        if p.name.lower() == "index.md":
            continue
        out.extend(parse_markdown(p, platform=platform))
    return out
