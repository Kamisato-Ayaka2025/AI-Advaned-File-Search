from __future__ import annotations

from datetime import datetime

from original_words.llm.query import RuleQueryParser

from .support import TZ, ts

NOW = datetime(2025, 10, 15, 12, 0, tzinfo=TZ)


def parser() -> RuleQueryParser:
    return RuleQueryParser(
        participants=[("u1", "张经理")],
        chats=[("chat-a", "设备采购群")],
    )


def test_yesterday_is_a_hard_day_range():
    spec = parser().parse("昨天张经理说的报价", now=NOW)
    assert spec.filters.time_start == ts(2025, 10, 14)
    assert spec.filters.time_end == ts(2025, 10, 15)
    assert spec.filters.sender_ids == ("u1",)
    assert "报价" in spec.semantic


def test_last_week_range():
    spec = parser().parse("上周的报价", now=NOW)
    assert spec.filters.time_start == ts(2025, 10, 6)
    assert spec.filters.time_end == ts(2025, 10, 13)


def test_last_wednesday():
    spec = parser().parse("上周三的报价", now=NOW)
    assert spec.filters.time_start == ts(2025, 10, 8)
    assert spec.filters.time_end == ts(2025, 10, 9)


def test_explicit_iso_date_and_image_type():
    spec = parser().parse("2025-10-12 的图片", now=NOW)
    assert spec.filters.time_start == ts(2025, 10, 12)
    assert spec.filters.time_end == ts(2025, 10, 13)
    assert spec.filters.message_types == ("image",)


def test_month_only_is_parsed():
    spec = parser().parse("三月份的报价", now=NOW)
    assert spec.filters.time_start == ts(2025, 3, 1)
    assert spec.filters.time_end == ts(2025, 4, 1)

    spec = parser().parse("3月份的报价", now=NOW)
    assert spec.filters.time_start == ts(2025, 3, 1)


def test_recent_days():
    spec = parser().parse("最近7天的报价", now=NOW)
    assert spec.filters.time_start == ts(2025, 10, 9)
    assert spec.filters.time_end == ts(2025, 10, 16)


def test_hedged_month_is_soft_not_hard():
    spec = parser().parse("好像三月份讨论过退款", now=NOW)
    assert spec.filters.time_start is None
    assert spec.filters.time_end is None
    assert spec.soft_hints["time_text"] == "三月份"
    assert "退款" in spec.semantic


def test_chat_and_sender_and_source():
    spec = parser().parse("微信里张经理在设备采购群发的报价", now=NOW)
    assert spec.filters.sources == ("wechat",)
    assert spec.filters.sender_ids == ("u1",)
    assert spec.filters.chat_ids == ("chat-a",)
    assert "报价" in spec.semantic


def test_deadline_weekday_is_not_a_time_filter():
    spec = parser().parse("是不是答应过周五前给方案", now=NOW)
    assert spec.filters.time_start is None
    assert spec.intent == "yesno"
    assert "方案" in spec.semantic


def test_process_intent():
    spec = parser().parse("谁最先反对换供应商", now=NOW)
    assert spec.intent == "process"


def test_empty_query():
    spec = parser().parse("", now=NOW)
    assert spec.raw == ""
    assert spec.semantic == ""
    assert spec.filters.time_start is None


def test_llm_cannot_override_explicit_hard_time():
    from original_words.llm.query import apply_llm_query

    rule = parser().parse("上周的报价", now=NOW)
    merged = apply_llm_query(
        rule,
        {
            "semantic": "报价",
            "filters": {"time_start": "2025-10-14T00:00:00+08:00", "time_end": "2025-10-15T00:00:00+08:00"},
        },
    )
    assert merged.filters.time_start == ts(2025, 10, 6)
    assert merged.filters.time_end == ts(2025, 10, 13)


def test_llm_time_stays_soft_when_rule_was_hedged():
    from original_words.llm.query import apply_llm_query

    rule = parser().parse("好像三月份讨论过退款", now=NOW)
    merged = apply_llm_query(
        rule,
        {
            "semantic": "退款",
            "filters": {"time_start": "2025-03-01T00:00:00+08:00", "time_end": "2025-04-01T00:00:00+08:00"},
        },
    )
    assert merged.filters.time_start is None
    assert merged.soft_hints["llm_time_range"] == (ts(2025, 3, 1), ts(2025, 4, 1))
    assert merged.semantic == "退款"


def test_llm_fills_missing_filters_but_rule_wins():
    from original_words.llm.query import apply_llm_query

    rule = parser().parse("张经理的报价", now=NOW)
    merged = apply_llm_query(
        rule,
        {
            "semantic": "报价单",
            "filters": {"sender_ids": ["u9"], "chat_ids": ["chat-a"]},
            "intent": "search",
        },
    )
    assert merged.filters.sender_ids == ("u1",)
    assert merged.filters.chat_ids == ("chat-a",)
    assert merged.semantic == "报价单"
