"""C 线契约消费测试（针对 contracts 0.3.0-draft）：UI/组装视角的正向验收。

与 0.2 版的差异（按 A 的迁移说明重写，未改 A 的任何文件）：
- 原 7 个 `test_gap_*` 缺口探针按 A 的修复改为正向验收（B1/B2/B3/B5/S1/S3/S7/S8）。
- 新增消费：来源/会话列表、时间线分页、时间过滤披露、导入问题明细、证据绑定。
- 保留两个新的缺口探针（A 0.3 未覆盖）：`stop_reason` 与 `answer.status` 未绑定、
  `TaskEvent.seq` 兼容默认 0 会吞掉进度事件。

本文件不导入 Qt、不联网、不碰真实数据，也不构成 G1/G5、模型质量或人工验收证据。
"""

from __future__ import annotations

# ruff: noqa: E402  契约未合入当前分支时先整体跳过，之后才导入契约模块。
import json
from dataclasses import fields, replace
from hashlib import sha256
from typing import get_args

import pytest

# A 的 contracts 仍在 PR #2 中；未合入的分支上整文件跳过，避免留下"空测试通过"。
pytest.importorskip("original_words.contracts", reason="contracts 未合入当前分支")

from original_words.contracts.answers import (  # noqa: E402
    Answer,
    Citation,
    Claim,
    SearchOutcome,
    TimelineEntry,
)
from original_words.contracts.catalog import (  # noqa: E402
    ChatPage,
    ChatSummary,
    MessagePage,
    SourceSummary,
)
from original_words.contracts.common import (  # noqa: E402
    ErrorCode,
    ErrorInfo,
    ServiceFailure,
    SnapshotRef,
    TaskEvent,
)
from original_words.contracts.data import (  # noqa: E402
    CharSpan,
    Coverage,
    ImportIssue,
    ImportManifest,
    ImportReport,
)
from original_words.contracts.messages import (  # noqa: E402
    Message,
    TimeFilterInfo,
    filter_message_times,
    stable_message_id,
)
from original_words.contracts.search import (  # noqa: E402
    EvidenceBundle,
    MessageEdge,
    SearchFilters,
    SearchHit,
    SearchRequest,
    SearchResult,
    SearchSpec,
)
from original_words.contracts.sending import (  # noqa: E402
    ConsentGrant,
    SendPlan,
    evidence_digest,
)
from original_words.contracts.services import (  # noqa: E402
    CleanupItem,
    CleanupReport,
    ExportReceipt,
    Repository,
    TaskControl,
)
from original_words.contracts.validation import (  # noqa: E402
    require_all_messages,
    validate_answer,
    validate_generated_answer,
    validate_search_result,
)

SOURCE = "synthetic:account-c"
OTHER_SOURCE = "synthetic:account-other"
SNAPSHOT = SnapshotRef("data-7", "index-7")
NOW = "2026-10-18T12:00:00Z"
RESOURCES = (
    "database",
    "index",
    "attachments",
    "cache",
    "logs",
    "keys",
    "pending_sends",
)

# ---------------------------------------------------------------------------
# C 线实现侧的小工具（将来位于 application/ 与 ui/，此处内联便于独立运行）


