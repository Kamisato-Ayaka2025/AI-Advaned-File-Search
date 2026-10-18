"""主窗口（C 线所有）：组装搜索/过滤/结果/答案/时间线/上下文与会话列表。

流程：导入 → 查询 → 答案与引用 → 时间线 → 应用内定位（REQ-001/009/019/020/021/022）。
UI 只调用应用服务（ServiceContainer），不直接执行 SQL 或调用 DeepSeek。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from original_words.application.dtos import (
    Answer,
    ChatFilters,
    SearchHit,
    TimelineNode,
)
from original_words.ui.answer_view import AnswerView
from original_words.ui.chat_list import ChatList
from original_words.ui.consent_dialog import ConsentDialog
from original_words.ui.context_view import ContextView
from original_words.ui.import_dialog import ImportDialog
from original_words.ui.results_view import ResultsView
from original_words.ui.search_panel import SearchPanel
from original_words.ui.search_status import BadgeRow, TaskStatusBar
from original_words.ui.settings_dialog import SettingsDialog
from original_words.ui.timeline_view import TimelineView
from original_words.ui.workers import Worker


class MainWindow(QMainWindow):
    def __init__(self, container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self._worker: Worker | None = None
        self._last_query = ""
        self._last_hits: list[SearchHit] = []
        self._last_answer: Answer | None = None
        self._last_elapsed_ms = 0.0
        self.setWindowTitle("原话考古 · 本地优先聊天记录检索")
        self.resize(1280, 820)
        self._build_ui()
        self._build_menu()
        self._load_demo()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)

        self.badge_row = BadgeRow()
        root.addWidget(self.badge_row)

        self.search_panel = SearchPanel()
        self.search_panel.search_requested.connect(self.on_search)
        self.search_panel.filters_changed.connect(self._on_filters_changed)
        root.addWidget(self.search_panel)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：会话列表 + 数据概况
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_list = ChatList()
        self.chat_list.chat_selected.connect(self._on_chat_selected)
        left_layout.addWidget(self.chat_list, 1)
        self.stats_label = QLabel("")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("color: #666;")
        left_layout.addWidget(self.stats_label)
        splitter.addWidget(left)

        # 中：结果 / 上下文（栈）
        self.stack = QStackedWidget()
        self.results_view = ResultsView()
        self.results_view.hit_activated.connect(self.locate_message)
        self.context_view = ContextView()
        self.context_view.back_requested.connect(lambda: self.stack.setCurrentIndex(0))
        self.stack.addWidget(self.results_view)
        self.stack.addWidget(self.context_view)
        splitter.addWidget(self.stack)

        # 右：答案 / 时间线
        right_tabs = QTabWidget()
        self.answer_view = AnswerView()
        self.answer_view.locate_requested.connect(self.locate_message)
        self.answer_view.export_requested.connect(self.export_answer)
        self.timeline_view = TimelineView()
        self.timeline_view.locate_requested.connect(self.locate_message)
        right_tabs.addTab(self.answer_view, "答案")
        right_tabs.addTab(self.timeline_view, "时间线")
        splitter.addWidget(right_tabs)

        splitter.setSizes([220, 640, 420])
        root.addWidget(splitter, 1)

        # 演示查询快捷入口
        demo_row = QVBoxLayout()
        demo_box = QHBoxLayout()
        demo_box.addWidget(QLabel("演示查询："))
        self.demo_query_combo = QComboBox()
        for item in self.container.demo_queries:
            self.demo_query_combo.addItem(f"{item['query']}（{item['note']}）", item["query"])
        self.demo_query_combo.currentIndexChanged.connect(self._fill_demo_query)
        demo_box.addWidget(self.demo_query_combo, 1)
        demo_row.addLayout(demo_box)
        root.addLayout(demo_row)

        self.setCentralWidget(central)
        self.status_bar = TaskStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.cancel_requested.connect(self._cancel_current)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction("导入聊天记录…", self.open_import)
        file_menu.addAction("载入演示数据", self._load_demo)
        file_menu.addAction("导出答案…", self.export_answer)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        settings_menu = self.menuBar().addMenu("设置")
        settings_menu.addAction("设置…", self.open_settings)
        settings_menu.addAction("删除本地数据…", self._delete_data)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction("演示指引", self._show_demo_guide)
        help_menu.addAction("关于", self._show_about)

    # ------------------------------------------------------------------ 数据刷新

    def refresh_all(self) -> None:
        chats = self.container.repo.list_chats()
        counts = {
            chat.chat_id: len(self.container.repo.get_messages(chat.chat_id)) for chat in chats
        }
        self.chat_list.refresh(chats, counts)
        self.search_panel.set_chats(chats)
        self.search_panel.set_senders(self.container.repo.sender_names())
        badges = self.container.mode_badges()
        self.badge_row.set_badges(badges)
        self.status_bar.set_badges(badges)
        self.stats_label.setText(self.container.stats_text())
        self.results_view.clear()
        self.timeline_view.show_nodes([])
        self.answer_view.show_notice("就绪：输入查询，或从演示查询中选择一条。")

    def _load_demo(self) -> None:
        self.container.load_demo()
        self.refresh_all()

    # ------------------------------------------------------------------ 查询流

    def _on_filters_changed(self, filters: ChatFilters) -> None:
        parsed = getattr(self, "_last_parsed", None)
        if parsed is None:
            return
        self.search_panel.show_understanding(parsed, filters)

    def _on_chat_selected(self, chat) -> None:
        combo = self.search_panel._chat  # noqa: SLF001 同包内同步选择
        combo.blockSignals(True)
        if chat is None:
            combo.setCurrentIndex(0)
        else:
            index = combo.findData(chat.chat_id)
            combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self.search_panel._emit_filters()

    def _fill_demo_query(self, _index: int) -> None:
        query = self.demo_query_combo.currentData()
        if query:
            self.search_panel._query.setText(query)  # noqa: SLF001 同包内快捷填充

    def on_search(self, query: str) -> None:
        if not query:
            self.answer_view.show_notice("请输入查询内容。")
            return
        if self._worker is not None and self._worker.isRunning():
            self.answer_view.show_notice("有任务正在运行，请先取消。")
            return
        self._last_query = query
        self._last_answer = None
        try:
            parsed = self.container.parse(query)
            self._last_parsed = parsed
        except Exception as exc:  # noqa: BLE001
            self.answer_view.show_notice(str(exc))
            return
        filters = self.search_panel.current_filters()
        self.search_panel.show_understanding(parsed, filters)
        self.status_bar.set_error(None)
        self.status_bar.set_phase("本地检索中…")
        self.search_panel.set_busy(True)
        self.results_view.clear()
        self.timeline_view.show_nodes([])
        self.answer_view.show_notice("正在检索首批原话…")

        def search_fn(progress, cancel):
            return self.container.search(query, filters, on_progress=progress, cancel=cancel)

        self._worker = Worker("search", search_fn, self)
        self._worker.progress.connect(self.status_bar.on_task_event)
        self._worker.result.connect(self._on_search_done)
        self._worker.failed.connect(self._on_task_failed)
        self._worker.start()

    def _on_search_done(self, result: tuple[list[SearchHit], float]) -> None:
        hits, elapsed_ms = result
        self._last_hits = hits
        self._last_elapsed_ms = elapsed_ms
        self.search_panel.set_busy(False)
        self.status_bar.set_phase(f"检索完成：{len(hits)} 个片段 · {elapsed_ms} ms")

        anchor_by_chunk = {}
        for hit in hits:
            chunk = self.container.index.get_chunk(hit.chunk_id)
            chat = self.container.repo.get_chat(chunk.chat_id) if chunk else None
            first = (
                self.container.repo.find_message(hit.message_ids[0]) if hit.message_ids else None
            )
            if first is not None:
                snippet = (
                    first.content or (first.attachment_ref or {}).get("name", "") or "（无文本）"
                )[:80]
            else:
                snippet = ""
            anchor_by_chunk[hit.chunk_id] = (
                chunk.chat_id if chunk else "",
                chat.chat_name if chat else "",
                snippet,
            )
        self.results_view.show_hits(hits, elapsed_ms, anchor_by_chunk)
        self.timeline_view.show_nodes(self._build_timeline(hits))

        # 回答阶段
        if not hits:
            answer = self.container.generate(
                self.container.prepare_send(self.container.next_request_id(), self._last_query, []),
                self._last_query,
                [],
                elapsed_ms,
            )
            self._render_answer(answer)
            return
        if self.container.answer_service.has_llm():
            self._consent_flow()
        else:
            plan = self.container.prepare_send(
                self.container.next_request_id(), self._last_query, hits
            )
            self._run_generate(plan)

    def _consent_flow(self) -> None:
        request_id = self.container.next_request_id()
        plan = self.container.prepare_send(request_id, self._last_query, self._last_hits)
        messages = self.container.preview_messages(self._last_hits)
        dialog = ConsentDialog(
            plan,
            messages,
            self.container.update_selection,
            lambda: self.container.consent.revoke(),
            self,
        )
        dialog.exec()
        if not dialog.approved:
            self.answer_view.show_notice("已拒绝发送：未生成回答（默认拒绝外发，可随时重新查询）。")
            self.status_bar.set_phase("发送被拒绝")
            return
        self.container.consent.grant(
            dialog.final_plan.request_id,
            dialog.final_plan.payload_hash,
            dialog.final_plan.consent_scope,
        )
        self._run_generate(dialog.final_plan)

    def _run_generate(self, plan) -> None:
        self.status_bar.set_phase("回答生成中…")
        self.answer_view.show_notice("正在生成回答…（未配置 Key 时为本地片段模式）")

        def generate_fn(progress, cancel):
            return self.container.generate(
                plan,
                self._last_query,
                self._last_hits,
                self._last_elapsed_ms,
                on_token=self._worker.token.emit if self._worker else None,
                cancel=cancel,
            )

        self._worker = Worker("answer", generate_fn, self)
        self._worker.token.connect(lambda _token: None)
        self._worker.progress.connect(self.status_bar.on_task_event)
        self._worker.result.connect(self._render_answer)
        self._worker.failed.connect(self._on_task_failed)
        self._worker.start()

    def _render_answer(self, answer: Answer) -> None:
        self._last_answer = answer
        self.search_panel.set_busy(False)
        self.answer_view.show_answer(self._last_query, answer)
        self.status_bar.set_phase(f"回答完成：{answer.status} · {answer.mode}")
        self.status_bar.set_error(None)
        if answer.timeline_message_ids:
            self.timeline_view.show_nodes(self._build_timeline(None, answer.timeline_message_ids))

    def _on_task_failed(self, error) -> None:
        self.search_panel.set_busy(False)
        message = error.user_message if hasattr(error, "user_message") else str(error)
        if getattr(error, "code", "") == "CONSENT_REQUIRED":
            self.answer_view.show_notice(f"未发送：{message}")
        else:
            self.answer_view.show_notice(f"操作失败：{message}")
        self.status_bar.set_error(error)
        self.status_bar.set_phase("失败")

    # ------------------------------------------------------------------ 定位

    def locate_message(self, chat_id: str, message_id: str) -> None:
        try:
            window = self.container.repo.get_context(chat_id, message_id)
        except Exception as exc:  # noqa: BLE001
            self.status_bar.set_error(str(exc))
            return
        self.context_view.show_window(window)
        self.stack.setCurrentIndex(1)

    def _build_timeline(
        self, hits: list[SearchHit] | None, extra_ids: tuple[str, ...] = ()
    ) -> list[TimelineNode]:
        ids: list[str] = []
        for hit in hits or []:
            ids.extend(hit.message_ids)
        ids.extend(extra_ids)
        nodes = []
        for mid in dict.fromkeys(ids):
            msg = self.container.repo.find_message(mid)
            if msg is None:
                continue
            chat = self.container.repo.get_chat(msg.chat_id)
            snippet = msg.content or (msg.attachment_ref or {}).get("name", "") or "（无文本）"
            nodes.append(
                TimelineNode(
                    message_id=mid,
                    chat_id=msg.chat_id,
                    chat_name=chat.chat_name if chat else msg.chat_id,
                    sender_name=msg.sender_name,
                    timestamp=msg.timestamp,
                    snippet=snippet,
                    unknown_time=msg.timestamp is None,
                )
            )
        known = sorted((n for n in nodes if not n.unknown_time), key=lambda n: n.timestamp)
        unknown = [n for n in nodes if n.unknown_time]
        return known + unknown

    # ------------------------------------------------------------------ 菜单动作

    def open_import(self) -> None:
        dialog = ImportDialog(self.container, self)
        dialog.exec()
        self.refresh_all()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.container, self)
        dialog.exec()
        self.refresh_all()

    def export_answer(self) -> None:
        if self._last_answer is None:
            self.status_bar.set_error("还没有可导出的答案")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出答案",
            "answer_export.md",
            "Markdown (*.md);;JSON (*.json)",
        )
        if not path:
            return
        try:
            saved = self.container.lifecycle.export(Path(path), self._last_query, self._last_answer)
            self.status_bar.set_phase(f"已导出：{saved}")
        except Exception as exc:  # noqa: BLE001
            self.status_bar.set_error(f"导出失败：{exc}")

    def _delete_data(self) -> None:
        self.open_settings()

    def _cancel_current(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.status_bar.set_phase("正在取消…")

    def _show_demo_guide(self) -> None:
        QMessageBox.information(
            self,
            "演示指引",
            "1) 从「演示查询」选择一条 → 搜索 → 查看答案与引用。\n"
            "2) 点击引用卡片或时间线节点 → 应用内定位到原话及上下文。\n"
            "3) 「冰岛团建是哪天定的」演示无证据回答（不编造引用）。\n"
            "4) 断网、无 API Key 均可演示；数据为合成数据，界面有明确标注。",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            "原话考古 v0.1.0\n面向 Windows 的本地优先 QQ/微信聊天记录检索工具。\n"
            "本版本为 C 线桌面骨架（mock 服务），数据均为合成演示数据。",
        )
