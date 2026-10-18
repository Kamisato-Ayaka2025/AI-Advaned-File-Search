"""检索结果视图（C 线所有）：首批原话命中卡片，点击进入上下文。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from original_words.application.dtos import SearchHit


class HitCard(QFrame):
    def __init__(self, hit: SearchHit, chat_name: str, snippet: str, parent=None) -> None:
        super().__init__(parent)
        self.hit = hit
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        head = QLabel(f"<b>{chat_name}</b>　命中 {len(hit.message_ids)} 条　分数 {hit.score}")
        head.setWordWrap(True)
        layout.addWidget(head)
        reasons = QLabel(" · ".join(hit.reasons) if hit.reasons else "相关原话")
        reasons.setStyleSheet("color: #1a73e8;")
        reasons.setWordWrap(True)
        layout.addWidget(reasons)
        text = QLabel(snippet)
        text.setWordWrap(True)
        text.setStyleSheet("color: #333; background: #f7f7f7; padding: 4px;")
        layout.addWidget(text)


class ResultsView(QWidget):
    hit_activated = Signal(str, str)  # chat_id, anchor message_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._summary = QLabel("尚未检索")
        layout.addWidget(self._summary)
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)
        self._hits: list[SearchHit] = []

    def clear(self) -> None:
        self._hits = []
        self._list.clear()
        self._summary.setText("尚未检索")

    def show_hits(self, hits: list[SearchHit], elapsed_ms: float, anchor_by_chunk: dict) -> None:
        self._hits = hits
        self._anchor = anchor_by_chunk
        self._list.clear()
        self._summary.setText(f"首批原话：{len(hits)} 个片段命中 · 用时 {elapsed_ms} ms")
        for hit in hits:
            chat_id, chat_name, snippet = anchor_by_chunk.get(hit.chunk_id, ("", "", ""))
            card = HitCard(hit, chat_name, snippet)
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, card)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        index = self._list.row(item)
        if 0 <= index < len(self._hits):
            hit = self._hits[index]
            chat_id = self._anchor.get(hit.chunk_id, ("", "", ""))[0]
            self.hit_activated.emit(chat_id, hit.message_ids[0])
