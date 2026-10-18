from __future__ import annotations

from datetime import datetime, timedelta, timezone

from original_words.llm.answer import CitationValidator, ExtractiveAnswerBuilder
from original_words.retrieval import (
    HashingEmbedder,
    HybridSearcher,
    MessageRecord,
    RetrievalIndex,
    SearchRequest,
)

TZ = timezone(timedelta(hours=8))
CHAT_TITLES = {"chat-a": "设备采购群"}


def ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=TZ).timestamp()


def _build_index(tmp_path):
    messages = [
        MessageRecord(
            "a1", "chat-a", "u1", "张经理", ts(2025, 10, 12, 15, 28),
            "新报价已经发给你了，之前那个版本别用了。", seq=1,
        ),
        MessageRecord(
            "a2", "chat-a", "u2", "我", ts(2025, 10, 12, 15, 31),
            "收到，设备采购方案我按最终版更新。", seq=2,
        ),
        MessageRecord(
            "a3", "chat-a", "u1", "张经理", ts(2025, 10, 12, 16, 2),
            "报价单_最终版.xlsx 已经放到共享盘。", seq=3,
        ),
    ]
    index = RetrievalIndex(
        tmp_path / "e2e.db",
        embedder=HashingEmbedder(),
        revision="rev-e2e",
    )
    index.build(messages, chat_titles=CHAT_TITLES)
    return index, messages


def test_search_to_extractive_answer_has_valid_citations(tmp_path):
    index, messages = _build_index(tmp_path)
    try:
        response = HybridSearcher(index).search(SearchRequest("旧版本报价", top_k=5))
        assert response.hits
        answer = ExtractiveAnswerBuilder(index).build("旧版本报价", response)
        assert answer.status == "answered"
        assert answer.claims
        assert answer.citations
        assert CitationValidator().validate_answer(answer, index, "rev-e2e") == []
        by_id = {message.message_id: message for message in messages}
        for citation in answer.citations:
            assert citation.message_id in by_id
            assert (
                citation.quote
                == by_id[citation.message_id].text[citation.char_start : citation.char_end]
            )
    finally:
        index.close()


def test_no_evidence_produces_not_found_not_hallucination(tmp_path):
    index, _ = _build_index(tmp_path)
    try:
        response = HybridSearcher(index).search(SearchRequest("zzz-not-present", top_k=5))
        answer = ExtractiveAnswerBuilder(index).build("zzz-not-present", response)
        assert answer.status == "not_found"
        assert answer.claims == ()
        assert answer.citations == ()
    finally:
        index.close()


def test_query_parser_to_hybrid_search_to_answer(tmp_path):
    from original_words.llm.query import RuleQueryParser

    index, _ = _build_index(tmp_path)
    try:
        parser = RuleQueryParser(
            participants=[("u1", "张经理")],
            chats=[("chat-a", "设备采购群")],
        )
        spec = parser.parse(
            "上周张经理在设备采购群说的报价",
            now=datetime(2025, 10, 15, 12, 0, tzinfo=TZ),
        )
        assert spec.filters.time_start is not None
        response = HybridSearcher(index).search(
            SearchRequest(spec.semantic, filters=spec.filters, top_k=5)
        )
        assert response.hits
        answer = ExtractiveAnswerBuilder(index).build(spec.semantic, response)
        assert answer.status == "answered"
        assert CitationValidator().validate_answer(answer, index, "rev-e2e") == []
    finally:
        index.close()
