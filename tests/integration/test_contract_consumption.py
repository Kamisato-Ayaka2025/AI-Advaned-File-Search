"""C 线契约消费测试：以 UI/组装视角消费 A 的 contracts 0.2.0-draft。

覆盖 A 在 PR #2 中要求 C 检查的五块内容：导入报告、任务/错误状态、UI 引用、
发送预览与授权、清理结果；另含 C 线在真实 UI 工作中会踩到的边界
（日期级/未知时间、char_span 索引、缺失消息、会话列表缺口）。

本文件不导入 Qt、不联网、不碰真实数据，也不构成 G1/G5 或人工验收证据。
命名以 test_gap_ 开头的用例是"C 线缺口探针"：它们断言当前契约的**缺失面**，
A 一旦补上相应 DTO/接口，这些用例会失败，用来提醒 C 更新 UI 适配。
"""

from __future__ import annotations

# ruff: noqa: E402  契约未合入当前分支时先整体跳过，之后才导入契约模块。
import json
from dataclasses import fields, replace
from hashlib import sha256
from typing import get_args

import pytest

# A 的 contracts 仍在 PR #2 中；未合入的分支上整文件跳过，避免留下"空测试通过"。
pytest.importorskip("original_words.contracts", reason="contracts 0.2.0-draft 未合入当前分支")
from original_words.contracts.answers import (
    Answer,
    Citation,
    Claim,
    SearchOutcome,
    TimelineEntry,
)
from original_words.contracts.common import (
    ErrorCode,
    ErrorInfo,
    ServiceFailure,
    SnapshotRef,
    TaskEvent,
)
from original_words.contracts.data import (
    CharSpan,
    Coverage,
    ImportManifest,
    ImportReport,
)
from original_words.contracts.messages import Message, stable_message_id
from original_words.contracts.search import (
    EvidenceBundle,
    SearchFilters,
    SearchHit,
    SearchRequest,
    SearchResult,
)
from original_words.contracts.sending import ConsentGrant, SendPlan
from original_words.contracts.services import CleanupItem, CleanupReport
from original_words.contracts.validation import validate_answer

SOURCE = "synthetic:account-c"
SNAPSHOT = SnapshotRef("data-7", "index-7")
RESOURCES = (
    "database",
    "index",
    "attachments",
    "cache",
    "logs",
    "keys",
    "pending_sends",
)
NOW = "2026-10-18T12:00:00Z"

# ---------------------------------------------------------------------------
# C 线实现侧的小工具（将来位于 application/ 与 ui/，此处内联便于独立运行）


def message(seq: int = 1, content: str = "这是合成证据", **kwargs) -> Message:
    base = dict(
        message_id=stable_message_id(SOURCE, "chat-c", original_id=str(seq)),
        source_id=SOURCE,
        chat_id="chat-c",
        chat_type="group",
        sender_id="person-c",
        sender_name="合成角色",
        timestamp="2026-01-01T00:00:00Z",
        message_type="text",
        content=content,
        seq=seq,
        timestamp_status="known",
        timestamp_precision="second",
        timestamp_source="fixture",
        source_timezone="UTC",
    )
    base.update(kwargs)
    return Message(**base)


def manifest(source_count: int | None = 1) -> ImportManifest:
    return ImportManifest(
        adapter_id="synthetic-json",
        adapter_version="1",
        export_schema="synthetic-v1",
        account_scope=(SOURCE,),
        snapshot_hash="synthetic-digest",
        upstream_tool=None,
        coverage_start="2026-01-01T00:00:00Z",
        coverage_end="2026-02-01T00:00:00Z",
        source_count=source_count,
    )


COMPLETENESS_LABEL = {
    "unknown": "覆盖未知",
    "partial": "部分覆盖",
    "verified_for_scope": "范围内已核对",
}


def format_count(value: int | None) -> str:
    """未知计数必须显示为"未知"，不能显示 0（Plan §4.3）。"""
    return "未知" if value is None else str(value)


def report_rows(report: ImportReport) -> list[tuple[str, str]]:
    return [
        ("读取", format_count(report.read_count)),
        ("导入", format_count(report.imported_count)),
        ("重复", format_count(report.duplicate_count)),
        ("拒收", format_count(report.rejected_count)),
        ("未知类型", format_count(report.unknown_count)),
        ("缺附件", format_count(report.attachment_missing_count)),
        ("完整性", COMPLETENESS_LABEL[report.completeness]),
    ]


