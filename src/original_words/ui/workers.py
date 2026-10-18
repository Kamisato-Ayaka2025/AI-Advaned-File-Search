"""后台工作线程（C 线所有）。

Plan §6：Qt 主线程只更新 UI；磁盘/检索/回答等任务在 QThread 中执行，
经信号回传结果；取消为协作式（检查取消标志），不强制杀线程。
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

from original_words.application.dtos import ServiceError, TaskState
from original_words.application.mocks import make_task_event


class Worker(QThread):
    """通用服务调用线程。

    fn(progress, should_cancel) -> result；progress(completed, total) 回调把
    TaskEvent 通过 progress 信号送回主线程。
    """

    progress = Signal(object)  # TaskEvent
    result = Signal(object)
    failed = Signal(object)  # Exception / ServiceError
    token = Signal(str)  # 流式 token（跨线程经排队信号回主线程）

    def __init__(
        self,
        task_id: str,
        fn: Callable,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._task_id = task_id
        self._fn = fn
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def _should_cancel(self) -> bool:
        return self._cancel_requested

    def _emit_progress(self, completed: int | None, total: int | None) -> None:
        self.progress.emit(
            make_task_event(
                self._task_id,
                TaskState.RUNNING,
                completed=completed,
                total=total,
            )
        )

    def run(self) -> None:
        self.progress.emit(
            make_task_event(self._task_id, TaskState.RUNNING, completed=0, total=None)
        )
        try:
            value = self._fn(self._emit_progress, self._should_cancel)
        except ServiceError as exc:
            self.progress.emit(make_task_event(self._task_id, TaskState.FAILED, error=exc))
            self.failed.emit(exc)
            return
        except Exception as exc:  # noqa: BLE001 兜底：异常堆栈不含原文/密钥
            wrapped = ServiceError(
                type(exc).__name__,
                f"内部错误：{exc}",
                retryable=False,
            )
            self.progress.emit(make_task_event(self._task_id, TaskState.FAILED, error=wrapped))
            self.failed.emit(wrapped)
            return
        self.progress.emit(make_task_event(self._task_id, TaskState.SUCCEEDED))
        self.result.emit(value)
