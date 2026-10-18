"""C-01 五个演示场景（G4）：3 条有证据查询 + 1 条无证据 + 1 次应用内定位。"""

from __future__ import annotations


def wait_idle(qtbot, window, timeout: int = 30000) -> None:
    def idle() -> bool:
        worker = window._worker
        return worker is None or not worker.isRunning()

    qtbot.waitUntil(idle, timeout=timeout)


def wait_answer(qtbot, window, timeout: int = 30000) -> None:
    qtbot.waitUntil(lambda: window._last_answer is not None, timeout=timeout)


def test_scenario1_who_opposed_first(window, qtbot):
    window.on_search("谁最先反对换供应商")
    wait_idle(qtbot, window)
    wait_answer(qtbot, window)
    answer = window._last_answer
    assert answer.status == "answered"
    assert any("李娜" in claim.text and "最先提出反对" in claim.text for claim in answer.claims)
    assert len(answer.citations) >= 1
    assert answer.mode == "demo"  # 无 Key：本地罐头答案，不发外网


def test_scenario2_supplier_with_three_citations(window, qtbot):
    window.on_search("供应商最后换了哪家")
    wait_idle(qtbot, window)
    wait_answer(qtbot, window)
    answer = window._last_answer
    assert answer.status == "answered"
    assert len(answer.citations) >= 3, "「换供应商」至少 3 处引用（Plan 8.2）"
    assert any("B 供应商" in claim.text for claim in answer.claims)


def test_scenario3_soft_hints_and_answer(window, qtbot):
    window.on_search("张伟三月提到的登录 bug 后来怎么处理了")
    wait_idle(qtbot, window)
    wait_answer(qtbot, window)
    understanding = window.search_panel._understanding.text()
    assert "软线索" in understanding
    assert "张伟" in understanding and "三月" in understanding
    answer = window._last_answer
    assert any("自动重试" in claim.text for claim in answer.claims)


def test_scenario4_no_evidence_not_fabricated(window, qtbot):
    window.on_search("冰岛团建是哪天定的")
    wait_idle(qtbot, window)
    wait_answer(qtbot, window)
    answer = window._last_answer
    assert answer.status == "no_evidence"
    assert not answer.citations, "无证据不得编造引用"
    assert any("没找到" in claim.text for claim in answer.claims)
    assert "覆盖范围" in answer.coverage_note
    assert not window._last_hits


def test_scenario5_locate_citation_to_context(window, qtbot):
    window.on_search("供应商最后换了哪家")
    wait_idle(qtbot, window)
    wait_answer(qtbot, window)
    citation = window._last_answer.citations[0]
    window.locate_message(citation.chat_id, citation.message_id)
    assert window.stack.currentIndex() == 1
    ctx = window.context_view._window
    assert ctx.anchor_id == citation.message_id
    assert any(m.message_id == citation.message_id for m in ctx.messages)


def test_timeline_sorted_and_unknown_last(window, qtbot):
    window.on_search("供应商最后换了哪家")
    wait_idle(qtbot, window)
    wait_answer(qtbot, window)
    nodes = window.timeline_view._nodes
    known = [n for n in nodes if not n.unknown_time]
    times = [n.timestamp for n in known]
    assert times == sorted(times), "时间线应按时间升序"
    unknown = [n for n in nodes if n.unknown_time]
    if unknown:
        assert all(n.unknown_time for n in nodes[len(known) :]), "未知时间节点应排在最后"


def test_context_window_boundaries(window):
    repo = window.container.repo
    demo_id = "demo:chat_project:"

    start = repo.get_context("chat_project", f"{demo_id}000001")
    assert start.anchor_index == 0
    assert not start.clipped_start
    assert len(start.messages) == 11  # 开头只有后 10 条

    middle = repo.get_context("chat_project", f"{demo_id}000020")
    assert middle.clipped_start
    assert middle.anchor_index == 10
    assert len(middle.messages) == 21  # 前后各 10 条 + 锚点

    tail = repo.get_context("chat_project", f"{demo_id}000680")
    assert tail.clipped_end
    assert len(tail.messages) == 21


def test_quote_jump_within_window(window):
    repo = window.container.repo
    window_ct = repo.get_context("chat_project", "demo:chat_project:000200")
    quoted = next((m for m in window_ct.messages if m.quote_of is not None), None)
    assert quoted is not None
    assert any(m.message_id == quoted.quote_of for m in window_ct.messages), (
        "被引用的消息应落在 ±10 上下文内，可应用内跳转"
    )


def test_unknown_time_messages_exist_and_marked(window):
    repo = window.container.repo
    unknowns = [m for m in repo._messages.values() if m.timestamp is None]
    assert len(unknowns) >= 10
    for msg in unknowns:
        assert msg.timestamp_status == "unknown"
        assert msg.timestamp_precision is None
        assert msg.timestamp is None
    # 未知时间消息不得伪造时间（Plan §4.1）
    assert all(isinstance(m.timestamp, type(None)) for m in unknowns)
