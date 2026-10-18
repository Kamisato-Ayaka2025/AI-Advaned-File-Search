"""文件导入对话框（C 线所有；REQ-009）。

JSON/CSV/TXT；授权确认；全量/最近30天/自定义范围；后台线程 + 进度 + 取消；
完成后展示导入报告（计数守恒：read = imported + duplicate + rejected）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from original_words.application.dtos import ImportReport, ServiceError
from original_words.ui.workers import Worker

TIME_ALL = "全量导入"
TIME_30D = "最近 30 天"
TIME_CUSTOM = "自定义范围"


class ImportDialog(QDialog):
    def __init__(self, container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._worker: Worker | None = None
        self.setWindowTitle("导入聊天记录（JSON / CSV / TXT）")
        self.setMinimumWidth(560)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        file_row = QHBoxLayout()
        self._path = QLineEdit()
        self._path.setReadOnly(True)
        self._path.setPlaceholderText("选择导出文件（.json / .csv / .txt）")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._pick_file)
        file_row.addWidget(self._path, 1)
        file_row.addWidget(browse)
        layout.addLayout(file_row)

        self._authorize = QCheckBox("我确认该文件为本人导出/拥有使用权，同意导入到本地")
        layout.addWidget(self._authorize)

        form = QFormLayout()
        self._time = QComboBox()
        self._time.addItems([TIME_ALL, TIME_30D, TIME_CUSTOM])
        form.addRow("导入范围", self._time)
        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("起"))
        range_row.addWidget(self._start_date)
        range_row.addWidget(QLabel("止"))
        range_row.addWidget(self._end_date)
        self._start_date.setVisible(False)
        self._end_date.setVisible(False)
        form.addRow("自定义日期", range_row)
        layout.addLayout(form)

        self._time.currentTextChanged.connect(
            lambda text: (
                self._start_date.setVisible(text == TIME_CUSTOM),
                self._end_date.setVisible(text == TIME_CUSTOM),
            )
        )

        buttons = QHBoxLayout()
        self._import_btn = QPushButton("开始导入")
        self._import_btn.clicked.connect(self._start_import)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel)
        buttons.addWidget(self._import_btn)
        buttons.addWidget(self._cancel_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._report = QLabel("")
        self._report.setWordWrap(True)
        self._report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._report)

        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.reject)
        layout.addWidget(close_btn)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择导出文件",
            "",
            "聊天记录 (*.json *.csv *.txt);;所有文件 (*.*)",
        )
        if path:
            self._path.setText(path)

    def _time_range(self) -> tuple[datetime | None, datetime | None]:
        mode = self._time.currentText()
        now = datetime.now()
        if mode == TIME_30D:
            start = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, None
        if mode == TIME_CUSTOM:
            start = self._start_date.dateTime().toPython()
            end = self._end_date.dateTime().toPython() + timedelta(days=1)
            return start, end
        return None, None

    def _start_import(self) -> None:
        path = self._path.text().strip()
        if not path:
            self._status.setText("请先选择文件")
            return
        if not self._authorize.isChecked():
            self._status.setText("请先勾选授权确认")
            return
        start, end = self._time_range()
        self._report.setText("")
        self._status.setText("")
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._import_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._worker = Worker(
            "import",
            lambda progress, cancel: self._container.import_file(
                path, start, end, on_progress=progress, cancel=cancel
            ),
            self,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.result.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_progress(self, event) -> None:
        if event.total:
            self._progress.setRange(0, event.total)
            self._progress.setValue(event.completed or 0)
        self._status.setText("正在导入…（可随时取消）")

    def _on_done(self, report: ImportReport) -> None:
        self._progress.setVisible(False)
        self._import_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        coverage = ""
        if report.coverage_start and report.coverage_end:
            coverage = (
                f"{report.coverage_start.strftime('%Y-%m-%d')} ~ "
                f"{report.coverage_end.strftime('%Y-%m-%d')}"
            )
        self._report.setText(
            "导入完成：\n"
            f"读取 {report.read_count} 条 · 导入 {report.imported_count} 条 · "
            f"重复 {report.duplicate_count} 条 · 拒绝 {report.rejected_count} 条\n"
            f"时间未知 {report.unknown_count} 条 · 附件缺失 {report.attachment_missing_count} 条\n"
            f"完整性：{report.completeness} · 覆盖范围：{coverage or '无有效时间'}\n"
            f"格式：{report.manifest.adapter_id} · 快照：{report.manifest.snapshot_hash}"
        )
        self._status.setText("导入成功")

    def _on_failed(self, error: ServiceError) -> None:
        self._progress.setVisible(False)
        self._import_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        self._status.setText(f"导入失败：{error.user_message}")
