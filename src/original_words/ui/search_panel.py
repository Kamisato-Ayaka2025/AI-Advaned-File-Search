"""搜索面板（C 线所有）：查询框、查询理解展示、过滤条。"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from original_words.application.dtos import Chat, ChatFilters, ParsedQuery


class SearchPanel(QWidget):
    search_requested = Signal(str)
    cancel_requested = Signal()
    filters_changed = Signal(object)  # ChatFilters

    TIME_ALL = "全部时间"
    TIME_30D = "最近 30 天"
    TIME_CUSTOM = "自定义范围"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        query_row = QHBoxLayout()
        self._query = QLineEdit()
        self._query.setPlaceholderText("输入自然语言查询，例如：谁最先反对换供应商")
        self._query.returnPressed.connect(self._emit_search)
        query_row.addWidget(self._query, 1)
        self._search_btn = QPushButton("搜索")
        self._search_btn.clicked.connect(self._emit_search)
        query_row.addWidget(self._search_btn)
        layout.addLayout(query_row)

        self._understanding = QLabel("")
        self._understanding.setWordWrap(True)
        self._understanding.setStyleSheet("color: #1a73e8;")
        layout.addWidget(self._understanding)

        filter_row = QHBoxLayout()
        self._chat_type = QComboBox()
        self._chat_type.addItems(["全部会话类型", "群聊", "私聊"])
        self._sender = QComboBox()
        self._sender.addItem("全部发送者")
        self._chat = QComboBox()
        self._chat.addItem("全部会话")
        self._time = QComboBox()
        self._time.addItems([self.TIME_ALL, self.TIME_30D, self.TIME_CUSTOM])
        self._msg_type = QComboBox()
        self._msg_type.addItems(["全部类型", "文本", "图片", "文件", "系统", "撤回"])
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        self._start_date.setVisible(False)
        self._end_date.setVisible(False)
        for widget in (self._chat_type, self._sender, self._chat, self._time, self._msg_type):
            filter_row.addWidget(widget)
        filter_row.addWidget(QLabel("起"))
        filter_row.addWidget(self._start_date)
        filter_row.addWidget(QLabel("止"))
        filter_row.addWidget(self._end_date)
        self._clear_btn = QPushButton("清除过滤")
        self._clear_btn.clicked.connect(self._clear_filters)
        filter_row.addWidget(self._clear_btn)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self._time.currentTextChanged.connect(self._on_time_mode)
        for combo in (self._chat_type, self._sender, self._chat, self._time, self._msg_type):
            combo.currentIndexChanged.connect(self._emit_filters)

    # ---- 数据填充 ----

    def set_senders(self, names: list[str]) -> None:
        self._sender.blockSignals(True)
        self._sender.clear()
        self._sender.addItem("全部发送者")
        self._sender.addItems(names)
        self._sender.blockSignals(False)

    def set_chats(self, chats: list[Chat]) -> None:
        self._chat.blockSignals(True)
        self._chat.clear()
        self._chat.addItem("全部会话")
        for chat in chats:
            self._chat.addItem(chat.chat_name, chat.chat_id)
        self._chat.blockSignals(False)

    # ---- 查询理解 ----

    def show_understanding(self, parsed: ParsedQuery, filters: ChatFilters) -> None:
        parts = [f"意图：{parsed.intent}"]
        hard = self._describe_filters(filters)
        if hard:
            parts.append(f"硬过滤：{hard}")
        if parsed.soft_hints:
            parts.append(f"软线索：{'；'.join(parsed.soft_hints)}")
        self._understanding.setText("我理解成了什么　" + "　|　".join(parts))

    @staticmethod
    def _describe_filters(filters: ChatFilters) -> str:
        parts = []
        if filters.chat_ids:
            parts.append(f"会话 {len(filters.chat_ids)} 个")
        if filters.chat_types:
            parts.append("/".join("群聊" if t == "group" else "私聊" for t in filters.chat_types))
        if filters.sender_names:
            parts.append(f"发送者：{'、'.join(filters.sender_names)}")
        if filters.start_time or filters.end_time:
            start = filters.start_time.strftime("%Y-%m-%d") if filters.start_time else "…"
            end = filters.end_time.strftime("%Y-%m-%d") if filters.end_time else "…"
            parts.append(f"时间 {start} ~ {end}")
        if filters.message_types:
            parts.append(f"类型：{'、'.join(filters.message_types)}")
        return "；".join(parts)

    # ---- 过滤取值 ----

    def current_filters(self) -> ChatFilters:
        filters = ChatFilters()
        chat_type = self._chat_type.currentText()
        type_map = {"群聊": "group", "私聊": "private"}
        if chat_type in type_map:
            filters = ChatFilters(chat_types=(type_map[chat_type],))
        sender = self._sender.currentText()
        if sender != "全部发送者":
            filters = ChatFilters(
                **{**filters.__dict__, "sender_names": (sender,)},
            )
        chat_id = self._chat.currentData()
        if chat_id:
            filters = ChatFilters(**{**filters.__dict__, "chat_ids": (chat_id,)})
        msg_type = self._msg_type.currentText()
        type_en = {
            "文本": "text",
            "图片": "image",
            "文件": "file",
            "系统": "system",
            "撤回": "recalled",
        }
        if msg_type in type_en:
            filters = ChatFilters(**{**filters.__dict__, "message_types": (type_en[msg_type],)})
        time_mode = self._time.currentText()
        now = datetime.now()
        if time_mode == self.TIME_30D:
            start = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
            filters = ChatFilters(**{**filters.__dict__, "start_time": start})
        elif time_mode == self.TIME_CUSTOM:
            start = self._start_date.dateTime().toPython()
            end = self._end_date.dateTime().toPython() + timedelta(days=1)
            filters = ChatFilters(**{**filters.__dict__, "start_time": start, "end_time": end})
        return filters

    # ---- 事件 ----

    def _emit_search(self) -> None:
        self.search_requested.emit(self._query.text().strip())

    def _emit_filters(self) -> None:
        self.filters_changed.emit(self.current_filters())

    def _clear_filters(self) -> None:
        for combo in (self._chat_type, self._sender, self._chat, self._msg_type):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._time.blockSignals(True)
        self._time.setCurrentIndex(0)
        self._time.blockSignals(False)
        self.filters_changed.emit(self.current_filters())

    def _on_time_mode(self, text: str) -> None:
        self._start_date.setVisible(text == self.TIME_CUSTOM)
        self._end_date.setVisible(text == self.TIME_CUSTOM)

    def set_busy(self, busy: bool) -> None:
        self._search_btn.setEnabled(not busy)
        self._query.setEnabled(not busy)
