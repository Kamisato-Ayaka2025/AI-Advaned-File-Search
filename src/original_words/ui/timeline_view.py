"""时间线视图（C 线所有）：按时间升序、未知时间单列，点击定位。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from original_words.application.dtos import TimelineNode


class TimelineView(QWidget):
    locate_requested = Signal(str, str)  # chat_id, message_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("时间线（点击定位）"))
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_clicked)
        layout.addWidget(self._list)
        self._nodes: list[TimelineNode] = []

    def show_nodes(self, nodes: list[TimelineNode]) -> None:
        self._nodes = nodes
        self._list.clear()
        unknown_added = False
        for node in nodes:
            if node.unknown_time and not unknown_added:
                unknown_added = True
                self._list.addItem("── 时间未知（按来源顺序）──")
            if node.timestamp is None:
                time_text = "时间未知"
            else:
                time_text = node.timestamp.strftime("%m-%d %H:%M")
            item = QListWidgetItem(
                f"{time_text}　{node.chat_name} · {node.sender_name}：{node.snippet[:40]}"
            )
            item.setData(256, node.message_id)
            self._list.addItem(item)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        message_id = item.data(256)
        node = next((n for n in self._nodes if n.message_id == message_id), None)
        if node is not None:
            self.locate_requested.emit(node.chat_id, node.message_id)
