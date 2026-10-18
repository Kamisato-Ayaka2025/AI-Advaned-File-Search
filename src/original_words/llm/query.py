"""Rule-based query understanding.

This is the deterministic first pass for B-02.  It extracts hard filters
(account/source, chat, sender, explicit date) and soft hints (hedged time or
person) before any LLM call.  The LLM parser must be treated as an optional
enrichment: explicit user constraints are hard filters, hedged guesses are not.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..retrieval.types import SearchFilters

TZ = dt.timezone(dt.timedelta(hours=8))

_HEDGES = ("好像", "大概", "可能", "似乎", "印象", "记得", "左右", "前后", "差不多", "应该是")

_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

_STOPWORDS = (
    "帮我",
    "帮忙",
    "找一下",
    "查一下",
    "看一下",
    "关于",
    "那个",
    "这个",
    "那些",
    "这些",
    "我们",
    "你们",
    "他们",
    "我",
    "你",
    "他",
    "她",
    "的",
    "了",
    "是",
    "在",
    "吗",
    "呢",
    "吧",
    "啊",
    "说",
    "过",
    "和",
    "与",
    "跟",
    "给",
    "把",
    "被",
    "就",
    "都",
    "也",
    "还",
    "有",
    "谁",
    "找",
    "查",
    "一下",
)

_TIME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日?"), "ymd_cn"),
    (re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日"), "md"),
    (re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月"), "ym"),
    (re.compile(r"(?<!\d)(\d{1,2})月份?"), "month_num"),
    (re.compile(r"([一二三四五六七八九十]{1,2})月份?"), "month_cn"),
    (re.compile(r"上上周[一二三四五六日天]"), "weekday_last2"),
    (re.compile(r"上周[一二三四五六日天]"), "weekday_last"),
    (re.compile(r"(?:本周|这周)[一二三四五六日天]"), "weekday_this"),
    (re.compile(r"周[一二三四五六日天](?!前|之前|以前|截止)"), "weekday_current"),
    (re.compile(r"上上周|上周|本周|这周"), "week"),
    (re.compile(r"上个月|本月|这个月"), "month"),
    (re.compile(r"今天|昨天|前天"), "day"),
    (re.compile(r"最近(\d+)天|近(\d+)天|过去(\d+)天"), "recent_days"),
    (re.compile(r"(\d+)天前"), "days_ago"),
    (re.compile(r"今年|去年"), "year"),
)


@dataclass(frozen=True, slots=True)
class QuerySpec:
    raw: str
    semantic: str
    keywords: tuple[str, ...]
    filters: SearchFilters
    soft_hints: dict[str, Any] = field(default_factory=dict)
    intent: str = "search"
    confidence: float = 0.0


class RuleQueryParser:
    def __init__(
        self,
        participants: Sequence[tuple[str, str]] = (),
        chats: Sequence[tuple[str, str]] = (),
        *,
        timezone: dt.tzinfo = TZ,
    ) -> None:
        self.participants = tuple(participants)
        self.chats = tuple(chats)
        self.timezone = timezone

    def parse(self, query: str, *, now: dt.datetime | None = None) -> QuerySpec:
        raw = (query or "").strip()
        if not raw:
            return QuerySpec(raw="", semantic="", keywords=(), filters=SearchFilters())
        current = now or dt.datetime.now(self.timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.timezone)
        current = current.astimezone(self.timezone)
        working = raw
        soft: dict[str, Any] = {}

        start, end, matched = _find_time(working, current, self.timezone)
        if matched:
            if _is_hedged(working, working.find(matched)):
                soft["time_text"] = matched
                soft["time_range"] = (start, end)
            else:
                pass
            working = _remove_once(working, matched)

        sender_ids: list[str] = []
        for alias, sender_id in _sorted_aliases(self.participants):
            match = _find_alias(working, alias)
            if match is None:
                continue
            if _is_hedged(working, match.start()):
                soft["sender_text"] = alias
            elif sender_id not in sender_ids:
                sender_ids.append(sender_id)
            working = _remove_span(working, match.start(), match.end())

        chat_ids: list[str] = []
        for alias, chat_id in _sorted_aliases(self.chats):
            match = _find_alias(working, alias)
            if match is None:
                continue
            if _is_hedged(working, match.start()):
                soft["chat_text"] = alias
            elif chat_id not in chat_ids:
                chat_ids.append(chat_id)
            working = _remove_span(working, match.start(), match.end())

        sources: list[str] = []
        for pattern, source in ((r"(?i)\bqq\b", "qq"), (r"微信|wechat", "wechat")):
            match = re.search(pattern, working)
            if match:
                if source not in sources:
                    sources.append(source)
                working = _remove_span(working, match.start(), match.end())

        message_types: list[str] = []
        for pattern, message_type in (
            (r"图片|照片|图像|截图", "image"),
            (r"文件|附件|文档", "file"),
            (r"链接|卡片|分享", "link"),
            (r"语音|音频", "voice"),
            (r"表情", "emoji"),
        ):
            match = re.search(pattern, working)
            if match:
                if message_type not in message_types:
                    message_types.append(message_type)
                working = _remove_span(working, match.start(), match.end())

        filters = SearchFilters(
            sources=tuple(sources),
            chat_ids=tuple(chat_ids),
            sender_ids=tuple(sender_ids),
            message_types=tuple(message_types),
            time_start=None if "time_text" in soft else start,
            time_end=None if "time_text" in soft else end,
        )

        semantic = _clean_semantic(working) or _clean_semantic(raw) or raw
        keywords = tuple(_keywords(semantic))
        confidence = min(
            0.95,
            0.4
            + 0.15 * sum(
                bool(value)
                for value in (sources, chat_ids, sender_ids, message_types, start)
            )
            + 0.05 * len(keywords),
        )
        return QuerySpec(
            raw=raw,
            semantic=semantic,
            keywords=keywords,
            filters=filters,
            soft_hints=soft,
            intent=_intent(raw),
            confidence=confidence,
        )


def _sorted_aliases(values: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    # Longest alias first so "张经理" wins over "张".
    return sorted(
        ((alias, identifier) for identifier, alias in values if alias),
        key=lambda item: len(item[0]),
        reverse=True,
    )


def _find_alias(text: str, alias: str) -> re.Match[str] | None:
    return re.search(re.escape(alias), text, re.IGNORECASE)


def _remove_once(text: str, value: str) -> str:
    index = text.find(value)
    if index < 0:
        return text
    return _remove_span(text, index, index + len(value))


def _remove_span(text: str, start: int, end: int) -> str:
    return (text[:start] + " " + text[end:]).strip()


def _is_hedged(text: str, start: int) -> bool:
    window = text[max(0, start - 6) : start]
    return any(hedge in window for hedge in _HEDGES)


def _day_start(value: dt.date, timezone: dt.tzinfo) -> float:
    return dt.datetime(value.year, value.month, value.day, tzinfo=timezone).timestamp()


def _range(start: dt.date, end: dt.date, timezone: dt.tzinfo) -> tuple[float, float]:
    return _day_start(start, timezone), _day_start(end, timezone)


def _month_start(year: int, month: int) -> dt.date:
    return dt.date(year, month, 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _find_time(
    text: str,
    now: dt.datetime,
    timezone: dt.tzinfo,
) -> tuple[float | None, float | None, str | None]:
    today = now.date()
    for pattern, kind in _TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        matched = match.group(0)
        if kind in {"ymd", "ymd_cn"}:
            year, month, day = (int(match.group(index)) for index in (1, 2, 3))
            try:
                start_date = dt.date(year, month, day)
            except ValueError:
                continue
            return (*_range(start_date, start_date + dt.timedelta(days=1), timezone), matched)
        if kind == "md":
            month, day = int(match.group(1)), int(match.group(2))
            year = today.year
            try:
                start_date = dt.date(year, month, day)
            except ValueError:
                continue
            if start_date > today:
                year -= 1
                start_date = dt.date(year, month, day)
            return (*_range(start_date, start_date + dt.timedelta(days=1), timezone), matched)
        if kind == "ym":
            year, month = int(match.group(1)), int(match.group(2))
            if not 1 <= month <= 12:
                continue
            next_year, next_month = _next_month(year, month)
            return (
                *_range(_month_start(year, month), _month_start(next_year, next_month), timezone),
                matched,
            )
        if kind in {"month_num", "month_cn"}:
            raw_month = match.group(1)
            month = int(raw_month) if raw_month.isdigit() else _cn_number(raw_month)
            if not 1 <= month <= 12:
                continue
            year = today.year
            if month > today.month:
                year -= 1
            next_year, next_month = _next_month(year, month)
            return (
                *_range(_month_start(year, month), _month_start(next_year, next_month), timezone),
                matched,
            )
        if kind.startswith("weekday"):
            weekday = _WEEKDAYS[matched[-1]]
            monday = today - dt.timedelta(days=today.weekday())
            if kind == "weekday_last":
                monday -= dt.timedelta(days=7)
            elif kind == "weekday_last2":
                monday -= dt.timedelta(days=14)
            start_date = monday + dt.timedelta(days=weekday)
            return (*_range(start_date, start_date + dt.timedelta(days=1), timezone), matched)
        if kind == "week":
            monday = today - dt.timedelta(days=today.weekday())
            if matched in {"上周", "上上周"}:
                monday -= dt.timedelta(days=14 if matched == "上上周" else 7)
            return (*_range(monday, monday + dt.timedelta(days=7), timezone), matched)
        if kind == "month":
            if matched == "上个月":
                year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
            else:
                year, month = today.year, today.month
            next_year, next_month = _next_month(year, month)
            return (
                *_range(_month_start(year, month), _month_start(next_year, next_month), timezone),
                matched,
            )
        if kind == "day":
            offset = {"今天": 0, "昨天": 1, "前天": 2}[matched]
            start_date = today - dt.timedelta(days=offset)
            return (*_range(start_date, start_date + dt.timedelta(days=1), timezone), matched)
        if kind == "recent_days":
            days = int(next(group for group in match.groups() if group))
            start_date = today - dt.timedelta(days=max(0, days - 1))
            return (*_range(start_date, today + dt.timedelta(days=1), timezone), matched)
        if kind == "days_ago":
            days = int(match.group(1))
            start_date = today - dt.timedelta(days=days)
            return (*_range(start_date, start_date + dt.timedelta(days=1), timezone), matched)
        if kind == "year":
            year = today.year if matched == "今年" else today.year - 1
            return (*_range(dt.date(year, 1, 1), dt.date(year + 1, 1, 1), timezone), matched)
    return None, None, None


def _cn_number(value: str) -> int:
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in digits:
        return digits[value]
    if value.startswith("十"):
        return 10 + digits.get(value[1:], 0)
    if value.endswith("十"):
        return digits.get(value[:-1], 0) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 0) * 10 + digits.get(right, 0)
    return 0


def _clean_semantic(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    for word in sorted(_STOPWORDS, key=len, reverse=True):
        cleaned = cleaned.replace(word, " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _keywords(semantic: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", semantic)


def _intent(query: str) -> str:
    if re.search(r"是不是|有没有|是否|答应过|决定过|确认过|说过", query):
        return "yesno"
    if re.search(r"怎么|为什么|如何|过程|谁最先|谁先", query):
        return "process"
    return "search"


def apply_llm_query(rule: QuerySpec, data: dict) -> QuerySpec:
    """Merge validated LLM slots into the rule spec.

    Explicit rule constraints (hard date, chat, sender) win over the model.
    A hedged rule time stays soft even if the model proposes a range: the model
    may enrich semantics and fill missing slots, but it cannot turn a guess into
    a permission/date constraint.
    """
    from ..retrieval.text import parse_timestamp

    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    rule_hard_time = rule.filters.time_start is not None or rule.filters.time_end is not None
    rule_soft_time = "time_text" in rule.soft_hints

    time_start = rule.filters.time_start
    time_end = rule.filters.time_end
    soft = dict(rule.soft_hints)
    llm_start = parse_timestamp(filters.get("time_start"))
    llm_end = parse_timestamp(filters.get("time_end"))
    if not rule_hard_time and llm_start is not None and llm_end is not None:
        if rule_soft_time:
            soft["llm_time_range"] = (llm_start, llm_end)
        else:
            time_start, time_end = llm_start, llm_end

    def values(key: str) -> tuple[str, ...]:
        raw = filters.get(key)
        if not isinstance(raw, list):
            return ()
        return tuple(str(value) for value in raw if value)

    sources = rule.filters.sources or values("sources")
    chat_ids = rule.filters.chat_ids or values("chat_ids")
    sender_ids = rule.filters.sender_ids or values("sender_ids")
    message_types = rule.filters.message_types or values("message_types")

    semantic = str(data.get("semantic") or "").strip() or rule.semantic
    raw_keywords = data.get("keywords")
    keywords = (
        tuple(str(value) for value in raw_keywords if value)
        if isinstance(raw_keywords, list) and raw_keywords
        else rule.keywords
    )
    intent = data.get("intent") if data.get("intent") in {"search", "yesno", "process"} else rule.intent
    return QuerySpec(
        raw=rule.raw,
        semantic=semantic,
        keywords=keywords,
        filters=SearchFilters(
            sources=sources,
            chat_ids=chat_ids,
            sender_ids=sender_ids,
            message_types=message_types,
            time_start=time_start,
            time_end=time_end,
        ),
        soft_hints=soft,
        intent=intent,
        confidence=max(rule.confidence, 0.6),
    )
