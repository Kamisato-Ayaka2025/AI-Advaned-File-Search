from __future__ import annotations

import pytest

from original_words.contracts.common import SnapshotRef
from original_words.contracts.data import CharSpan
from original_words.contracts.messages import Message
from original_words.contracts.search import (
    EvidenceBundle,
    SearchBudget,
    SearchFilters as ContractFilters,
    SearchHit as ContractSearchHit,
    SearchRequest as ContractRequest,
    SearchSpec,
)
from original_words.contracts.services import SearchService
from original_words.contracts.validation import (
    validate_answer,
    validate_chunk,
    validate_evidence,
    validate_search_result,
)
from original_words.llm.answer import ExtractiveAnswerBuilder
from original_words.llm.contracts_bridge import to_contract_answer
from original_words.retrieval import ChunkRecord, HashingEmbedder, MessageRecord, RetrievalIndex
from original_words.retrieval.contracts_bridge import (
    ContractSearchService,
    to_contract_candidate,
    to_contract_chunk,
    to_contract_evidence,
    to_contract_message,
    to_contract_result,
    to_internal_request,
)

from .support import ts

SNAPSHOT = SnapshotRef("data-1", "idx-1")


def _messages() -> list[MessageRecord]:
    return [
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
        MessageRecord(
            "a4", "chat-a", "u3", "李四", ts(2025, 10, 14, 9, 5),
            "这个旧版本的报价不能再用了。", seq=4,
        ),
    ]


def _index(tmp_path):
    index = RetrievalIndex(tmp_path / "contracts.db", embedder=HashingEmbedder(), revision="idx-1")
    index.build(_messages(), chat_titles={"chat-a": "设备采购群"})
    return index


def test_search_service_consumes_contract_request_and_returns_valid_result(tmp_path):
    index = _index(tmp_path)
    try:
        service = ContractSearchService(index)
        assert isinstance(service, SearchService)
        request = ContractRequest("req-1", "旧版本", ContractFilters(source_ids=("qq",)))
        spec = service.parse_local(request, snapshot=SNAPSHOT, authorized_source_ids=("qq",))
        assert spec.hard_filters == request.filters
        result = service.search(spec)

        assert result.hits
        assert result.snapshot == SNAPSHOT
        assert result.time_filter.applied is False
        assert all(hit.index_revision == "idx-1" for hit in result.hits)
        assert "a1" in {message_id for hit in result.hits for message_id in hit.message_ids}
    finally:
        index.close()


def test_internal_hits_evidence_and_answer_validate_against_contract(tmp_path):
    index = _index(tmp_path)
    try:
        request = ContractRequest("req-2", "旧版本", ContractFilters(source_ids=("qq",)))
        internal = to_internal_request(request)
        response = ContractSearchService(index).searcher.search(internal)
        assert response.hits

        contract_messages = tuple(to_contract_message(message) for message in _messages())
        by_id = {message.message_id: message for message in contract_messages}

        first_hit = response.hits[0]
        unit = index.get_units([first_hit.unit_id])[first_hit.unit_id]
        chunk_record = ChunkRecord(
            chunk_id=unit["unit_id"],
            chat_id=unit["chat_id"],
            chat_title=unit["chat_title"],
            message_ids=unit["message_ids"],
            char_spans=unit["char_spans"],
            text=unit["text"],
            embed_text=unit["embed_text"],
            ts_start=unit["ts_start"],
            ts_end=unit["ts_end"],
            seq_start=unit["seq_start"],
            seq_end=unit["seq_end"],
            parent_id=unit["parent_id"],
            source=unit["source"],
            chat_type=unit["chat_type"],
        )
        chunk = to_contract_chunk(chunk_record, dataset_revision="data-1")
        validate_chunk(chunk, tuple(by_id[message_id] for message_id in chunk.message_ids))
        candidate = to_contract_candidate(first_hit, source_id="qq", chat_id=first_hit.chat_id)
        assert candidate.hit.chunk_id == first_hit.unit_id

        evidence = to_contract_evidence(response, SNAPSHOT, ("qq",))
        evidence_messages = tuple(by_id[message_id] for message_id in evidence.message_ids)
        validate_evidence(evidence, evidence_messages, ("qq",))

        internal_answer = ExtractiveAnswerBuilder(index).build("旧版本", response)
        assert internal_answer.status == "answered"
        answer = to_contract_answer(internal_answer, SNAPSHOT, request_id="req-2")
        validate_answer(answer, evidence, evidence_messages, ("qq",))
        assert answer.status == "answered"
        assert answer.mode == "local"
    finally:
        index.close()


def test_hard_filter_cannot_exceed_authorized_scope():
    request = ContractRequest("req-3", "报价", ContractFilters(source_ids=("wechat",)))
    with pytest.raises(ValueError):
        SearchSpec(request, SNAPSHOT, ("qq",))


def test_search_budget_cannot_exceed_standard_caps():
    with pytest.raises(ValueError):
        SearchBudget(max_rounds=3)
    with pytest.raises(ValueError):
        SearchBudget(candidate_pool=201)


def test_date_precision_is_conservatively_excluded_from_bounded_time_filter():
    message = Message(
        message_id="day-1",
        source_id="qq",
        chat_id="chat-a",
        chat_type="group",
        sender_id="u1",
        sender_name="张经理",
        timestamp="2026-10-18",
        message_type="text",
        content="日期级消息",
        seq=1,
        timestamp_status="known",
        timestamp_precision="day",
        timestamp_source="export",
        source_timezone="Asia/Shanghai",
    )
    assert message.matches_time_range(
        "2026-10-18T00:00:00Z",
        "2026-10-19T00:00:00Z",
    ) is False


def test_evidence_span_outside_message_is_rejected():
    evidence = EvidenceBundle(
        snapshot=SNAPSHOT,
        message_ids=("a1",),
        char_spans=(CharSpan("a1", 0, 999),),
    )
    message = to_contract_message(_messages()[0])
    with pytest.raises(ValueError):
        validate_evidence(evidence, (message,), ("qq",))


def test_gap_search_filters_have_no_chat_type():
    # C's B1/REQ-022: group/private filtering cannot be expressed today.
    assert "chat_types" not in ContractFilters.__dataclass_fields__
    assert "chat_type" not in ContractFilters.__dataclass_fields__


def test_gap_search_hit_has_no_text_or_chat_id():
    # C's S10 / B's hydration note: C must call Repository.get_chunks.
    fields = ContractSearchHit.__dataclass_fields__
    assert "text" not in fields
    assert "chat_id" not in fields


def test_bounded_search_discloses_time_filter(tmp_path):
    index = _index(tmp_path)
    try:
        request = ContractRequest(
            "req-time",
            "旧版本",
            ContractFilters(
                source_ids=("qq",),
                start="2025-10-01T00:00:00Z",
                end="2025-11-01T00:00:00Z",
            ),
        )
        service = ContractSearchService(index)
        spec = service.parse_local(request, snapshot=SNAPSHOT, authorized_source_ids=("qq",))
        result = service.search(spec)
        assert result.time_filter.applied is True
        validate_search_result(spec, result)
    finally:
        index.close()
