from __future__ import annotations

import calendar
import datetime as dt
import re

from .models import QueryPlan
from .text import normalize

# ---------------------------------------------------------------------------
# Extension vocabulary
# ---------------------------------------------------------------------------

EXT_GROUPS: dict[str, list[str]] = {
    "表格": ["xlsx", "xls", "csv", "xlsm"],
    "excel": ["xlsx", "xls", "csv", "xlsm"],
    "文档": ["doc", "docx", "txt", "md", "pdf", "rtf"],
    "word": ["doc", "docx", "rtf"],
    "ppt": ["ppt", "pptx"],
    "幻灯片": ["ppt", "pptx"],
    "演示": ["ppt", "pptx"],
    "图片": ["jpg", "jpeg", "png", "gif", "webp", "bmp", "heic"],
    "照片": ["jpg", "jpeg", "png", "gif", "webp", "bmp", "heic"],
    "截图": ["png", "jpg", "jpeg", "webp"],
    "视频": ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm"],
    "音频": ["mp3", "wav", "flac", "m4a", "aac", "ogg"],
    "音乐": ["mp3", "wav", "flac", "m4a", "aac", "ogg"],
    "录音": ["mp3", "wav", "m4a", "amr"],
    "代码": ["py", "js", "ts", "java", "c", "cpp", "h", "go", "rs", "cs"],
    "压缩包": ["zip", "rar", "7z", "tar", "gz", "bz2"],
}

_EXPLICIT_EXT = re.compile(
    r"(?<![\w.])(pdf|docx?|xlsx?|pptx?|txt|md|csv|json|zip|rar|7z|mp4|mp3|png|jpe?g|gif|webp)(?![\w])",
    re.IGNORECASE,
)

_SOURCE_WORDS = {
    "微信": "wechat",
    "wechat": "wechat",
    "企业微信": "wework",
    "qq": "qq",
    "本地": "fs",
    "电脑": "fs",
    "磁盘": "fs",
    "文件": "fs",
}

# ---------------------------------------------------------------------------
# Time expressions
# ---------------------------------------------------------------------------


def _start_of_day(d: dt.datetime) -> dt.datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_week(d: dt.datetime) -> dt.datetime:
    d = _start_of_day(d)
    return d - dt.timedelta(days=d.weekday())


def _start_of_month(d: dt.datetime) -> dt.datetime:
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(d: dt.datetime, n: int) -> dt.datetime:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return d.replace(year=y, month=m, day=day)


def _day_range(d: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    return _start_of_day(d), _start_of_day(d) + dt.timedelta(days=1)


def _time_ranges(q: str, now: dt.datetime) -> list[tuple[dt.datetime, dt.datetime, tuple[int, int]]]:
    today = _start_of_day(now)
    tomorrow = today + dt.timedelta(days=1)
    items: list[tuple[dt.datetime, dt.datetime, tuple[int, int]]] = []

    def add(m: re.Match, a: dt.datetime, b: dt.datetime) -> None:
        items.append((a, b, m.span()))

    def rel_days(m: re.Match) -> None:
        n = int(m.group(1))
        add(m, today - dt.timedelta(days=n), tomorrow)

    def rel_weeks(m: re.Match) -> None:
        n = int(m.group(1))
        add(m, today - dt.timedelta(weeks=n), tomorrow)

    def rel_months(m: re.Match) -> None:
        n = int(m.group(1))
        add(m, _add_months(today, -n), tomorrow)

    def rel_years(m: re.Match) -> None:
        n = int(m.group(1))
        add(m, today.replace(year=today.year - n), tomorrow)

    simple: list[tuple[re.Pattern, object]] = [
        (re.compile(r"最近\s*(\d+)\s*天"), rel_days),
        (re.compile(r"近\s*(\d+)\s*天"), rel_days),
        (re.compile(r"最近\s*(\d+)\s*周"), rel_weeks),
        (re.compile(r"最近\s*(\d+)\s*个?月"), rel_months),
        (re.compile(r"最近\s*(\d+)\s*年"), rel_years),
        (re.compile(r"今天|今日"), lambda m: add(m, today, tomorrow)),
        (re.compile(r"昨天|昨日"), lambda m: add(m, today - dt.timedelta(days=1), today)),
        (re.compile(r"前天"), lambda m: add(m, today - dt.timedelta(days=2), today - dt.timedelta(days=1))),
        (re.compile(r"明天|明日"), lambda m: add(m, tomorrow, tomorrow + dt.timedelta(days=1))),
        (re.compile(r"这周|本周|这个星期"), lambda m: add(m, _start_of_week(now), _start_of_week(now) + dt.timedelta(days=7))),
        (re.compile(r"上周|上个星期|上星期"), lambda m: add(m, _start_of_week(now) - dt.timedelta(days=7), _start_of_week(now))),
        (re.compile(r"这个月|本月"), lambda m: add(m, _start_of_month(now), _add_months(_start_of_month(now), 1))),
        (re.compile(r"上个月|上月"), lambda m: add(m, _add_months(_start_of_month(now), -1), _start_of_month(now))),
        (re.compile(r"今年|本年"), lambda m: add(m, today.replace(month=1, day=1), today.replace(year=today.year + 1, month=1, day=1))),
        (re.compile(r"去年"), lambda m: add(m, today.replace(year=today.year - 1, month=1, day=1), today.replace(month=1, day=1))),
        (re.compile(r"前年"), lambda m: add(m, today.replace(year=today.year - 2, month=1, day=1), today.replace(year=today.year - 1, month=1, day=1))),
    ]

    def full_date(m: re.Match) -> None:
        try:
            a = dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return
        add(m, a, a + dt.timedelta(days=1))

    def year_month(m: re.Match) -> None:
        try:
            a = dt.datetime(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return
        add(m, a, _add_months(a, 1))

    def year_only(m: re.Match) -> None:
        add(m, dt.datetime(int(m.group(1)), 1, 1), dt.datetime(int(m.group(1)) + 1, 1, 1))

    # specific patterns first; `items` is sorted by span length later
    for pat in (
        re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?"),
        re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})"),
    ):
        for m in pat.finditer(q):
            full_date(m)
    for pat in (
        re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月"),
        re.compile(r"(\d{4})[-/](\d{1,2})(?![-/]\d)"),
    ):
        for m in pat.finditer(q):
            year_month(m)
    for m in re.finditer(r"(\d{4})\s*年", q):
        year_only(m)
    for pat, fn in simple:
        for m in pat.finditer(q):
            fn(m)

    # prefer longer matches, drop overlaps
    items.sort(key=lambda x: (x[2][1] - x[2][0]), reverse=True)
    kept: list[tuple[dt.datetime, dt.datetime, tuple[int, int]]] = []
    for it in items:
        s, e = it[2]
        if any(not (e <= ks or s >= ke) for _, _, (ks, ke) in kept):
            continue
        kept.append(it)
    return kept


