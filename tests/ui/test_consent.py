"""C-02 发送同意（REQ-025）：默认拒绝、完整/部分片段、一次性/按次、编辑失效、撤回。"""

from __future__ import annotations

import pytest

from original_words.application.dtos import ErrorCode, SearchRequest, ServiceError
from original_words.ui.consent_dialog import ConsentDialog


def _hits(container, query: str = "供应商"):
    container.load_demo()
    parsed = container.search_service.parse_local(query)
    request = SearchRequest(request_id="t", query=query, filters=parsed.hard_filters)
    return container.search_service.search(request)[0]


# ---------------------------------------------------------------------------
# 服务层：同意校验


def test_default_deny_without_grant(container):
    container.secrets.set("api_key", "sk-abcdefgh1234")
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    with pytest.raises(ServiceError) as exc_info:
        container.generate(plan, "供应商最后换了哪家", hits)
    assert exc_info.value.code is ErrorCode.CONSENT_REQUIRED


def test_grant_then_generate(container):
    container.secrets.set("api_key", "sk-abcdefgh1234")
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    container.consent.grant(plan.request_id, plan.payload_hash, plan.consent_scope)
    answer = container.generate(plan, "供应商最后换了哪家", hits)
    assert answer.mode == "llm_sim"
    assert answer.calls == 1


def test_one_time_consent_consumed(container):
    container.secrets.set("api_key", "sk-abcdefgh1234")
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    container.consent.grant(plan.request_id, plan.payload_hash, "one_time")
    container.generate(plan, "供应商最后换了哪家", hits)
    with pytest.raises(ServiceError) as exc_info:
        container.generate(plan, "供应商最后换了哪家", hits)
    assert exc_info.value.code is ErrorCode.CONSENT_REQUIRED, "一次性同意用后即失效"


def test_session_scope_and_revoke(container):
    container.secrets.set("api_key", "sk-abcdefgh1234")
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    container.consent.grant(plan.request_id, plan.payload_hash, "session")
    container.generate(plan, "供应商最后换了哪家", hits)
    container.generate(plan, "供应商最后换了哪家", hits)  # 会话内可复用
    container.consent.revoke()
    with pytest.raises(ServiceError) as exc_info:
        container.generate(plan, "供应商最后换了哪家", hits)
    assert exc_info.value.code is ErrorCode.CONSENT_REQUIRED, "撤回后阻止后续发送"


def test_edited_preview_invalidates_grant(container):
    container.secrets.set("api_key", "sk-abcdefgh1234")
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    container.consent.grant(plan.request_id, plan.payload_hash, "session")
    edited = container.update_selection(
        plan, plan.selected_message_ids, "full", edited_preview="修改后的内容"
    )
    assert edited.payload_hash != plan.payload_hash
    with pytest.raises(ServiceError) as exc_info:
        container.generate(edited, "供应商最后换了哪家", hits)
    assert exc_info.value.code is ErrorCode.CONSENT_REQUIRED, "编辑预览后旧授权失效"


def test_partial_mode_smaller_payload(container):
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    subset = plan.selected_message_ids[:2]
    partial = container.update_selection(plan, subset, "partial")
    assert partial.mode == "partial"
    assert len(partial.selected_message_ids) == 2 < len(plan.selected_message_ids)
    assert partial.preview_text != plan.preview_text
    assert partial.payload_hash != plan.payload_hash


# ---------------------------------------------------------------------------
# UI 层：对话框行为 + 拒绝/同意两条路径


def _make_dialog(container, plan, messages, qtbot):
    dialog = ConsentDialog(plan, messages, container.update_selection, container.consent.revoke)
    qtbot.addWidget(dialog)
    return dialog


def test_dialog_partial_mode_updates_preview(container, qtbot):
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    messages = container.preview_messages(hits)
    dialog = _make_dialog(container, plan, messages, qtbot)
    dialog._partial_radio.setChecked(True)
    assert dialog._preview.isReadOnly()
    first_check = next(iter(dialog._checkboxes.values()))
    first_check.setChecked(False)
    partial_text = dialog._preview.toPlainText()
    dialog._on_approve()
    assert dialog.approved
    assert dialog.final_plan.mode == "partial"
    assert dialog.final_plan.preview_text == partial_text


def test_dialog_edit_full_preview_changes_hash(container, qtbot):
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    messages = container.preview_messages(hits)
    dialog = _make_dialog(container, plan, messages, qtbot)
    dialog._preview.setPlainText("手工编辑后的预览")
    assert dialog.preview_edited
    dialog._on_approve()
    assert dialog.final_plan.payload_hash != plan.payload_hash


def test_dialog_revoke_all(container, qtbot):
    hits = _hits(container)
    plan = container.prepare_send("r1", "供应商最后换了哪家", hits)
    container.consent.grant(plan.request_id, plan.payload_hash, "session")
    messages = container.preview_messages(hits)
    dialog = _make_dialog(container, plan, messages, qtbot)
    dialog._on_revoke()
    assert container.consent.list_active() == []


class _FakeDialog:
    """代替真实模态对话框；approved 可配置。"""

    approved: bool = False

    def __init__(self, plan, _messages, _update, _revoke, _parent=None):
        self.plan = plan
        self.final_plan = plan

    def exec(self):  # noqa: A003 保持与 QDialog 同接口
        return 0


def test_ui_deny_path(container, window, qtbot, monkeypatch):
    import original_words.ui.main_window as mw

    container.secrets.set("api_key", "sk-abcdefgh1234")
    _FakeDialog.approved = False
    monkeypatch.setattr(mw, "ConsentDialog", _FakeDialog)
    window.on_search("供应商最后换了哪家")
    qtbot.waitUntil(lambda: window._worker is None or not window._worker.isRunning(), timeout=30000)
    assert window._last_answer is None
    assert "已拒绝发送" in window.answer_view._notice_text


def test_ui_approve_path(container, window, qtbot, monkeypatch):
    import original_words.ui.main_window as mw

    container.secrets.set("api_key", "sk-abcdefgh1234")
    _FakeDialog.approved = True
    monkeypatch.setattr(mw, "ConsentDialog", _FakeDialog)
    window.on_search("供应商最后换了哪家")
    qtbot.waitUntil(
        lambda: (
            (window._worker is None or not window._worker.isRunning())
            and window._last_answer is not None
        ),
        timeout=30000,
    )
    assert window._last_answer.mode == "llm_sim"
