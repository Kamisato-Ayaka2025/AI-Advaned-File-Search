"""答案视图（C 线所有）：结论 + 可点击引用卡片 + 模式/耗时/覆盖提示。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from original_words.application.dtos import Answer, Citation


class CitationCard(QFrame):
    locate_requested = Signal(str, str)  # chat_id, message_id

    def __init__(self, index: int, citation: Citation, parent=None) -> None:
        super().__init__(parent)
        self.citation = citation
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        ts = citation.timestamp.strftime("%Y-%m-%d %H:%M") if citation.timestamp else "时间未知"
        head = QLabel(f"<b>[{index}]</b> {ts}　{citation.sender_name}（{citation.chat_name}）")
        layout.addWidget(head)
        text = QLabel(citation.text or "（无文本，图片/文件消息）")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(text)
        locate = QPushButton("在应用中定位")
        locate.clicked.connect(
            lambda: self.locate_requested.emit(citation.chat_id, citation.message_id)
        )
        layout.addWidget(locate)


class AnswerView(QWidget):
    locate_requested = Signal(str, str)
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._export = QPushButton("导出答案（Markdown/JSON）")
        self._export.setEnabled(False)
        self._export.clicked.connect(self.export_requested)
        outer.addWidget(self._export)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._answer: Answer | None = None

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def show_answer(self, query: str, answer: Answer, streaming: bool = False) -> None:
        self._answer = answer
        self._clear_layout()
        query_label = QLabel(f"<b>查询：{query}</b>")
        query_label.setWordWrap(True)
        self._layout.addWidget(query_label)
        status_text = {"answered": "已回答", "no_evidence": "没找到", "partial": "部分结果"}.get(
            answer.status, answer.status
        )
        streaming_tag = "　生成中…" if streaming else ""
        status = QLabel(f"状态：{status_text}　模式：{answer.mode}{streaming_tag}")
        self._layout.addWidget(status)
        for claim in answer.claims:
            claim_label = QLabel(claim.text)
            claim_label.setWordWrap(True)
            claim_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._layout.addWidget(claim_label)
        if answer.citations:
            header = QLabel(f"引用原话（{len(answer.citations)} 条，点击可定位）")
            self._layout.addWidget(header)
        for index, citation in enumerate(answer.citations, start=1):
            card = CitationCard(index, citation)
            card.locate_requested.connect(self.locate_requested)
            self._layout.addWidget(card)
        footer = f"耗时 {answer.elapsed_ms} ms · 调用 {answer.calls} 次 · 约 {answer.tokens} tokens"
        if answer.stop_reason:
            footer += f" · 结束原因：{answer.stop_reason}"
        self._layout.addWidget(QLabel(footer))
        if answer.coverage_note:
            note = QLabel(answer.coverage_note)
            note.setWordWrap(True)
            note.setStyleSheet("color: #666; background: #f2f2f2; padding: 4px;")
            self._layout.addWidget(note)
        self._export.setEnabled(True)

    def show_notice(self, text: str) -> None:
        self._answer = None
        self._notice_text = text
        self._clear_layout()
        notice = QLabel(text)
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #1a73e8; padding: 6px;")
        self._layout.addWidget(notice)
        self._export.setEnabled(False)
