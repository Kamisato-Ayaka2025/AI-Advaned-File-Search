"""Cross-object checks against repository facts, before UI or remote use.

The repository must supply these messages from the pinned dataset revision.
This validates identity, scope and character bounds, not semantic claim support.
"""
from .answers import Answer
from .base import require
from .common import ErrorInfo, ServiceFailure
from .data import Chunk
from .messages import Message
from .search import EvidenceBundle, SearchResult, SearchSpec


def _facts(messages: tuple[Message, ...], allowed: tuple[str, ...]) -> dict[str, Message]:
    require(bool(allowed), "authorized sources are required")
    result = {m.message_id: m for m in messages}
    require(len(result) == len(messages), "duplicate repository message")
    require(all(m.source_id in allowed for m in messages), "repository message outside scope")
    return result


def validate_chunk(chunk: Chunk, messages: tuple[Message, ...]) -> None:
    facts = _facts(messages, (chunk.source_id,))
    require(set(facts) == set(chunk.message_ids), "chunk membership differs from facts")
    require(all(m.chat_id == chunk.chat_id for m in messages), "chunk crosses chat")
    for span in chunk.char_spans:
        require(span.end <= len(facts[span.message_id].content), "chunk span exceeds original text")


def validate_evidence(bundle: EvidenceBundle, messages: tuple[Message, ...],
                      authorized_source_ids: tuple[str, ...]) -> None:
    facts = _facts(messages, authorized_source_ids)
    require(set(facts) == set(bundle.message_ids), "evidence membership differs from facts")
    require(set(bundle.coverage.source_ids) <= set(authorized_source_ids),
            "coverage exceeds authorized sources")
    for span in bundle.char_spans:
        require(span.end <= len(facts[span.message_id].content), "evidence span exceeds original text")


def validate_answer(answer: Answer, bundle: EvidenceBundle, messages: tuple[Message, ...],
                    authorized_source_ids: tuple[str, ...]) -> None:
    validate_evidence(bundle, messages, authorized_source_ids)
    facts = {m.message_id: m for m in messages}
    for citation in answer.citations:
        require(citation.snapshot == bundle.snapshot, "citation snapshot differs from evidence")
        require(citation.message_id in facts, "citation message outside evidence")
        span = citation.char_span
        permitted = [s for s in bundle.char_spans if s.message_id == citation.message_id]
        if span is not None:
            require(span.end <= len(facts[citation.message_id].content),
                    "citation span exceeds original text")
            if permitted:
                cursor = span.start
                for boundary in sorted(permitted, key=lambda s: s.start):
                    if boundary.start <= cursor:
                        cursor = max(cursor, boundary.end)
                require(cursor >= span.end, "citation exceeds selected evidence spans")
        else:
            require(not permitted, "partial evidence requires an explicit citation span")


def require_all_messages(requested_ids: tuple[str, ...], messages: tuple[Message, ...]) -> None:
    """Postcondition for batch reads; no message identifiers in the error."""
    if tuple(m.message_id for m in messages) != requested_ids:
        raise ServiceFailure(ErrorInfo("REVISION_MISMATCH", "消息集合与请求不一致，请重新查询"))


def validate_generated_answer(answer: Answer, request_id: str, bundle: EvidenceBundle,
                              messages: tuple[Message, ...],
                              authorized_source_ids: tuple[str, ...]) -> None:
    if answer.request_id != request_id:
        raise ServiceFailure(ErrorInfo("REVISION_MISMATCH", "回答所属请求已变化"))
    validate_answer(answer, bundle, messages, authorized_source_ids)


def validate_search_result(spec: SearchSpec, result: SearchResult) -> None:
    """The service must disclose imprecise-time exclusion even when counts are unknown."""
    if result.request_id != spec.request.request_id or result.snapshot != spec.snapshot:
        raise ServiceFailure(ErrorInfo("REVISION_MISMATCH", "搜索结果所属请求或版本已变化"))
    bounded = spec.hard_filters.start is not None or spec.hard_filters.end is not None
    require(result.time_filter.applied == bounded, "result is missing time-filter disclosure")
    require(set(result.coverage.source_ids) <= set(spec.authorized_source_ids),
            "result coverage exceeds authorized scope")
