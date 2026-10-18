"""B-side adapter between internal retrieval units and contracts 0.2.0-draft.

The internal dataclasses in ``retrieval.types`` predate A's contracts.  This
module is the single translation seam: it converts internal messages/chunks/
hits to contract DTOs and implements A's ``SearchService`` protocol.  It is
intentionally not imported by ``retrieval/__init__.py`` so the B-01 tests can
still run on a branch without contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from ..contracts.common import SnapshotRef
from ..contracts.data import CharSpan, Chunk, Coverage
from ..contracts.messages import Message, TimeFilterInfo
from ..contracts.search import (
    Candidate,
    EvidenceBundle,
    SearchFilters as ContractFilters,
    SearchHit as ContractHit,
    SearchRequest as ContractRequest,
    SearchResult as ContractResult,
    SearchSpec,
)
from .hybrid import HybridSearcher
from .index import RetrievalIndex
from .text import parse_timestamp
from .types import ChunkRecord, MessageRecord, SearchFilters, SearchHit, SearchRequest, SearchResponse

_ALLOWED_CHAT_TYPES = {"group", "private", "unknown"}
_ALLOWED_MESSAGE_TYPES = {"text", "image", "file", "system", "recalled", "unknown"}


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _precision(timestamp: float | None) -> str:
    if timestamp is None:
        return "unknown"
    return "second" if float(timestamp).is_integer() else "millisecond"


def to_contract_message(record: MessageRecord) -> Message:
    precision = _precision(record.timestamp)
    chat_type = record.chat_type if record.chat_type in _ALLOWED_CHAT_TYPES else "unknown"
    message_type = record.message_type if record.message_type in _ALLOWED_MESSAGE_TYPES else "unknown"
    known = record.timestamp is not None
    return Message(
        message_id=record.message_id,
        source_id=record.source,
        chat_id=record.chat_id,
        chat_type=chat_type,
        sender_id=record.sender_id or None,
        sender_name=record.sender_name or None,
        timestamp=_iso(record.timestamp),
        message_type=message_type,
        content=record.text,
        seq=record.seq,
        timestamp_status="known" if known else "unknown",
        timestamp_precision=precision if known else "unknown",
        timestamp_source="retrieval-index" if known else None,
        source_timezone="UTC" if known else None,
        quote_of=record.quote_of,
        attachment_ref=record.attachments[0] if record.attachments else None,
    )


def to_contract_chunk(chunk: ChunkRecord, *, dataset_revision: str) -> Chunk:
    spans = tuple(
        CharSpan(message_id, start, end)
        for message_id, (start, end) in zip(chunk.message_ids, chunk.char_spans)
        if end > start
    )
    return Chunk(
        chunk_id=chunk.chunk_id,
        source_id=chunk.source,
        chat_id=chunk.chat_id,
        message_ids=chunk.message_ids,
        start=_iso(chunk.ts_start),
        end=_iso(chunk.ts_end),
        participants=chunk.participants,
        text=chunk.text,
        dataset_revision=dataset_revision,
        parent_id=chunk.parent_id or None,
        char_spans=spans,
    )


def to_contract_hit(hit: SearchHit) -> ContractHit:
    return ContractHit(
        chunk_id=hit.unit_id,
        message_ids=hit.message_ids,
        score=hit.score,
        reasons=hit.reasons,
        index_revision=hit.index_revision,
    )


def to_contract_candidate(hit: SearchHit, *, source_id: str, chat_id: str) -> Candidate:
    return Candidate(
        hit=to_contract_hit(hit),
        source_id=source_id,
        chat_id=chat_id,
        char_spans=tuple(
            CharSpan(message_id, start, end)
            for message_id, (start, end) in zip(hit.message_ids, hit.char_spans)
            if end > start
        ),
    )


def to_internal_filters(filters: ContractFilters) -> SearchFilters:
    return SearchFilters(
        sources=filters.source_ids,
        chat_ids=filters.chat_ids,
        sender_ids=filters.sender_ids,
        message_types=filters.message_types,
        time_start=parse_timestamp(filters.start),
        time_end=parse_timestamp(filters.end),
    )


def to_internal_request(request: ContractRequest) -> SearchRequest:
    return SearchRequest(
        query=request.query,
        request_id=request.request_id,
        filters=to_internal_filters(request.filters),
        top_k=request.top_k,
    )


def to_contract_result(
    response: SearchResponse,
    request: ContractRequest,
    snapshot: SnapshotRef,
    *,
    coverage: Coverage | None = None,
    time_filter: TimeFilterInfo | None = None,
) -> ContractResult:
    hits = tuple(to_contract_hit(hit) for hit in response.hits)
    bounded = request.filters.start is not None or request.filters.end is not None
    return ContractResult(
        request_id=request.request_id,
        snapshot=snapshot,
        hits=hits,
        coverage=coverage or Coverage(source_ids=request.filters.source_ids),
        truncated=False,
        time_filter=time_filter or TimeFilterInfo(applied=bounded),
    )


def to_contract_evidence(
    response: SearchResponse,
    snapshot: SnapshotRef,
    authorized_source_ids: Sequence[str],
) -> EvidenceBundle:
    message_ids: list[str] = []
    spans: list[CharSpan] = []
    for hit in response.hits:
        for message_id, (start, end) in zip(hit.message_ids, hit.char_spans):
            if message_id not in message_ids:
                message_ids.append(message_id)
            if end > start:
                spans.append(CharSpan(message_id, start, end))
    return EvidenceBundle(
        snapshot=snapshot,
        message_ids=tuple(message_ids),
        char_spans=tuple(spans),
        coverage=Coverage(source_ids=tuple(authorized_source_ids), completeness="unknown"),
        truncated=False,
    )


class ContractSearchService:
    """Implements A's ``SearchService`` on top of the B-01 hybrid searcher."""

    def __init__(self, index: RetrievalIndex, embedder=None, **kwargs) -> None:
        self.index = index
        self.searcher = HybridSearcher(index, embedder, **kwargs)

    def parse_local(
        self,
        request: ContractRequest,
        *,
        snapshot: SnapshotRef,
        authorized_source_ids: tuple[str, ...],
    ) -> SearchSpec:
        return SearchSpec(
            request=request,
            snapshot=snapshot,
            authorized_source_ids=tuple(authorized_source_ids),
        )

    def search(self, spec: SearchSpec) -> ContractResult:
        response = self.searcher.search(to_internal_request(spec.request))
        return to_contract_result(
            response,
            spec.request,
            spec.snapshot,
            coverage=Coverage(
                source_ids=spec.authorized_source_ids,
                completeness="unknown",
            ),
            time_filter=TimeFilterInfo(
                applied=spec.hard_filters.start is not None or spec.hard_filters.end is not None,
            ),
        )


__all__ = [
    "ContractSearchService",
    "to_contract_candidate",
    "to_contract_chunk",
    "to_contract_evidence",
    "to_contract_hit",
    "to_contract_message",
    "to_contract_result",
    "to_internal_filters",
    "to_internal_request",
]
