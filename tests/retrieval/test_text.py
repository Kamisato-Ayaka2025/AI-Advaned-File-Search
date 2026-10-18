from __future__ import annotations

from original_words.retrieval.text import (
    build_fts_query,
    extract_entities,
    normalize,
    parse_timestamp,
    token_count,
    tokenize,
)


def test_cjk_is_split_into_adjacent_tokens():
    assert tokenize("设备采购方案") == "设 备 采 购 方 案"


def test_mixed_cjk_and_latin_tokens():
    assert tokenize("GPU-Thermal 掉帧") == "gpu thermal 掉 帧"


def test_fts_query_defaults_to_a_phrase():
    assert build_fts_query("设备采购方案") == '"设 备 采 购 方 案"'


def test_fts_query_or_mode_uses_bigrams_for_long_runs():
    query = build_fts_query("显卡温度太高导致游戏掉帧", mode="or")
    assert '"显 卡"' in query
    assert " OR " in query


def test_fts_query_handles_quotes_and_punctuation():
    assert build_fts_query('报告"最终版"') != ""
    assert build_fts_query("!!!") == ""


def test_normalize_is_nfkc_and_lowercase():
    assert normalize("ＧＰＵ  温度") == "gpu 温度"


def test_extract_entities_keeps_whole_file_and_code():
    entities = extract_entities("ERR_5001 报价单_最终版.xlsx https://example.com/a")
    assert "ERR_5001" in entities
    assert "报价单_最终版.xlsx" in entities
    assert "https://example.com/a" in entities
    assert "xlsx" not in entities


def test_parse_timestamp_accepts_iso_and_epoch():
    assert parse_timestamp("2025-10-12T15:28:00+08:00") == 1760254080.0
    assert parse_timestamp(1760254080) == 1760254080.0
    assert parse_timestamp("") is None


def test_token_count_matches_tokenize():
    assert token_count("设备采购方案") == 6