# ---------------------------------------------------------------------------
# Size / ext / source
# ---------------------------------------------------------------------------

_SIZE_RE = re.compile(
    r"(大于|超过|>|不小于|至少|小于|不到|<|不超过|至多)\s*(\d+(?:\.\d+)?)\s*(kb|k|mb|m|gb|g)",
    re.IGNORECASE,
)
_UNIT = {"k": 1024, "kb": 1024, "m": 1024**2, "mb": 1024**2, "g": 1024**3, "gb": 1024**3}


def _parse_size(q: str) -> tuple[int | None, int | None, list[tuple[int, int]]]:
    lo = hi = None
    spans: list[tuple[int, int]] = []
    for m in _SIZE_RE.finditer(q):
        op = m.group(1)
        value = float(m.group(2)) * _UNIT[m.group(3).lower()]
        if op in ("大于", "超过", ">", "不小于", "至少"):
            lo = int(value)
        else:
            hi = int(value)
        spans.append(m.span())
    return lo, hi, spans


def _parse_ext(q: str) -> tuple[list[str], list[tuple[int, int]]]:
    found: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _EXPLICIT_EXT.finditer(q):
        found.append(m.group(1).lower())
        spans.append(m.span())
    for word, exts in EXT_GROUPS.items():
        for m in re.finditer(re.escape(word), q, re.IGNORECASE):
            found.extend(exts)
            spans.append(m.span())
    seen: set[str] = set()
    uniq = [e for e in found if not (e in seen or seen.add(e))]
    return uniq, spans


def _parse_sources(q: str) -> tuple[list[str], list[tuple[int, int]]]:
    found: list[str] = []
    spans: list[tuple[int, int]] = []
    for word, src in _SOURCE_WORDS.items():
        for m in re.finditer(re.escape(word), q, re.IGNORECASE):
            found.append(src)
            spans.append(m.span())
    seen: set[str] = set()
    return [s for s in found if not (s in seen or seen.add(s))], spans


def _strip(q: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return q
    mask = [True] * len(q)
    for s, e in spans:
        for i in range(s, min(e, len(q))):
            mask[i] = False
    return "".join(ch if mask[i] else " " for i, ch in enumerate(q))


def plan(query: str, now: dt.datetime | None = None) -> QueryPlan:
    now = now or dt.datetime.now()
    q = normalize(query)

    ranges = _time_ranges(q, now)
    spans: list[tuple[int, int]] = [span for _, _, span in ranges]
    if ranges:
        ts_from = max(r[0] for r in ranges).timestamp()
        ts_to = min(r[1] for r in ranges).timestamp()
        if ts_from >= ts_to:  # contradictory ("去年 上周"): keep the broader one
            ts_from = min(r[0] for r in ranges).timestamp()
            ts_to = max(r[1] for r in ranges).timestamp()
    else:
        ts_from = ts_to = None

    exts, ext_spans = _parse_ext(q)
    spans.extend(ext_spans)
    size_min, size_max, size_spans = _parse_size(q)
    spans.extend(size_spans)
    sources, src_spans = _parse_sources(q)
    spans.extend(src_spans)

    residual = re.sub(r"\s+", " ", _strip(q, spans)).strip()
    residual = re.sub(
        r"^(?:帮我|请|麻烦)?\s*(?:搜索一下|搜索|查找|寻找|找一下|找|查一下|查|搜一下|搜)\s*",
        "",
        residual,
    )
    residual = re.sub(r"^(?:那个|这个|关于|有关)\s*", "", residual)
    residual = re.sub(r"\s*(?:的|了)$", "", residual).strip()
    semantic = residual or q

    keywords = [w for w in re.findall(r"[a-z0-9]+", residual) if len(w) > 1]
    return QueryPlan(
        raw=query,
        semantic=semantic,
        keywords=keywords,
        exts=exts,
        ts_from=ts_from,
        ts_to=ts_to,
        size_min=size_min,
        size_max=size_max,
        sources=sources,
    )