ERROR_UI: dict[str, str] = {
    "INVALID_INPUT": "输入无效，请检查后重试",
    "UNSUPPORTED_FORMAT": "不支持的文件格式",
    "UNSUPPORTED_OPERATION": "当前数据源不支持该操作",
    "PERMISSION_DENIED": "没有权限访问该数据",
    "MODEL_UNAVAILABLE": "本地模型不可用",
    "INDEX_NOT_READY": "索引尚未就绪",
    "CONSENT_REQUIRED": "需要重新确认发送内容",
    "RATE_LIMITED": "请求过于频繁",
    "NETWORK_ERROR": "网络错误",
    "CANCELLED": "已取消",
    "REVISION_MISMATCH": "数据版本已变化，请重新查询",
    "INTERNAL_ERROR": "内部错误",
}

TASK_LABEL = {
    "queued": "排队中",
    "running": "处理中",
    "succeeded": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def task_view(event: TaskEvent) -> str:
    label = TASK_LABEL[event.state]
    if event.total is None:
        return f"{label}（进度未知）"
    return f"{label} {event.completed}/{event.total}"


def require_all_messages(requested: tuple[str, ...], returned: tuple[Message, ...]) -> None:
    """C 线守卫：仓储静默少返回消息时 UI 必须报错而不是显示残缺时间线。"""
    got = {m.message_id for m in returned}
    missing = [mid for mid in requested if mid not in got]
    if missing:
        raise ValueError(f"repository dropped {len(missing)} requested messages")


def char_span_to_utf16(text: str, span: CharSpan) -> tuple[int, int]:
    """契约 char_span 是 Python Unicode 索引；Qt/JS 需要 UTF-16 码元索引。"""
    return (
        len(text[: span.start].encode("utf-16-le")) // 2,
        len(text[: span.end].encode("utf-16-le")) // 2,
    )


def render_citation(citation: Citation, facts: dict[str, Message]) -> dict[str, str]:
    """引用只带 ID/区间，原文、发送者、时间一律从固定版本仓储取（Plan §4.2）。"""
    fact = facts[citation.message_id]
    if citation.char_span is None:
        snippet = fact.content
    else:
        snippet = fact.content[citation.char_span.start : citation.char_span.end]
    when = "未知时间" if fact.timestamp is None else fact.timestamp
    return {
        "text": snippet,
        "sender": fact.sender_name or "未知发送者",
        "time": when,
    }


def grant_state(grant: ConsentGrant, plan: SendPlan, now: str) -> str:
    """C 线只做展示级预检；真正的原子 consume 必须由 A 的授权服务执行。"""
    if grant.plan_fingerprint != plan.fingerprint:
        return "bound_to_other_plan"
    if grant.expires_at < now:
        return "expired"
    return "valid"


def send_plan() -> SendPlan:
    body = '{"model":"synthetic-model","messages":[{"role":"user","content":"合成问题"}]}'
    return SendPlan(
        request_id="request-c",
        purpose="answer",
        mode="partial",
        payload_hash=sha256(body.encode("utf-8")).hexdigest(),
        selected_message_ids=(message().message_id,),
        preview_text=body,
        model="synthetic-model",
        endpoint="https://api.deepseek.com/chat/completions",
        consent_scope=(SOURCE,),
    )


# ---------------------------------------------------------------------------
# 1. 导入报告（REQ-004/009/011/012，Plan §4.3）


def test_import_report_renders_unknown_instead_of_zero():
    unknown = ImportReport(
        manifest=manifest(source_count=None),
        read_count=None,
        imported_count=None,
        duplicate_count=None,
        rejected_count=None,
        unknown_count=None,
        attachment_missing_count=None,
        completeness="unknown",
    )
    rows = dict(report_rows(unknown))
    assert rows["读取"] == "未知"
    assert rows["完整性"] == "覆盖未知"
    assert "0" not in rows.values()


def test_import_report_renders_partial_counts_as_given():
    partial = ImportReport(
        manifest=manifest(source_count=1000),
        read_count=1000,
        imported_count=900,
        duplicate_count=10,
        rejected_count=90,
        unknown_count=5,
        attachment_missing_count=12,
        completeness="partial",
    )
    rows = dict(report_rows(partial))
    assert rows["导入"] == "900"
    assert rows["缺附件"] == "12"
    # 缺附件可以超过消息数，UI 不能把它当导入失败
    assert partial.attachment_missing_count > 0


def test_import_report_counts_must_reconcile_or_ui_shows_error():
    with pytest.raises(ValueError):
        ImportReport(
            manifest=manifest(source_count=1000),
            read_count=1000,
            imported_count=900,
            duplicate_count=10,
            rejected_count=0,
            unknown_count=0,
            attachment_missing_count=0,
            completeness="partial",
        )
    with pytest.raises(ValueError):
        ImportReport(
            manifest=manifest(source_count=1000),
            read_count=1,
            imported_count=1,
            duplicate_count=0,
            rejected_count=0,
            unknown_count=0,
            attachment_missing_count=0,
            completeness="verified_for_scope",
        )


def test_import_manifest_shows_upstream_unknown_for_generic_formats():
    rows = {
        "上游工具": manifest().upstream_tool or "未知",
        "导出时间": manifest().exported_at or "未知",
    }
    assert rows == {"上游工具": "未知", "导出时间": "未知"}


def test_gap_import_report_has_no_per_record_error_detail():
    """缺口：REQ-011 要求字段级错误报告，契约只有计数，C 无法展示哪一行失败。"""
    names = {f.name for f in fields(ImportReport)}
    assert "rejected_details" not in names
    assert "errors" not in names


# ---------------------------------------------------------------------------
# 2. 任务与错误状态（REQ-028/030，Plan §6 UI 与后台）


@pytest.mark.parametrize(
    ("state", "completed"),
    [("queued", 0), ("running", 4), ("succeeded", 12), ("cancelled", 4)],
)
def test_task_event_progress_states_render(state, completed):
    event = TaskEvent("task-c", "request-c", state, completed=completed, total=12)
    assert task_view(event).startswith(TASK_LABEL[state])


def test_task_event_failed_requires_sanitized_error():
    error = ErrorInfo("INDEX_NOT_READY", "索引尚未就绪", True, "task-c")
    event = TaskEvent("task-c", None, "failed", completed=3, total=12, error=error)
    assert task_view(event).startswith("失败")
    assert ERROR_UI[event.error.code] == "索引尚未就绪"
    assert event.error.retryable is True
    with pytest.raises(ValueError):
        TaskEvent("task-c", None, "failed", completed=3, total=12)


def test_task_event_rejects_inconsistent_progress():
    with pytest.raises(ValueError):
        TaskEvent("task-c", None, "running", completed=13, total=12)
    with pytest.raises(ValueError):
        TaskEvent("task-c", None, "succeeded", completed=4, total=12)
    unknown_total = TaskEvent("task-c", None, "succeeded", completed=7, total=None)
    assert task_view(unknown_total) == "已完成（进度未知）"


def test_error_taxonomy_matches_ui_mapping_exactly():
    """A 新增错误码时该用例失败，提醒 C 补 UI 文案，避免裸码上屏。"""
    assert set(get_args(ErrorCode)) == set(ERROR_UI)


def test_service_failure_str_carries_only_code():
    failure = ServiceFailure(ErrorInfo("NETWORK_ERROR", "网络错误，请稍后重试", True))
    assert str(failure) == "NETWORK_ERROR"
    assert "请稍后重试" not in repr(failure)


def test_gap_task_event_has_no_order_key_or_cancel_channel():
    """缺口：任务事件无序号/时间，UI 无法排序乱序信号；契约里也没有取消接口。"""
    names = {f.name for f in fields(TaskEvent)}
    assert "detail" not in names and "seq" not in names and "started_at" not in names
    assert "error" in names  # 但错误通道存在


# ---------------------------------------------------------------------------
# 3. UI 引用与时间展示（REQ-019/021/023，Plan §4.2）


def _answered_outcome() -> tuple[SearchOutcome, Message]:
    fact = message()
    span = CharSpan(fact.message_id, 0, 3)
    bundle = EvidenceBundle(SNAPSHOT, (fact.message_id,), (span,), coverage=Coverage((SOURCE,)))
    citation = Citation("citation-c", fact.message_id, SNAPSHOT, span)
    answer = Answer(
        "answered",
        (Claim("合成结论", ("citation-c",)),),
        (citation,),
        (TimelineEntry(fact.message_id, ("citation-c",)),),
        "demo",
    )
    return SearchOutcome("request-c", answer, bundle, "complete"), fact


def test_citation_renders_only_from_repository_facts():
    outcome, fact = _answered_outcome()
    validate_answer(outcome.answer, outcome.evidence, (fact,), (SOURCE,))
    facts = {fact.message_id: fact}
    rendered = render_citation(outcome.answer.citations[0], facts)
    assert rendered["text"] == fact.content[:3]
    assert rendered["sender"] == "合成角色"
    assert outcome.status == "answered"


def test_citation_carries_no_model_authored_text_fields():
    names = {f.name for f in fields(Citation)}
    assert names == {"citation_id", "message_id", "snapshot", "char_span"}


def test_char_span_is_python_index_so_ui_must_convert_to_utf16():
    fact = message(content="证据😀A")
    span = CharSpan(fact.message_id, 0, 3)
    assert fact.content[span.start : span.end] == "证据😀"
    start, end = char_span_to_utf16(fact.content, span)
    assert (start, end) == (0, 4)
    assert end != span.end  # 直接把契约索引交给 Qt 会截断错位


def test_unknown_and_day_precision_time_are_displayed_not_guessed():
    unknown = message(
        seq=2,
        timestamp=None,
        timestamp_status="unknown",
        timestamp_precision="unknown",
        timestamp_source=None,
    )
    day = message(seq=3, timestamp="2026-01-02", timestamp_precision="day")
    assert (
        render_citation(
            Citation("c2", unknown.message_id, SNAPSHOT), {unknown.message_id: unknown}
        )["time"]
        == "未知时间"
    )
    assert day.timestamp == "2026-01-02"
    # 有界时间过滤会保守排除日期级与未知时间，UI 必须给出提示而不是静默丢行
    assert day.matches_time_range("2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z") is False
    assert day.matches_time_range(None, None) is True
    assert unknown.matches_time_range(None, None) is True


def test_search_result_banner_uses_coverage_and_truncated():
    result = SearchResult(
        "request-c",
        SNAPSHOT,
        (SearchHit("chunk-c", (message().message_id,), 0.4, ("bm25",), "index-7"),),
        Coverage((SOURCE,), completeness="partial"),
        True,
    )
    banner = f"{COMPLETENESS_LABEL[result.coverage.completeness]}" + (
        "，结果被截断" if result.truncated else ""
    )
    assert banner == "部分覆盖，结果被截断"


def test_not_found_answer_cannot_fake_citations():
    answer = Answer("not_found")
    assert answer.claims == () and answer.citations == () and answer.timeline == ()
    with pytest.raises(ValueError):
        Answer("not_found", (Claim("编造", ("x",)),), (), ())
    request = SearchRequest("request-c", "不存在的团建", SearchFilters(source_ids=(SOURCE,)))
    assert request.query and answer.status == "not_found"


def test_partial_outcome_requires_partial_status():
    outcome, fact = _answered_outcome()
    partial_answer = Answer("partial", outcome.answer.claims, outcome.answer.citations)
    with pytest.raises(ValueError):
        SearchOutcome("request-c", partial_answer, outcome.evidence, "deadline")
    stopped = SearchOutcome(
        "request-c", partial_answer, outcome.evidence, "deadline", budget_exhausted=True
    )
    assert stopped.status == "partial"
    assert fact.message_id in stopped.evidence.message_ids


def test_gap_answer_has_no_request_id_or_clarification_text():
    """缺口：Answer 无 request_id/追问文本，C 必须改消费 SearchOutcome，且 REQ-023 追问无字段。"""
    names = {f.name for f in fields(Answer)}
    assert "request_id" not in names and "clarification" not in names
    assert "request_id" in {f.name for f in fields(SearchOutcome)}


def test_gap_repository_read_has_no_missing_id_channel():
    """缺口：get_messages 静默丢弃不可见消息，C 只能自建守卫。"""
    fact = message()
    with pytest.raises(ValueError):
        require_all_messages((fact.message_id, "missing-id"), (fact,))
    require_all_messages((fact.message_id,), (fact,))


# ---------------------------------------------------------------------------
# 4. 发送预览与授权（REQ-024/025/026）


def test_send_preview_is_exact_request_body_and_renders_model_and_query():
    plan = send_plan()
    body = json.loads(plan.preview_text)
    assert body["model"] == plan.model
    assert body["messages"][0]["content"] == "合成问题"
    rendered = (
        f"目标：{plan.endpoint}\n模型：{plan.model}\n"
        f"正文：{json.dumps(body['messages'], ensure_ascii=False)}"
    )
    assert "合成问题" in rendered
    assert plan.preview_text.encode("utf-8")  # 预览即发送字节


def test_editing_preview_invalidates_grant_and_ui_must_reconfirm():
    plan = send_plan()
    grant = ConsentGrant("grant-c", plan.fingerprint, "2026-12-01T00:00:00Z")
    assert grant_state(grant, plan, NOW) == "valid"
    edited = replace(plan, mode="full")
    assert edited.fingerprint != plan.fingerprint
    assert grant_state(grant, edited, NOW) == "bound_to_other_plan"
    expired = ConsentGrant("grant-c", plan.fingerprint, "2026-10-18T11:59:59Z")
    assert grant_state(expired, plan, NOW) == "expired"


def test_unsupported_endpoint_or_model_mismatch_is_rejected_before_ui():
    body = '{"model":"other-model","messages":[{"role":"user","content":"x"}]}'
    with pytest.raises(ValueError):
        SendPlan(
            "request-c",
            "answer",
            "full",
            sha256(body.encode()).hexdigest(),
            (),
            body,
            "synthetic-model",
            "https://api.deepseek.com/chat/completions",
            (SOURCE,),
        )
    plan = send_plan()
    with pytest.raises(ValueError):
        replace(plan, endpoint="https://api.deepseek.com.evil.test/chat/completions")
    with pytest.raises(ValueError):
        replace(plan, consent_scope=())


def test_gap_send_plan_does_not_bind_evidence_snapshot():
    """缺口：SendPlan 不含 SnapshotRef/证据指纹，UI 无法证明预览对应哪份数据版本。"""
    names = {f.name for f in fields(SendPlan)}
    assert "snapshot" not in names and "evidence_revision" not in names


# ---------------------------------------------------------------------------
# 5. 清理与导出结果（REQ-027，Plan §6 删除与后台任务）


def test_cleanup_report_must_cover_every_resource():
    with pytest.raises(ValueError):
        CleanupReport("delete-c", tuple(CleanupItem(r, "absent") for r in RESOURCES[:-1]))
    report = CleanupReport("delete-c", tuple(CleanupItem(r, "absent") for r in RESOURCES))
    assert report.succeeded is True
    rows = {i.resource: i.status for i in report.items}
    assert set(rows) == set(RESOURCES)


def test_cleanup_failure_blocks_success_display():
    status_by_resource = {resource: "deleted" for resource in RESOURCES}
    status_by_resource["keys"] = "failed"
    items = tuple(
        CleanupItem(
            resource,
            status_by_resource[resource],
            ErrorInfo("PERMISSION_DENIED", "密钥清理失败")
            if status_by_resource[resource] == "failed"
            else None,
        )
        for resource in RESOURCES
    )
    report = CleanupReport("delete-c", items)
    assert report.succeeded is False
    failed = [i for i in report.items if i.status == "failed"]
    assert failed[0].error.code == "PERMISSION_DENIED"
    with pytest.raises(ValueError):
        CleanupItem("keys", "failed")


def test_gap_cleanup_has_no_temp_or_wal_resource():
    """缺口：Plan §8.2 要求核对 WAL/临时文件，CleanupItem 资源枚举里没有对应项。"""
    allowed = {"database", "index", "attachments", "cache", "logs", "keys", "pending_sends"}
    with pytest.raises(ValueError):
        CleanupItem("temp", "absent")
    assert "temp" not in allowed


# ---------------------------------------------------------------------------
# 6. 会话列表 / 时间线视图缺口（C-01 的硬阻塞项）


def test_gap_contracts_have_no_chat_or_session_listing():
    """缺口：C-01 需要会话列表与时间线，契约既无 Chat DTO 也无仓储列举接口。"""
    import original_words.contracts as contracts_pkg
    from original_words.contracts.services import Repository

    assert not hasattr(contracts_pkg, "Chat")
    methods = {name for name in dir(Repository) if not name.startswith("_")}
    assert methods == {"import_batch", "get_messages", "get_context", "get_chunks"}
    assert not any("list" in name or "chat" in name for name in methods)
