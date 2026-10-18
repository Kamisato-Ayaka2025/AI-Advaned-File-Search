"""上下文视图（C 线所有）：锚点前后各 10 条、引用展开、未知时间单列。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from original_words.application.dtos import ContextWindow, Message


class MessageBubble(QWidget):
    quote_requested = Signal(str)  # quote_of message_id

    def __init__(self, msg: Message, anchor: bool, parent=None) -> None:
        super().__init__(parent)
        self.msg = msg
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        if msg.timestamp_status == "unknown" or msg.timestamp is None:
            time_text = "时间未知"
        else:
            time_text = msg.timestamp.strftime("%Y-%m-%d %H:%M")
        head = QLabel(f"{time_text}　{msg.sender_name}")
        head.setStyleSheet("font-weight: bold;")
        layout.addWidget(head)
        body = QLabel()
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if msg.message_type == "image":
            attachment = msg.attachment_ref or {}
            available = attachment.get("available", False)
            name = attachment.get("name", "图片")
            body.setText(f"🖼 {name}" + ("（附件缺失，无法预览）" if not available else ""))
        elif msg.message_type == "file":
            attachment = msg.attachment_ref or {}
            available = attachment.get("available", False)
            name = attachment.get("name", "文件")
            body.setText(f"📄 {name}" + ("（附件缺失）" if not available else ""))
        elif msg.message_type == "recalled":
            body.setText("（消息已撤回）")
            body.setStyleSheet("color: #888; font-style: italic;")
        else:
            body.setText(msg.content or "（空消息）")
        layout.addWidget(body)
        if msg.quote_of:
            quote_btn = QPushButton("↩ 查看被引用的消息")
            quote_btn.clicked.connect(lambda: self.quote_requested.emit(msg.quote_of))
            layout.addWidget(quote_btn)
        if anchor:
            self.setStyleSheet("MessageBubble { background: #fff3c4; border: 1px solid #e0b400; }")


class ContextView(QWidget):
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        head_row = QVBoxLayout()
        self._title = QLabel("")
        self._title.setWordWrap(True)
        head_row.addWidget(self._title)
        back = QPushButton("← 返回结果")
        back.clicked.connect(self.back_requested)
        head_row.addWidget(back)
        layout.addLayout(head_row)
        self._list = QListWidget()
        layout.addWidget(self._list)

    def show_window(self, window: ContextWindow) -> None:
        self._window = window
        self._list.clear()
        clip = ""
        if window.clipped_start:
            clip += "（上方还有更早消息）"
        if window.clipped_end:
            clip += "（下方还有更多消息）"
        self._title.setText(
            f"<b>{window.chat.chat_name}</b>　上下文 ±10 条 · 共 {len(window.messages)} 条{clip}"
        )
        unknown_header_added = False
        for index, msg in enumerate(window.messages):
            if msg.timestamp is None and not unknown_header_added:
                unknown_header_added = True
                header = QListWidgetItem("── 以下消息时间未知（按来源顺序）──")
                header.setFlags(header.flags() & ~header.ItemFlag.ItemIsSelectable)
                self._list.addItem(header)
            bubble = MessageBubble(msg, anchor=(index == window.anchor_index))
            bubble.quote_requested.connect(self._jump_to_quote)
            item = QListWidgetItem()
            item.setSizeHint(bubble.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, bubble)
            if index == window.anchor_index:
                self._list.scrollToItem(item)
                self._list.setCurrentItem(item)

    def _jump_to_quote(self, quote_id: str) -> None:
        for row in range(self._list.count()):
            widget = self._list.itemWidget(self._list.item(row))
            if isinstance(widget, MessageBubble) and widget.msg.message_id == quote_id:
                self._list.scrollToItem(self._list.item(row))
                self._list.setCurrentItem(self._list.item(row))
                return
