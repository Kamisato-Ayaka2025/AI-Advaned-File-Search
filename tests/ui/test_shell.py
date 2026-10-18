"""窗口骨架与降级可见性（REQ-002/030/031）。"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from original_words.ui.settings_dialog import SettingsDialog


def test_window_badges_and_data(window):
    assert "演示数据（合成）" in window.badge_row._label.text()
    assert "3 个会话" in window.stats_label.text()
    assert window.chat_list._list.count() == 4  # 全部会话 + 3 个会话
    assert window.status_bar._badges.text()


def test_no_key_degradation_local_demo_answer(window, qtbot):
    window.on_search("供应商最后换了哪家")
    qtbot.waitUntil(
        lambda: (
            (window._worker is None or not window._worker.isRunning())
            and window._last_answer is not None
        ),
        timeout=30000,
    )
    answer = window._last_answer
    assert answer.mode == "demo"
    assert "未配置 API Key" in window.status_bar._badges.text()
    assert "BM25 降级" in window.status_bar._badges.text()


def test_settings_connection_test_good_and_bad(container, qtbot):
    dialog = SettingsDialog(container)
    qtbot.addWidget(dialog)
    dialog._api_key.setText("bad-key")
    dialog._test_connection()
    assert "失败" in dialog._test_result.text()

    dialog._api_key.setText("sk-123456789012")
    dialog._test_connection()
    assert "成功" in dialog._test_result.text()


def test_delete_data_double_confirm(container, qtbot, monkeypatch):
    container.load_demo()
    assert container.repo.stats()["message_count"] > 0
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog = SettingsDialog(container)
    qtbot.addWidget(dialog)
    dialog._delete_data()
    assert container.repo.stats()["message_count"] == 0
    assert container.index.get_active_revision() >= 1  # 删除后重建索引
