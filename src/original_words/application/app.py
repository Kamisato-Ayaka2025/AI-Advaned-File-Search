"""应用入口组装（C 线所有）。

- 单实例锁（Plan §6：第二实例提示已有实例）。
- 组装 mock 服务容器并启动主窗口；A/B 真实服务合入后在此切换。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from original_words.application.services import ServiceContainer
from original_words.ui.main_window import MainWindow


def _lock_path() -> str:
    return str(Path(tempfile.gettempdir()) / "original_words.single.lock")


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("OriginalWords")

    lock = QLockFile(_lock_path())
    lock.setStaleLockTime(30_000)  # 崩溃后 30 秒自动视为过期
    if not lock.tryLock(0):
        QMessageBox.warning(
            None,
            "已有实例在运行",
            "原话考古已在运行中。为避免双写数据，本实例将退出。",
        )
        return 0

    container = ServiceContainer()
    window = MainWindow(container)
    window.show()
    exit_code = app.exec()
    lock.unlock()
    return exit_code
