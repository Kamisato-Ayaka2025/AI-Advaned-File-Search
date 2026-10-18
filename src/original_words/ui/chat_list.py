"""会话列表（C 线所有）。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from original_words.application.dtos import Chat


class ChatList(QWidget):
    chat_selected = Signal(object)  # Chat | None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("会话")
        layout.addWidget(title)
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self._list)
        self._chats: list[Chat] = []

    def refresh(self, chats: list[Chat], counts: dict[str, int]) -> None:
        self._chats = chats
        self._list.blockSignals(True)
        self._list.clear()
        self._list.addItem(QListWidgetItem("全部会话"))
        for chat in chats:
            kind = "群聊" if chat.chat_type == "group" else "私聊"
            item = QListWidgetItem(f"{chat.chat_name}（{kind} · {counts.get(chat.chat_id, 0)} 条）")
            item.setData(256, chat.chat_id)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._list.setCurrentRow(0)

    def _on_current_changed(self, current: QListWidgetItem | None, _prev) -> None:
        if current is None or current.data(256) is None:
            self.chat_selected.emit(None)
            return
        chat_id = current.data(256)
        self.chat_selected.emit(next((c for c in self._chats if c.chat_id == chat_id), None))
