from __future__ import annotations

import datetime as dt

from aimem.planner import plan
from aimem.text import build_fts_query, chunk_text, tokenize_cjk


def test_tokenize_cjk_splits_chinese_and_latin():
    assert tokenize_cjk("设备采购方案_final v2.xlsx") == "设 备 采 购 方 案 final v2 xlsx"


def test_fts_query_and_phrase():
    assert build_fts_query("报价单", "and") == '"报 价 单"'


def test_fts_query_or_bigrams():
    q = build_fts_query("报价单", "or")
    assert '"报 价"' in q and '"价 单"' in q and " OR " in q


def test_fts_query_latin_prefix():
    assert build_fts_query("report", "and") == "report*"


def test_chunk_text_respects_size():
    text = "第一句。" * 400
    chunks = chunk_text(text, size=100, max_chunks=3)
    assert 1 <= len(chunks) <= 3
    assert all(len(c) <= 200 for c in chunks)


NOW = dt.datetime(2026, 10, 18, 12, 0, 0)  # a Sunday


def test_plan_yesterday():
    p = plan("昨天的报表", now=NOW)
    assert p.ts_from is not None and p.ts_to is not None
    assert p.ts_to - p.ts_from == 86400
    assert "报表" in p.semantic


def test_plan_last_month_and_ext():
    p = plan("上个月的表格", now=NOW)
    start = dt.datetime(2026, 9, 1).timestamp()
    end = dt.datetime(2026, 10, 1).timestamp()
    assert p.ts_from == start and p.ts_to == end
    assert "xlsx" in p.exts and "csv" in p.exts


def test_plan_year_month():
    p = plan("2025年10月的合同", now=NOW)
    assert p.ts_from == dt.datetime(2025, 10, 1).timestamp()
    assert p.ts_to == dt.datetime(2025, 11, 1).timestamp()
    assert "合同" in p.semantic


def test_plan_size():
    p = plan("大于10MB的视频", now=NOW)
    assert p.size_min == 10 * 1024 * 1024
    assert "mp4" in p.exts


def test_plan_recent_days():
    p = plan("最近7天的文件", now=NOW)
    assert p.ts_from is not None
    assert p.ts_to - p.ts_from >= 8 * 86400


def test_plan_hyphen_date():
    p = plan("2025-10-12 的报价单", now=NOW)
    assert p.ts_from == dt.datetime(2025, 10, 12).timestamp()
    assert "报价单" in p.semantic
