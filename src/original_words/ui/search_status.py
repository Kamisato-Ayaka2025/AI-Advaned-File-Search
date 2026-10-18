"""搜索状态栏（C 线所有；ADR-001 §6 指定 C 的文件）。

职责：首批原话计数、阶段进度、缺口/覆盖提示、错误展示与取消按钮。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QWidget,
)

from original_words.application.dtos import ServiceError, TaskEvent, TaskState


class TaskStatusBar(QStatusBar):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._badges = QLabel("")
        self._phase = QLabel("")
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(180)
        self._progress.setVisible(False)
        self._cancel = QPushButton("取消")
        self._cancel.setVisible(False)
        self._cancel.clicked.connect(self.cancel_requested)
        self._error = QLabel("")
        self._error.setStyleSheet("color: #b00020;")
        self.addWidget(self._badges, 0)
        self.addPermanentWidget(self._error)
        self.addPermanentWidget(self._phase)
        self.addPermanentWidget(self._progress)
        self.addPermanentWidget(self._cancel)

    def set_badges(self, badges: list[str]) -> None:
        self._badges.setText("  |  ".join(badges))

    def set_phase(self, phase: str) -> None:
        self._phase.setText(phase)

    def set_error(self, error: ServiceError | str | None) -> None:
        if error is None:
            self._error.setText("")
            return
        self._error.setText(error.user_message if isinstance(error, ServiceError) else str(error))

    def set_task_running(self, running: bool) -> None:
        self._progress.setVisible(running)
        self._cancel.setVisible(running)

    def on_task_event(self, event: TaskEvent) -> None:
        if event.state is TaskState.RUNNING:
            if event.total:
                self._progress.setRange(0, event.total)
                self._progress.setValue(event.completed or 0)
            else:
                self._progress.setRange(0, 0)
            self.set_task_running(True)
        elif event.state in (TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED):
            self.set_task_running(False)
            self._progress.setRange(0, 100)
            self._progress.setValue(0 if event.state is not TaskState.SUCCEEDED else 100)
            if event.error is not None:
                self.set_error(event.error)
        elif event.state is TaskState.QUEUED:
            self.set_phase("排队中…")


class BadgeRow(QWidget):
    """窗口顶部模式徽标行（演示数据/离线/降级等，REQ-031 要求明确标注）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("")
        self._label.setStyleSheet("color: #555; padding: 2px 6px;")
        layout.addWidget(self._label)
        layout.addStretch(1)

    def set_badges(self, badges: list[str]) -> None:
        self._label.setText("　".join(f"〔{b}〕" for b in badges))
