"""发送同意对话框（C-02 原型；C 线所有）。

REQ-025：调用前展示将发送的内容；完整/部分片段可选；一次性/按次同意；
默认拒绝；编辑预览后旧授权失效（payload_hash 变化）；可撤回。
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from original_words.application.dtos import Message, SendPlan


class ConsentDialog(QDialog):
    """返回：approved（bool）、final_plan（SendPlan）。"""

    def __init__(
        self,
        plan: SendPlan,
        messages: list[Message],
        update_selection,
        revoke_all,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plan = plan
        self._messages = messages
        self._update_selection = update_selection
        self._revoke_all = revoke_all
        self._approved = False
        self._original_preview = plan.preview_text
        self.setWindowTitle("发送前预览与同意")
        self.setMinimumSize(560, 640)
        self._build()

    @property
    def approved(self) -> bool:
        return self._approved

    @property
    def final_plan(self) -> SendPlan:
        return self._plan

    @property
    def preview_edited(self) -> bool:
        if self._partial_radio.isChecked():
            return False
        return self._preview.toPlainText() != self._original_preview

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        purpose = QLabel(f"<b>用途：{self._plan.purpose}</b>")
        layout.addWidget(purpose)
        warning = QLabel(
            f"以下内容将被发送到 DeepSeek（端点：{self._plan.endpoint}，"
            f"模型：{self._plan.model}）。默认拒绝；未同意不会发送任何内容。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #b00020;")
        layout.addWidget(warning)

        mode_group = QGroupBox("发送范围")
        mode_row = QHBoxLayout(mode_group)
        self._mode_group = QButtonGroup(self)
        self._full_radio = QRadioButton("完整片段（全部候选消息）")
        self._partial_radio = QRadioButton("仅部分片段（勾选要发送的消息）")
        self._full_radio.setChecked(True)
        self._mode_group.addButton(self._full_radio)
        self._mode_group.addButton(self._partial_radio)
        mode_row.addWidget(self._full_radio)
        mode_row.addWidget(self._partial_radio)
        layout.addWidget(mode_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        message_area = QWidget()
        self._message_layout = QVBoxLayout(message_area)
        self._checkboxes: dict[str, QCheckBox] = {}
        for msg in self._messages:
            ts = msg.timestamp.strftime("%Y-%m-%d %H:%M") if msg.timestamp else "时间未知"
            text = msg.content or (msg.attachment_ref or {}).get("name", "（无文本）")
            check = QCheckBox(f"{ts} {msg.sender_name}：{text[:60]}")
            check.setChecked(True)
            check.setEnabled(False)  # 完整模式不可减选
            check.toggled.connect(self._on_selection_changed)
            self._checkboxes[msg.message_id] = check
            self._message_layout.addWidget(check)
        scroll.setWidget(message_area)
        layout.addWidget(scroll, 1)

        scope_group = QGroupBox("同意方式")
        scope_row = QHBoxLayout(scope_group)
        self._scope_group = QButtonGroup(self)
        self._one_time = QRadioButton("仅本次发送（一次性）")
        self._session = QRadioButton("本会话内按次同意")
        self._one_time.setChecked(True)
        self._scope_group.addButton(self._one_time)
        self._scope_group.addButton(self._session)
        scope_row.addWidget(self._one_time)
        scope_row.addWidget(self._session)
        layout.addWidget(scope_group)

        layout.addWidget(QLabel("发送内容预览（完整模式可编辑；编辑后需重新同意）："))
        self._preview = QPlainTextEdit(self._plan.preview_text)
        layout.addWidget(self._preview, 1)

        buttons = QDialogButtonBox()
        approve = buttons.addButton("同意并发送", QDialogButtonBox.ButtonRole.AcceptRole)
        reject = buttons.addButton("拒绝发送", QDialogButtonBox.ButtonRole.RejectRole)
        revoke = QPushButton("撤回已有授权")
        buttons.addButton(revoke, QDialogButtonBox.ButtonRole.DestructiveRole)
        approve.clicked.connect(self._on_approve)
        reject.clicked.connect(self.reject)
        revoke.clicked.connect(self._on_revoke)
        layout.addWidget(buttons)

        self._full_radio.toggled.connect(self._on_mode_changed)
        self._partial_radio.toggled.connect(self._on_mode_changed)

    def _selected_ids(self) -> tuple[str, ...]:
        return tuple(mid for mid, check in self._checkboxes.items() if check.isChecked())

    def _scope(self) -> str:
        return "session" if self._session.isChecked() else "one_time"

    def _on_mode_changed(self, checked: bool) -> None:
        if not checked:
            return
        partial = self._partial_radio.isChecked()
        for check in self._checkboxes.values():
            check.setEnabled(partial)
        self._preview.setReadOnly(partial)
        if partial:
            self._refresh_partial_preview()

    def _refresh_partial_preview(self) -> None:
        plan = self._update_selection(self._plan, self._selected_ids(), "partial")
        self._preview.blockSignals(True)
        self._preview.setPlainText(plan.preview_text)
        self._preview.blockSignals(False)

    def _on_selection_changed(self) -> None:
        if self._partial_radio.isChecked():
            self._refresh_partial_preview()

    def _on_approve(self) -> None:
        if self._partial_radio.isChecked():
            plan = self._update_selection(self._plan, self._selected_ids(), "partial")
        else:
            edited = self._preview.toPlainText()
            plan = self._update_selection(
                self._plan,
                self._selected_ids(),
                "full",
                edited_preview=edited if edited != self._original_preview else None,
            )
        self._plan = replace(plan, consent_scope=self._scope())
        self._approved = True
        self.accept()

    def _on_revoke(self) -> None:
        self._revoke_all()
        self._preview.appendPlainText("\n[已撤回全部授权：本次需重新同意后才可发送]")