def message(seq: int = 1, content: str = "这是合成证据", chat: str = "chat-c", **kwargs) -> Message:
    base = dict(
        message_id=stable_message_id(SOURCE, chat, original_id=str(seq)),
        source_id=SOURCE,
        chat_id=chat,
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


def issue_rows(report: ImportReport) -> list[str]:
    """问题明细只显示脱敏序号与固定模板，不显示字段值或路径。"""
    rows = [f"{issue.record_ref} {issue.detail}" for issue in report.issues]
    if report.issues_truncated:
        rows.append("还有未展示的问题")
    return rows


def task_view(event: TaskEvent) -> str:
    label = TASK_LABEL[event.state]
    if event.total is None:
        return f"{label}（进度未知）"
    return f"{label} {event.completed}/{event.total}"


class ProgressTracker:
    """C 线规则：同一 task_id 内丢弃不新于已见序号的事件。"""

    def __init__(self) -> None:
        self.last_seq: dict[str, int] = {}

    def accept(self, event: TaskEvent) -> bool:
        seen = self.last_seq.get(event.task_id)
        if seen is not None and event.seq <= seen:
            return False
        self.last_seq[event.task_id] = event.seq
        return True


def chat_list_rows(page: ChatPage) -> list[tuple[str, str, str]]:
    return [
        (
            chat.display_name or chat.chat_id,
            format_count(chat.message_count),
            COMPLETENESS_LABEL[chat.coverage.completeness],
        )
        for chat in page.chats
    ]


def time_warning(info: TimeFilterInfo) -> str | None:
    if not info.applied:
        return None
    if info.excluded_unknown_time_count is None or info.excluded_date_only_count is None:
        return "时间筛选排除了时间不精确的消息，排除数量尚未统计；可清除时间条件查看"
    if info.excluded_unknown_time_count == 0 and info.excluded_date_only_count == 0:
        return None
    return (
        f"时间筛选排除了 {info.excluded_unknown_time_count} 条未知时间、"
        f"{info.excluded_date_only_count} 条仅日期级消息"
        f"（策略 {info.date_only_policy}）；可清除时间条件查看"
    )


def require_all_messages_c(requested: tuple[str, ...], returned: tuple[Message, ...]) -> None:
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


def clarification_banner(answer: Answer) -> str | None:
    """REQ-023：最多一次追问；文案必须来自契约字段，不能由 UI 编造。"""
    if answer.status != "ambiguous":
        return None
    return f"需要你补充一次信息：{answer.clarification}"


def grant_state(grant: ConsentGrant, plan: SendPlan, now: str) -> str:
    """C 线只做展示级预检；真正的原子 consume 必须由 A 的授权服务执行。"""
    if grant.plan_fingerprint != plan.fingerprint:
        return "bound_to_other_plan"
    if grant.expires_at < now:
        return "expired"
    return "valid"


def bundle() -> EvidenceBundle:
    fact = message()
    return EvidenceBundle(
        SNAPSHOT,
        (fact.message_id,),
        (CharSpan(fact.message_id, 0, 3),),
        coverage=Coverage((SOURCE,), completeness="partial"),
    )


def send_plan(evidence: EvidenceBundle | None = None, **changes) -> SendPlan:
    evidence = evidence or bundle()
    body = '{"model":"synthetic-model","messages":[{"role":"user","content":"合成问题"}]}'
    plan = SendPlan(
        request_id="request-c",
        purpose="answer",
        mode="partial",
        payload_hash=sha256(body.encode("utf-8")).hexdigest(),
        selected_message_ids=tuple(evidence.message_ids),
        preview_text=body,
        model="synthetic-model",
        endpoint="https://api.deepseek.com/chat/completions",
        consent_scope=(SOURCE,),
        snapshot=evidence.snapshot,
        evidence_digest=evidence_digest(evidence),
    )
    return replace(plan, **changes) if changes else plan


# ---------------------------------------------------------------------------
# 1. B1：来源/会话列表与时间线分页（REQ-001/019/021）


def test_b1_source_and_chat_list_render_unknown_counts():
    source = SourceSummary(SOURCE, None, None, None, Coverage((SOURCE,)))
    assert source.display_name is None  # UI 退回 source_id 显示
    page = ChatPage(
        SNAPSHOT,
        (
            ChatSummary(
                SOURCE,
                "chat-c",
                "group",
                None,
                ("person-c",),
                None,
                None,
                None,
                Coverage((SOURCE,)),
            ),
        ),
    )
    assert chat_list_rows(page) == [("chat-c", "未知", "覆盖未知")]
    assert page.next_cursor is None


def test_b1_chat_page_rejects_duplicates_and_dangling_cursor():
    chat = ChatSummary(
        SOURCE, "chat-c", "group", "合成群聊", (), 3, None, None, Coverage((SOURCE,))
    )
    other = replace(
        chat,
        source_id=OTHER_SOURCE,
        coverage=replace(chat.coverage, source_ids=(OTHER_SOURCE,)),
    )
    assert len(ChatPage(SNAPSHOT, (chat, other)).chats) == 2  # 复合身份
    with pytest.raises(ValueError):
        ChatPage(SNAPSHOT, (chat, chat))
    with pytest.raises(ValueError):
        ChatPage(SNAPSHOT, (), next_cursor="page-2")
    with pytest.raises(ValueError):
        ChatPage(SNAPSHOT, tuple(replace(chat, chat_id=f"c{i}") for i in range(201)))


def test_b1_message_page_bounded_and_unbounded():
    fact = message()
    unbounded = MessagePage(SNAPSHOT, SOURCE, fact.chat_id, (fact,))
    assert unbounded.time_filter.applied is False
    assert time_warning(unbounded.time_filter) is None
    bounded = MessagePage(
        SNAPSHOT,
        SOURCE,
        fact.chat_id,
        (fact,),
        start="2026-01-01T00:00:00Z",
        end="2026-01-02T00:00:00Z",
        time_filter=TimeFilterInfo(True, 2, 1),
    )
    warning = time_warning(bounded.time_filter)
    assert warning is not None and "未知时间" in warning and "清除时间条件" in warning
    with pytest.raises(ValueError):
        replace(bounded, time_filter=TimeFilterInfo(False, 0, 0))
    with pytest.raises(ValueError):
        MessagePage(SNAPSHOT, SOURCE, fact.chat_id, (message(chat="other"),))


def test_b1_timeline_cross_chat_and_unknown_page():
    facts = (
        message(1),
        message(
            2,
            timestamp=None,
            timestamp_status="unknown",
            timestamp_precision="unknown",
            timestamp_source=None,
        ),
    )
    page = MessagePage(SNAPSHOT, SOURCE, "chat-c", facts)
    assert len(page.messages) == 2
    with pytest.raises(ValueError):
        MessagePage(SNAPSHOT, OTHER_SOURCE, "chat-c", facts)
    unknown_node = page.messages[1]
    rendered = render_citation(
        Citation("c9", unknown_node.message_id, SNAPSHOT), {unknown_node.message_id: unknown_node}
    )
    assert rendered["time"] == "未知时间"


def test_b1_repository_protocol_surface():
    methods = {name for name in dir(Repository) if not name.startswith("_")}
    assert {
        "list_sources",
        "list_chats",
        "get_message_range",
        "get_messages",
        "get_context",
        "get_chunks",
        "import_batch",
    } <= methods


# ---------------------------------------------------------------------------
# 2. 任务、错误与取消（REQ-028/030，Plan §6）


@pytest.mark.parametrize(
    ("state", "completed"),
    [("queued", 0), ("running", 4), ("succeeded", 12), ("cancelled", 4)],
)
def test_task_event_progress_states_render(state, completed):
    event = TaskEvent("task-c", "request-c", state, completed=completed, total=12, seq=3)
    assert task_view(event).startswith(TASK_LABEL[state])


def test_task_event_failed_requires_sanitized_error():
    error = ErrorInfo("INDEX_NOT_READY", "索引尚未就绪", True, "task-c")
    event = TaskEvent("task-c", None, "failed", completed=3, total=12, error=error, seq=2)
    assert task_view(event).startswith("失败")
    assert ERROR_UI[event.error.code] == "索引尚未就绪"
    with pytest.raises(ValueError):
        TaskEvent("task-c", None, "failed", completed=3, total=12)
    with pytest.raises(ValueError):
        TaskEvent("task-c", None, "succeeded", completed=4, total=12)


def test_s1_late_progress_events_are_dropped_by_seq():
    tracker = ProgressTracker()
    assert tracker.accept(TaskEvent("task-c", "request-c", "running", 1, 12, seq=1))
    assert tracker.accept(TaskEvent("task-c", "request-c", "running", 5, 12, seq=2))
    assert not tracker.accept(TaskEvent("task-c", "request-c", "running", 3, 12, seq=1))
    assert tracker.accept(TaskEvent("task-c", "request-c", "succeeded", 12, 12, seq=3))
    # 不同任务互不影响
    assert tracker.accept(TaskEvent("task-d", "request-d", "queued", 0, None, seq=0))


def test_s1_task_control_offers_cooperative_cancel():
    class Canceller:
        def __init__(self) -> None:
            self.cancelled: list[str] = []

        def cancel(self, task_id: str) -> None:
            self.cancelled.append(task_id)

    canceller = Canceller()
    assert isinstance(canceller, TaskControl)
    canceller.cancel("task-c")
    canceller.cancel("task-c")  # 幂等约定：重复取消无副作用
    assert canceller.cancelled == ["task-c", "task-c"]


def test_error_taxonomy_matches_ui_mapping_exactly():
    """A 新增错误码时该用例失败，提醒 C 补 UI 文案，避免裸码上屏。"""
    assert set(get_args(ErrorCode)) == set(ERROR_UI)


def test_service_failure_str_carries_only_code():
    failure = ServiceFailure(ErrorInfo("NETWORK_ERROR", "网络错误，请稍后重试", True))
    assert str(failure) == "NETWORK_ERROR"
    assert "请稍后重试" not in repr(failure)


# ---------------------------------------------------------------------------
# 3. B2/B4：回答状态、迟到丢弃、追问与时间披露（REQ-020/021/023）


def _answered_outcome() -> tuple[SearchOutcome, Message]:
    fact = message()
    evidence = bundle()
    citation = Citation("citation-c", fact.message_id, SNAPSHOT, CharSpan(fact.message_id, 0, 3))
    answer = Answer(
        "answered",
        (Claim("合成结论", ("citation-c",)),),
        (citation,),
        (TimelineEntry(fact.message_id, ("citation-c",)),),
        "demo",
        request_id="request-c",
    )
    return SearchOutcome("request-c", answer, evidence, "complete"), fact


def test_b2_request_id_survives_and_stale_answer_rejected():
    outcome, fact = _answered_outcome()
    answer = outcome.answer
    assert answer.request_id == outcome.request_id
    validate_answer(answer, outcome.evidence, (fact,), (SOURCE,))
    with pytest.raises(ServiceFailure):
        validate_generated_answer(answer, "request-new", outcome.evidence, (fact,), (SOURCE,))
    with pytest.raises(TypeError):
        Answer("not_found")  # request_id 必填，不能静默用默认值


def test_b2_ambiguous_answer_carries_single_clarification():
    answer = Answer("ambiguous", request_id="request-c", clarification="请指明是哪个会话")
    assert clarification_banner(answer) == "需要你补充一次信息：请指明是哪个会话"
    assert clarification_banner(Answer("not_found", request_id="r")) is None
    with pytest.raises(ValueError):
        Answer("ambiguous", request_id="request-c")
    with pytest.raises(ValueError):
        Answer("answered", request_id="request-c", clarification="不该追问")


def test_citation_renders_only_from_repository_facts():
    outcome, fact = _answered_outcome()
    facts = {fact.message_id: fact}
    rendered = render_citation(outcome.answer.citations[0], facts)
    assert rendered["text"] == fact.content[:3]
    assert rendered["sender"] == "合成角色"
    assert {f.name for f in fields(Citation)} == {
        "citation_id",
        "message_id",
        "snapshot",
        "char_span",
    }


def test_char_span_is_python_index_so_ui_must_convert_to_utf16():
    fact = message(content="证据😀A")
    span = CharSpan(fact.message_id, 0, 3)
    assert fact.content[span.start : span.end] == "证据😀"
    start, end = char_span_to_utf16(fact.content, span)
    assert (start, end) == (0, 4)
    assert end != span.end  # 直接把契约索引交给 Qt 会截断错位


def test_b4_time_policy_reference_helper_and_disclosure():
    facts = (
        message(1),
        message(
            2,
            timestamp=None,
            timestamp_status="unknown",
            timestamp_precision="unknown",
            timestamp_source=None,
        ),
        message(3, timestamp="2026-01-05", timestamp_precision="day"),
    )
    accepted, info = filter_message_times(facts, None, None)
    assert len(accepted) == 3 and info.applied is False
    accepted, info = filter_message_times(facts, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    assert len(accepted) == 1
    assert (info.excluded_unknown_time_count, info.excluded_date_only_count) == (1, 1)
    assert info.date_only_policy == "exclude_imprecise_v1"


def test_b4_search_result_must_disclose_time_filter():
    bounded = SearchRequest(
        "request-c",
        "合成问题",
        SearchFilters(source_ids=(SOURCE,), start="2026-01-01T00:00:00Z"),
    )
    spec = SearchSpec(bounded, SNAPSHOT, (SOURCE,))
    hit = SearchHit("chunk-c", tuple(bundle().message_ids), 0.4, ("bm25",), "index-7")
    disclosed = SearchResult(
        "request-c", SNAPSHOT, (hit,), Coverage((SOURCE,)), False, TimeFilterInfo(True, 4, 2)
    )
    validate_search_result(spec, disclosed)
    assert "4 条未知时间" in (time_warning(disclosed.time_filter) or "")
    with pytest.raises(ValueError):
        validate_search_result(spec, replace(disclosed, time_filter=TimeFilterInfo(False)))
    # 计数未知时必须提示"未统计"，不能显示 0
    assert "尚未统计" in (time_warning(TimeFilterInfo(True)) or "")


def test_not_found_and_partial_states():
    not_found = Answer("not_found", request_id="request-c")
    assert not_found.claims == () and not_found.citations == ()
    with pytest.raises(ValueError):
        Answer("not_found", (Claim("编造", ("x",)),), (), (), request_id="request-c")
    outcome, _fact = _answered_outcome()
    partial = Answer(
        "partial", outcome.answer.claims, outcome.answer.citations, request_id="request-c"
    )
    with pytest.raises(ValueError):
        SearchOutcome("request-c", partial, outcome.evidence, "deadline")
    stopped = SearchOutcome(
        "request-c", partial, outcome.evidence, "deadline", budget_exhausted=True
    )
    assert stopped.status == "partial"


# ---------------------------------------------------------------------------
# 4. B5：预览与证据绑定（REQ-024/025/026）


def test_b5_send_preview_is_exact_body_and_binds_evidence():
    evidence = bundle()
    plan = send_plan(evidence)
    assert plan.snapshot == evidence.snapshot
    assert plan.evidence_digest == evidence_digest(evidence)
    body = json.loads(plan.preview_text)
    assert body["model"] == plan.model
    assert body["messages"][0]["content"] == "合成问题"
    plan.validate_evidence(evidence)


def test_b5_changed_evidence_forces_new_preview():
    evidence = bundle()
    plan = send_plan(evidence)
    changed = replace(evidence, coverage=Coverage((SOURCE,), completeness="verified_for_scope"))
    with pytest.raises(ServiceFailure) as failure:
        plan.validate_evidence(changed)
    assert failure.value.error.code == "CONSENT_REQUIRED"
    other_revision = replace(evidence, snapshot=SnapshotRef("data-8", "index-8"))
    with pytest.raises(ServiceFailure) as failure:
        plan.validate_evidence(other_revision)
    assert failure.value.error.code == "REVISION_MISMATCH"
    with pytest.raises(ServiceFailure):
        plan.validate_evidence(EvidenceBundle(SNAPSHOT))  # 空证据不等于原选择


def test_b5_selection_and_scope_rules():
    evidence = bundle()
    with pytest.raises(ValueError):
        send_plan(evidence, selected_message_ids=())
    with pytest.raises(ValueError):
        send_plan(evidence, consent_scope=())
    with pytest.raises(ValueError):
        send_plan(evidence, evidence_digest="not-a-digest")
    with pytest.raises(ValueError):
        send_plan(evidence, endpoint="https://api.deepseek.com.evil.test/chat/completions")
    full = send_plan(evidence, mode="full")
    full.validate_evidence(evidence)
    subset = replace(evidence, message_ids=(evidence.message_ids[0], "extra"))
    with pytest.raises(ServiceFailure):
        full.validate_evidence(subset)  # full 必须等于绑定证据全集


def test_b5_query_parse_send_carries_no_chat_evidence():
    empty = EvidenceBundle(SNAPSHOT)
    body = '{"model":"synthetic-model","messages":[{"role":"user","content":"合成问题"}]}'
    plan = SendPlan(
        "request-c",
        "query_parse",
        "full",
        sha256(body.encode()).hexdigest(),
        (),
        body,
        "synthetic-model",
        "https://api.deepseek.com/chat/completions",
        (SOURCE,),
        snapshot=SNAPSHOT,
        evidence_digest=evidence_digest(empty),
    )
    plan.validate_evidence(empty)
    with pytest.raises(ServiceFailure):
        plan.validate_evidence(bundle())


def test_editing_preview_invalidates_grant_and_ui_must_reconfirm():
    evidence = bundle()
    plan = send_plan(evidence)
    grant = ConsentGrant("grant-c", plan.fingerprint, "2026-12-01T00:00:00Z")
    assert grant_state(grant, plan, NOW) == "valid"
    edited = replace(plan, mode="full")
    assert edited.fingerprint != plan.fingerprint
    assert grant_state(grant, edited, NOW) == "bound_to_other_plan"
    expired = ConsentGrant("grant-c", plan.fingerprint, "2026-10-18T11:59:59Z")
    assert grant_state(expired, plan, NOW) == "expired"
    # 重绑证据会改变摘要，因此旧 grant 不可复用
    rebound = replace(plan, evidence_digest=evidence_digest(EvidenceBundle(SNAPSHOT)))
    assert grant_state(grant, rebound, NOW) == "bound_to_other_plan"


# ---------------------------------------------------------------------------
# 5. B3：导入报告与问题明细（REQ-004/009/011）


def test_b3_import_report_renders_unknown_instead_of_zero():
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
    assert rows["读取"] == "未知" and rows["完整性"] == "覆盖未知"
    assert "0" not in rows.values()


def test_b3_issue_rows_are_redacted_and_truncation_is_visible():
    report = ImportReport(
        manifest=manifest(source_count=101),
        read_count=101,
        imported_count=1,
        duplicate_count=0,
        rejected_count=100,
        unknown_count=0,
        attachment_missing_count=0,
        completeness="partial",
        issues=(ImportIssue("missing_field", "record:7", "sender_id", "缺少必填字段"),),
        issues_truncated=True,
    )
    rows = issue_rows(report)
    assert rows[0] == "record:7 缺少必填字段"
    assert rows[-1] == "还有未展示的问题"
    assert report.rejected_count == 100  # 样例数量独立于拒收计数


def test_b3_issue_rejects_raw_values_and_oversized_samples():
    with pytest.raises(ValueError):
        ImportIssue("missing_field", "C:/private/chat.json", "sender_id", "缺少必填字段")
    with pytest.raises(ValueError):
        ImportIssue("missing_field", "record:7", "sender_id", "原始内容泄露")
    issue = ImportIssue("bad_time", "record:2", "timestamp", "时间无效或精度不明确")
    with pytest.raises(ValueError):
        ImportReport(
            manifest=manifest(source_count=1),
            read_count=1,
            imported_count=1,
            duplicate_count=0,
            rejected_count=0,
            unknown_count=0,
            attachment_missing_count=0,
            completeness="partial",
            issues=(issue,) * 101,
        )


def test_import_report_counts_must_reconcile():
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


# ---------------------------------------------------------------------------
# 6. S3/S4/S7/S8：清理、导出、缺失消息、引用关系


def test_s3_cleanup_report_covers_every_resource_and_failures_block_success():
    status = {resource: "deleted" for resource in RESOURCES}
    status["keys"] = "failed"
    items = tuple(
        CleanupItem(
            resource,
            status[resource],
            ErrorInfo("PERMISSION_DENIED", "密钥清理失败")
            if status[resource] == "failed"
            else None,
        )
        for resource in RESOURCES
    )
    report = CleanupReport("delete-c", items)
    assert report.succeeded is False
    assert {i.resource for i in report.items} == set(RESOURCES)
    with pytest.raises(ValueError):
        CleanupReport("delete-c", items[:-1])


def test_s4_export_receipt_digest_is_lowercase_hex_when_present():
    receipt = ExportReceipt("out.json", "json", 12, "a" * 64)
    assert receipt.sha256 == "a" * 64
    assert ExportReceipt("out.json", "json", 12).sha256 is None
    with pytest.raises(ValueError):
        ExportReceipt("out.json", "json", 12, "A" * 64)


def test_s7_missing_ids_fail_loudly_without_leaking_ids():
    fact = message()
    with pytest.raises(ValueError):
        require_all_messages_c((fact.message_id, "missing-id"), (fact,))
    require_all_messages_c((fact.message_id,), (fact,))
    with pytest.raises(ServiceFailure) as failure:
        require_all_messages((fact.message_id,), ())
    assert failure.value.error.code == "REVISION_MISMATCH"
    assert fact.message_id not in str(failure.value)


def test_s8_quote_target_outside_bundle_keeps_relation():
    fact = message()
    edge = MessageEdge(
        fact.message_id,
        "known-other-message",
        "quote",
        "synthetic-export",
        SNAPSHOT.dataset_revision,
        external_target=True,
    )
    evidence = EvidenceBundle(SNAPSHOT, (fact.message_id,), edge_provenance=(edge,))
    assert evidence.edge_provenance[0].to_id == "known-other-message"
    unresolved = MessageEdge(
        fact.message_id,
        None,
        "quote",
        "synthetic-export",
        SNAPSHOT.dataset_revision,
        True,
    )
    assert replace(evidence, edge_provenance=(unresolved,)).edge_provenance[0].unresolved
    # 目标不在证据包内却不标 external_target，视为契约冲突
    with pytest.raises(ValueError):
        replace(evidence, edge_provenance=(replace(edge, external_target=False),))


# ---------------------------------------------------------------------------
# 7. 0.3 仍未闭合的缺口（新探针；A 修好后这些用例失败，提醒 C 更新）


def test_gap_stop_reason_ambiguous_not_tied_to_answer_status():
    """缺口：stop_reason=ambiguous 可与 answer.status=answered 同时出现，UI 收到矛盾信号。"""
    outcome, _fact = _answered_outcome()
    inconsistent = SearchOutcome(outcome.request_id, outcome.answer, outcome.evidence, "ambiguous")
    assert inconsistent.stop_reason == "ambiguous"
    assert inconsistent.status == "answered"


def test_gap_task_event_seq_default_zero_hides_forgotten_seq():
    """缺口：seq 兼容默认 0，生产者忘记赋值时事件全为 0，C 的丢弃规则会吞掉进度。"""
    first = TaskEvent("task-c", "request-c", "running", 1, 12)
    second = TaskEvent("task-c", "request-c", "running", 2, 12)
    tracker = ProgressTracker()
    assert tracker.accept(first)
    assert not tracker.accept(second)  # 两个事件序号相同 → 第二个被丢弃


def test_gap_search_filters_have_no_chat_types():
    """缺口（与 B 的 B 侧评审一致）：REQ-022 需要"只看群聊/私聊"，Filters 只能逐个列 chat_ids。"""
    names = {f.name for f in fields(SearchFilters)}
    assert "chat_types" not in names
    assert "chat_ids" in names and "source_ids" in names
