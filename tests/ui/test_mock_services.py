"""C 线服务级测试：过滤组合、查询理解、导入适配错误路径（mock）。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from original_words.application.dtos import (
    ChatFilters,
    ErrorCode,
    SearchRequest,
    ServiceError,
)

# ---------------------------------------------------------------------------
# 过滤组合（REQ-022：10 组组合）


def _hits(container, query: str, filters: ChatFilters):
    request = SearchRequest(request_id="t", query=query, filters=filters)
    hits, _elapsed = container.search_service.search(request)
    return hits


def _msg_ids(container, hits):
    ids = []
    for hit in hits:
        for mid in hit.message_ids:
            ids.append(mid)
    return [container.repo.find_message(mid) for mid in ids]


def test_filter_01_empty_filters(container):
    container.load_demo()
    hits = _hits(container, "供应商", ChatFilters())
    assert hits, "空过滤时应有命中"


def test_filter_02_by_chat(container):
    container.load_demo()
    hits = _hits(container, "供应商", ChatFilters(chat_ids=("chat_project",)))
    msgs = _msg_ids(container, hits)
    assert msgs and all(m.chat_id == "chat_project" for m in msgs)


def test_filter_03_by_chat_type_private(container):
    container.load_demo()
    hits = _hits(container, "火锅", ChatFilters(chat_types=("private",)))
    msgs = _msg_ids(container, hits)
    assert msgs and all(m.chat_type == "private" for m in msgs)


def test_filter_04_by_sender(container):
    container.load_demo()
    hits = _hits(container, "供应商", ChatFilters(sender_names=("李娜",)))
    msgs = _msg_ids(container, hits)
    assert msgs and all(m.sender_name == "李娜" for m in msgs)


def test_filter_05_by_message_type(container):
    container.load_demo()
    file_hits = _hits(container, "预算表", ChatFilters(message_types=("file",)))
    assert file_hits, "文件名应可检索"
    text_hits = _hits(container, "供应商", ChatFilters(message_types=("text",)))
    assert text_hits, "文本类型应命中"
    image_hits = _hits(container, "报价截图", ChatFilters(message_types=("image",)))
    assert not image_hits, "图片文本不参与检索（REQ-012）"


def test_filter_06_time_30d_excludes_old(container):
    container.load_demo()
    start = (container.now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    hits = _hits(container, "供应商", ChatFilters(start_time=start))
    assert not hits, "约 220 天前的供应商讨论不应落在最近 30 天"


def test_filter_07_custom_range(container):
    container.load_demo()
    start = container.now - timedelta(days=222)
    end = container.now - timedelta(days=213)
    hits = _hits(container, "供应商", ChatFilters(start_time=start, end_time=end))
    assert hits, "自定义范围覆盖供应商讨论时间段，应命中"
    miss = _hits(container, "供应商", ChatFilters(start_time=end))
    assert not miss


def test_filter_08_sender_plus_type(container):
    container.load_demo()
    hits = _hits(
        container,
        "供应商",
        ChatFilters(sender_names=("张伟",), message_types=("text",)),
    )
    msgs = _msg_ids(container, hits)
    assert msgs and all(m.sender_name == "张伟" and m.message_type == "text" for m in msgs)


def test_filter_09_chat_plus_time(container):
    container.load_demo()
    start = (container.now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    hits = _hits(
        container,
        "会议",
        ChatFilters(chat_ids=("chat_project",), start_time=start),
    )
    msgs = _msg_ids(container, hits)
    assert msgs and all(
        m.chat_id == "chat_project" and m.timestamp is not None and m.timestamp >= start
        for m in msgs
    )


def test_filter_10_unknown_time_excluded_when_bounded(container):
    container.load_demo()
    start = (container.now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    hits = _hits(container, "测试环境又挂了", ChatFilters(start_time=start))
    msgs = _msg_ids(container, hits)
    assert all(m.timestamp is not None for m in msgs), "有界时间过滤不得匹配未知时间消息"


# ---------------------------------------------------------------------------
# 查询理解（REQ-017）


def test_parse_empty_query_rejected(container):
    with pytest.raises(ServiceError) as exc_info:
        container.parse("   ")
    assert exc_info.value.code is ErrorCode.INVALID_INPUT


def test_parse_soft_hints(container):
    container.load_demo()
    parsed = container.parse("张伟三月提到的登录 bug 后来怎么处理了")
    assert any("张伟" in hint for hint in parsed.soft_hints)
    assert any("三月" in hint for hint in parsed.soft_hints)
    assert parsed.hard_filters.is_empty(), "人物/时间线索是软线索，不得变为硬过滤（ADR-001）"


def test_parse_intent(container):
    container.load_demo()
    assert container.parse("谁最先反对换供应商").intent == "事实查找"
    assert container.parse("供应商报价讨论").intent == "查找原话"


# ---------------------------------------------------------------------------
# 导入适配器错误路径（REQ-009）


def _import(container, path: Path, start_time=None, end_time=None):
    return container.import_file(path, start_time, end_time)


def test_import_unsupported_format(container, tmp_path):
    bad = tmp_path / "data.xlsx"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ServiceError) as exc_info:
        _import(container, bad)
    assert exc_info.value.code is ErrorCode.UNSUPPORTED_FORMAT


def test_import_empty_file(container, tmp_path):
    empty = tmp_path / "data.json"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ServiceError) as exc_info:
        _import(container, empty)
    assert exc_info.value.code is ErrorCode.INVALID_INPUT


def test_import_bad_encoding(container, tmp_path):
    bad = tmp_path / "data.txt"
    bad.write_bytes(b"\xff\xfe\x81\x00bad")
    with pytest.raises(ServiceError) as exc_info:
        _import(container, bad)
    assert exc_info.value.code is ErrorCode.INVALID_INPUT


def test_import_json_wrong_shape(container, tmp_path):
    wrong = tmp_path / "data.json"
    wrong.write_text('{"messages": []}', encoding="utf-8")
    with pytest.raises(ServiceError) as exc_info:
        _import(container, wrong)
    assert exc_info.value.code is ErrorCode.UNSUPPORTED_FORMAT


def test_import_missing_required_fields(container, tmp_path):
    data = tmp_path / "data.json"
    data.write_text(
        '[{"message_id": "m1", "chat_id": "c1", "sender_name": "张三"},'
        ' {"message_id": "m2", "chat_id": "c1", "sender_name": "张三", "content": "你好"}]',
        encoding="utf-8",
    )
    _messages, report = container.adapter.read(data)
    assert report.read_count == 2
    assert report.rejected_count == 1, "缺 content 的 m1 应被拒绝"
    assert (
        report.read_count == report.imported_count + report.duplicate_count + report.rejected_count
    ), "计数守恒（Plan 4.3）"


def test_import_json_roundtrip_and_idempotent(container, tmp_path):
    data = tmp_path / "data.json"
    data.write_text(
        (
            '[{"message_id": "m1", "chat_id": "c1", "sender_name": "张三",'
            '  "content": "会议改到明天", "timestamp": "2026-10-01T10:00:00"},'
            ' {"message_id": "m2", "chat_id": "c1", "sender_name": "李四",'
            '  "content": "收到", "timestamp": "2026-10-01T10:05:00"}]'
        ),
        encoding="utf-8",
    )
    report = _import(container, data)
    assert report.imported_count == 2
    assert report.completeness == "verified_for_scope"
    again = _import(container, data)
    assert again.imported_count == 0 and again.duplicate_count == 2, "重复导入幂等"
    hits = _hits(container, "会议", ChatFilters())
    assert hits, "导入后应可检索"


def test_import_time_range(container, tmp_path):
    data = tmp_path / "data.csv"
    data.write_text(
        "message_id,chat_id,sender_name,content,timestamp\n"
        "m1,c1,张三,三月的讨论,2026-03-05T10:00:00\n"
        "m2,c1,李四,最近的讨论,2026-10-10T10:00:00\n",
        encoding="utf-8",
    )
    start = container.now - timedelta(days=30)
    report = _import(container, data, start_time=start)
    assert report.imported_count == 1, "范围外的 m1 应被拒绝"
    assert report.rejected_count == 1


def test_import_txt(container, tmp_path):
    data = tmp_path / "data.txt"
    data.write_text(
        "2026-10-01 10:00|张三|项目群|今天开始联调\n2026-10-01 10:05|李四|项目群|收到\n",
        encoding="utf-8",
    )
    report = _import(container, data)
    assert report.imported_count == 2
    assert report.manifest.adapter_id == "tier-a-txt"


def test_import_cancel(container, tmp_path):
    data = tmp_path / "data.json"
    rows = [
        f'{{"message_id": "m{i}", "chat_id": "c1", "sender_name": "张三",'
        f' "content": "消息{i}", "timestamp": "2026-10-01T10:00:00"}}'
        for i in range(1000)
    ]
    data.write_text("[" + ",".join(rows) + "]", encoding="utf-8")
    with pytest.raises(ServiceError) as exc_info:
        container.adapter.read(data, cancel=lambda: True)
    assert exc_info.value.code is ErrorCode.CANCELLED
