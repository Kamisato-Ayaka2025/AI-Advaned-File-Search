"""应用服务容器（C 线所有）：组装 mock 服务供 UI 调用。

UI 只与本层交互（Plan §2：UI 不直接执行 SQL 或调用 DeepSeek）。
A/B 真实服务合入后，仅在此切换实现；对外方法签名保持不变。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from original_words.application import demo_data, mocks
from original_words.application.dtos import (
    Answer,
    Chat,
    ChatFilters,
    DatasetInfo,
    ImportReport,
    Message,
    ParsedQuery,
    SearchHit,
    SearchRequest,
    SendPlan,
)


class ServiceContainer:
    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime.now().replace(microsecond=0)
        self.repo = mocks.DemoRepository()
        self.index = mocks.MockIndexStore(self.repo)
        self.search_service = mocks.MockSearchService(self.repo, self.index, self.now)
        self.secrets = mocks.MockSecretStore()
        self.consent = mocks.MockConsentService()
        self.answer_service = mocks.MockAnswerService(
            self.repo, self.index, self.consent, self.secrets
        )
        self.lifecycle = mocks.MockDataLifecycle(self.repo)
        self.adapter = mocks.MockExportAdapter()
        self.demo_queries = demo_data.DEMO_QUERIES
        self.dataset: DatasetInfo | None = None
        self._request_seq = 0

    # ---- 数据装载 ----

    def load_demo(self) -> DatasetInfo:
        bundle = demo_data.build_dataset(self.now)
        self.repo.load_demo(bundle)
        self.index.rebuild()
        stats = self.repo.stats()
        self.dataset = DatasetInfo(
            kind="demo",
            label="演示数据（合成）",
            chat_count=stats["chat_count"],
            message_count=stats["message_count"],
        )
        return self.dataset

    def import_file(
        self,
        path: str | Path,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        on_progress=None,
        cancel=None,
    ) -> ImportReport:
        messages, report = self.adapter.read(Path(path), start_time, end_time, on_progress, cancel)
        for msg in messages:
            if self.repo.get_chat(msg.chat_id) is None:
                self.repo.add_chat(
                    Chat(
                        chat_id=msg.chat_id,
                        chat_name=msg.chat_id,
                        chat_type=msg.chat_type,
                        source_id="import",
                        participants=(msg.sender_name,),
                    )
                )
        imported, duplicate = self.repo.import_batch(messages)
        report = replace(
            report,
            imported_count=imported,
            duplicate_count=duplicate,
            rejected_count=report.rejected_count,
        )
        self.index.rebuild()
        stats = self.repo.stats()
        self.dataset = DatasetInfo(
            kind="imported",
            label=f"已导入：{Path(path).name}",
            chat_count=stats["chat_count"],
            message_count=stats["message_count"],
            reports=[*self.dataset.reports, report] if self.dataset else [report],
        )
        return report

    # ---- 查询与回答 ----

    def next_request_id(self) -> str:
        self._request_seq += 1
        return f"req-{self._request_seq}"

    def parse(self, query: str) -> ParsedQuery:
        return self.search_service.parse_local(query)

    def search(
        self,
        query: str,
        filters: ChatFilters,
        top_k: int = 10,
        on_progress=None,
        cancel=None,
    ) -> tuple[list[SearchHit], float]:
        request = SearchRequest(
            request_id=self.next_request_id(),
            query=query,
            filters=filters,
            top_k=top_k,
        )
        return self.search_service.search(request, on_progress, cancel)

    def prepare_send(self, request_id: str, query: str, hits: list[SearchHit]) -> SendPlan:
        return self.answer_service.prepare_send(request_id, query, hits)

    def preview_messages(self, hits: list[SearchHit]) -> list[Message]:
        return self.answer_service.preview_messages(hits)

    def update_selection(
        self,
        plan: SendPlan,
        selected_ids: tuple[str, ...],
        mode: str,
        edited_preview: str | None = None,
    ) -> SendPlan:
        return self.answer_service.update_selection(plan, selected_ids, mode, edited_preview)

    def generate(
        self,
        plan: SendPlan,
        query: str,
        hits: list[SearchHit],
        elapsed_ms: int = 0,
        on_token=None,
        cancel=None,
    ) -> Answer:
        return self.answer_service.generate(
            plan, query, hits, elapsed_ms, on_token=on_token, cancel=cancel
        )

    # ---- 状态徽标 ----

    def mode_badges(self) -> list[str]:
        badges = [self.dataset.label if self.dataset else "尚未装载数据"]
        badges.append("离线（mock，无外发）")
        if self.secrets.is_key_configured():
            badges.append("API Key 已配置（llm_sim）")
        else:
            badges.append("未配置 API Key（本地片段模式）")
        if self.search_service.bm25_only:
            badges.append("BM25 降级（向量模型未接入）")
        return badges

    def stats_text(self) -> str:
        stats = self.repo.stats()
        start = stats["coverage_start"]
        end = stats["coverage_end"]
        span = (
            f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}"
            if start and end
            else "无有效时间"
        )
        return (
            f"{stats['chat_count']} 个会话 · {stats['message_count']} 条消息 · {span}"
            f" · 未知时间 {stats['unknown_time_count']} 条"
        )
