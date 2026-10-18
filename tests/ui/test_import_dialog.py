"""导入对话框（REQ-009）：授权确认、后台进度、重复导入、报告展示。"""

from __future__ import annotations

from original_words.ui.import_dialog import ImportDialog


def _make_json(path):
    path.write_text(
        (
            '[{"message_id": "m1", "chat_id": "c1", "sender_name": "张三",'
            '  "content": "会议改到明天", "timestamp": "2026-10-01T10:00:00"},'
            ' {"message_id": "m2", "chat_id": "c1", "sender_name": "李四",'
            '  "content": "收到", "timestamp": "2026-10-01T10:05:00"}]'
        ),
        encoding="utf-8",
    )
    return path


def _start(dialog):
    dialog._path.setText(str(dialog._file))
    dialog._authorize.setChecked(True)
    dialog._start_import()


def test_import_requires_authorization(container, qtbot, tmp_path):
    dialog = ImportDialog(container)
    qtbot.addWidget(dialog)
    dialog._file = _make_json(tmp_path / "data.json")
    dialog._path.setText(str(dialog._file))
    dialog._authorize.setChecked(False)
    dialog._start_import()
    assert dialog._worker is None
    assert "授权确认" in dialog._status.text()


def test_import_requires_file(container, qtbot):
    dialog = ImportDialog(container)
    qtbot.addWidget(dialog)
    dialog._start_import()
    assert dialog._worker is None
    assert "选择文件" in dialog._status.text()


def test_import_happy_path_and_duplicate(container, qtbot, tmp_path):
    dialog = ImportDialog(container)
    qtbot.addWidget(dialog)
    dialog._file = _make_json(tmp_path / "data.json")
    _start(dialog)
    qtbot.waitUntil(
        lambda: dialog._worker is not None and not dialog._worker.isRunning(),
        timeout=30000,
    )
    assert "导入完成" in dialog._report.text()
    assert "导入 2 条" in dialog._report.text()
    assert "完整性：verified_for_scope" in dialog._report.text()

    # 重复导入幂等
    _start(dialog)
    qtbot.waitUntil(lambda: not dialog._worker.isRunning(), timeout=30000)
    assert "重复 2 条" in dialog._report.text()
    assert "导入 0 条" in dialog._report.text()
