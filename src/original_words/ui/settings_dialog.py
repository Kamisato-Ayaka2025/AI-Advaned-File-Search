"""设置对话框（C 线所有；REQ-024/026/027/028）。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

PRIVACY_NOTICE = (
    "隐私与本地优先（REQ-026）：聊天原文、索引与附件默认仅存储在本地；"
    "云端仅发送你同意的片段；发送前有预览与同意；本地数据库与索引加密；"
    "不上传原始聊天库、不用于训练。"
)


class SettingsDialog(QDialog):
    def __init__(self, container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # ---- LLM 配置 ----
        llm = QWidget()
        form = QFormLayout(llm)
        self._base_url = QLineEdit(self._container.secrets.get("base_url"))
        form.addRow("Base URL", self._base_url)
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        masked = self._container.secrets.masked_key()
        placeholder = f"已保存：{masked}" if masked else "输入 DeepSeek API Key（sk-…）"
        self._api_key.setPlaceholderText(placeholder)
        form.addRow("API Key（不回显）", self._api_key)
        self._model = QComboBox()
        self._model.addItems(["deepseek-flash", "deepseek-v4-pro"])
        current = self._container.secrets.get("model")
        if current in ("deepseek-flash", "deepseek-v4-pro"):
            self._model.setCurrentText(current)
        form.addRow("模型", self._model)
        self._timeout = QSpinBox()
        self._timeout.setRange(5, 300)
        self._timeout.setValue(int(self._container.secrets.get("timeout") or "30"))
        form.addRow("超时（秒）", self._timeout)
        self._retry = QSpinBox()
        self._retry.setRange(0, 5)
        self._retry.setValue(int(self._container.secrets.get("retry") or "2"))
        form.addRow("重试次数", self._retry)
        test_row = QHBoxLayout()
        test_btn = QPushButton("测试连接")
        self._test_result = QLabel("")
        test_row.addWidget(test_btn)
        test_row.addWidget(self._test_result, 1)
        form.addRow("", test_row)
        test_btn.clicked.connect(self._test_connection)
        tabs.addTab(llm, "DeepSeek 配置")

        # ---- 隐私与数据 ----
        privacy = QWidget()
        privacy_layout = QVBoxLayout(privacy)
        notice = QLabel(PRIVACY_NOTICE)
        notice.setWordWrap(True)
        privacy_layout.addWidget(notice)
        delete_row = QHBoxLayout()
        delete_btn = QPushButton("删除本地数据")
        self._delete_result = QLabel("")
        delete_row.addWidget(delete_btn)
        delete_row.addWidget(self._delete_result, 1)
        privacy_layout.addLayout(delete_row)
        privacy_layout.addStretch(1)
        delete_btn.clicked.connect(self._delete_data)
        tabs.addTab(privacy, "隐私与数据")

        # ---- 关于 ----
        about = QWidget()
        about_layout = QVBoxLayout(about)
        about_layout.addWidget(QLabel("原话考古 v0.1.0"))
        about_layout.addWidget(
            QLabel(
                "演示模式（REQ-031）：内置合成演示数据，标注「演示数据（合成）」，"
                "断网、无 API Key 均可演示。"
            )
        )
        about_layout.addStretch(1)
        tabs.addTab(about, "关于")

        layout.addWidget(tabs)
        buttons = QDialogButtonBox()
        save = buttons.addButton("保存", QDialogButtonBox.ButtonRole.AcceptRole)
        close = buttons.addButton("关闭", QDialogButtonBox.ButtonRole.RejectRole)
        save.clicked.connect(self._save)
        close.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        secrets = self._container.secrets
        secrets.set("base_url", self._base_url.text().strip())
        key = self._api_key.text().strip()
        if key:
            secrets.set("api_key", key)
        secrets.set("model", self._model.currentText())
        secrets.set("timeout", str(self._timeout.value()))
        secrets.set("retry", str(self._retry.value()))
        self.accept()

    def _test_connection(self) -> None:
        key = self._api_key.text().strip() or self._container.secrets.get("api_key")
        if key.startswith("sk-") and len(key) >= 12:
            self._test_result.setText("连接测试成功（mock：密钥格式有效）")
            self._test_result.setStyleSheet("color: #188038;")
        elif not key:
            self._test_result.setText("失败：未配置 API Key（当前为本地片段模式）")
            self._test_result.setStyleSheet("color: #b00020;")
        else:
            self._test_result.setText("失败：密钥无效（需以 sk- 开头且长度 ≥ 12）")
            self._test_result.setStyleSheet("color: #b00020;")

    def _delete_data(self) -> None:
        confirm = QMessageBox.question(
            self,
            "删除本地数据",
            "将删除全部本地消息与索引（本版本为内存 mock，重启后即清空）。\n确定删除？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        again = QMessageBox.question(
            self,
            "二次确认",
            "此操作不可恢复（REQ-027 删除前二次确认）。仍要删除？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if again != QMessageBox.StandardButton.Yes:
            self._delete_result.setText("已取消")
            return
        results = self._container.lifecycle.delete()
        self._container.index.rebuild()
        summary = "；".join(f"{item}：{note}" for item, _ok, note in results)
        self._delete_result.setText(summary)
