"""Answer construction and citation validation.

Two modes share one contract: extractive (deterministic fallback, no network)
and LLM (B-02).  Every claim must point at a citation; a citation is accepted
only if the message exists in the same index revision, the character span is
valid and the quote matches the stored original.  Semantic support is a human
evaluation question; a valid citation is necessary, not sufficient.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..retrieval.text import datetime_label, normalize, parse_timestamp
from ..retrieval.types import MessageRepository, SearchHit, SearchResponse


@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    message_id: str
    char_start: int
    char_end: int
    quote: str
    chat_id: str
    sender: str
    timestamp: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "citation_id": self.citation_id,
            "message_id": self.message_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "quote": self.quote,
            "chat_id": self.chat_id,
            "sender": self.sender,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class Claim:
    text: str
    citation_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"text": self.text, "citation_ids": list(self.citation_ids)}


@dataclass(frozen=True, slots=True)
class Answer:
    status: str
    claims: tuple[Claim, ...] = ()
    citations: tuple[Citation, ...] = ()
    timeline: tuple[Citation, ...] = ()
    mode: str = "extractive"
    coverage: str = "current_index"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "claims": [claim.to_dict() for claim in self.claims],
            "citations": [citation.to_dict() for citation in self.citations],
            "timeline": [citation.to_dict() for citation in self.timeline],
            "mode": self.mode,
            "coverage": self.coverage,
        }


class CitationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CitationValidator:
    def validate(
        self,
        citation: Citation,
        repo: MessageRepository,
        index_revision: str,
    ) -> None:
        if repo.get_index_revision() != index_revision:
            raise CitationError("STALE_REVISION", "citation belongs to an older index revision")
        message = repo.get_message(citation.message_id)
        if message is None:
            raise CitationError("UNKNOWN_MESSAGE", "citation message does not exist")
        if citation.chat_id and message.chat_id != citation.chat_id:
            raise CitationError("CHAT_MISMATCH", "citation chat does not match the message")
        if citation.sender and normalize(message.sender_name) != normalize(citation.sender):
            raise CitationError("SENDER_MISMATCH", "citation sender does not match the message")
        if citation.timestamp is not None and citation.timestamp != message.timestamp:
            raise CitationError("TIME_MISMATCH", "citation time does not match the message")
        if (
            citation.char_start < 0
            or citation.char_end <= citation.char_start
            or citation.char_end > len(message.text)
        ):
            raise CitationError("BAD_SPAN", "citation character span is out of range")
        quote = message.text[citation.char_start : citation.char_end]
        if normalize(quote) != normalize(citation.quote):
            raise CitationError("QUOTE_MISMATCH", "citation quote does not match the stored original")

    def validate_all(
        self,
        citations: Iterable[Citation],
        repo: MessageRepository,
        index_revision: str,
    ) -> list[CitationError]:
        errors: list[CitationError] = []
        for citation in citations:
            try:
                self.validate(citation, repo, index_revision)
            except CitationError as error:
                errors.append(error)
        return errors

    def validate_answer(
        self,
        answer: Answer,
        repo: MessageRepository,
        index_revision: str,
    ) -> list[CitationError]:
        errors: list[CitationError] = []
        citations = {citation.citation_id: citation for citation in answer.citations}
        if len(citations) != len(answer.citations):
            errors.append(CitationError("DUPLICATE_CITATION", "citation ids must be unique"))
        errors.extend(self.validate_all(answer.citations, repo, index_revision))
        for claim in answer.claims:
            if not claim.citation_ids:
                errors.append(CitationError("UNCITED_CLAIM", "each claim needs at least one citation"))
            for citation_id in claim.citation_ids:
                if citation_id not in citations:
                    errors.append(
                        CitationError("UNKNOWN_CITATION", f"claim references unknown citation {citation_id}")
                    )
        if answer.status == "answered" and not answer.claims:
            errors.append(CitationError("EMPTY_ANSWER", "answered status requires at least one claim"))
        return errors


class ExtractiveAnswerBuilder:
    """No-network fallback: show what the index actually contains."""

    def __init__(self, repo: MessageRepository, *, max_claims: int = 5, max_citations_per_claim: int = 3) -> None:
        self.repo = repo
        self.max_claims = max_claims
        self.max_citations_per_claim = max_citations_per_claim
        self.validator = CitationValidator()

    def build(
        self,
        query: str,
        hits: Sequence[SearchHit] | SearchResponse,
        *,
        index_revision: str | None = None,
        coverage: str = "current_index",
    ) -> Answer:
        if isinstance(hits, SearchResponse):
            hits = hits.hits
        revision = index_revision or self.repo.get_index_revision()
        if not hits:
            return Answer(status="not_found", mode="extractive", coverage=coverage)

        claims: list[Claim] = []
        citations: list[Citation] = []
        for hit in list(hits)[: self.max_claims]:
            messages = {
                message.message_id: message
                for message in self.repo.get_messages(hit.message_ids)
            }
            hit_citations: list[Citation] = []
            for message_id, span in zip(hit.message_ids, hit.char_spans):
                message = messages.get(message_id)
                if message is None:
                    continue
                start, end = _clamp_span(span, len(message.text))
                if end <= start:
                    continue
                quote = message.text[start:end]
                if not quote.strip():
                    continue
                citation = Citation(
                    citation_id=f"c{len(citations) + len(hit_citations) + 1}",
                    message_id=message.message_id,
                    char_start=start,
                    char_end=end,
                    quote=quote,
                    chat_id=message.chat_id,
                    sender=message.sender_name,
                    timestamp=message.timestamp,
                )
                try:
                    self.validator.validate(citation, self.repo, revision)
                except CitationError:
                    continue
                hit_citations.append(citation)
                if len(hit_citations) >= self.max_citations_per_claim:
                    break
            if not hit_citations:
                continue
            citations.extend(hit_citations)
            first = hit_citations[0]
            sender = messages[first.message_id].sender_name if first.message_id in messages else first.sender
            claim_text = (
                f"{sender} 在 {datetime_label(first.timestamp)} 说：{first.quote[:160]}"
            )
            claims.append(
                Claim(
                    text=claim_text,
                    citation_ids=tuple(citation.citation_id for citation in hit_citations),
                )
            )

        if not claims:
            return Answer(status="not_found", mode="extractive", coverage=coverage)
        timeline = tuple(
            sorted(
                citations,
                key=lambda citation: (
                    citation.timestamp is None,
                    citation.timestamp if citation.timestamp is not None else 0.0,
                    citation.citation_id,
                ),
            )
        )
        return Answer(
            status="answered",
            claims=tuple(claims),
            citations=tuple(citations),
            timeline=timeline,
            mode="extractive",
            coverage=coverage,
        )


def _clamp_span(span: tuple[int, int], length: int) -> tuple[int, int]:
    start = max(0, min(int(span[0]), length))
    end = max(0, min(int(span[1]), length))
    if end <= start:
        return 0, length
    return start, end


def answer_to_dict(answer: Answer) -> dict[str, object]:
    return answer.to_dict()


def merge_timeline(citations: Iterable[Citation]) -> tuple[Citation, ...]:
    return tuple(
        sorted(
            citations,
            key=lambda citation: (
                citation.timestamp is None,
                citation.timestamp if citation.timestamp is not None else 0.0,
                citation.citation_id,
            ),
        )
    )


def timestamp_label(timestamp: float | None) -> str:
    if timestamp is None:
        return "未知时间"
    return dt.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def answer_from_json(
    data: dict,
    repo: MessageRepository,
    index_revision: str,
    *,
    coverage: str = "current_index",
) -> Answer:
    """Convert a validated LLM answer JSON into the internal Answer contract.

    The JSON shape is checked by ``deepseek.validate_answer_json`` before this
    call; this function additionally verifies every quote against the stored
    original and rejects the whole answer if one citation is invalid.
    """
    if data.get("status") not in {"answered", "partial", "not_found", "ambiguous"}:
        raise CitationError("INVALID_STATUS", "unknown answer status")
    citations: list[Citation] = []
    for raw in data.get("citations") or ():
        citations.append(
            Citation(
                citation_id=str(raw.get("citation_id") or raw.get("message_id")),
                message_id=str(raw["message_id"]),
                char_start=int(raw["char_start"]),
                char_end=int(raw["char_end"]),
                quote=str(raw["quote"]),
                chat_id=str(raw.get("chat_id") or ""),
                sender=str(raw.get("sender") or ""),
                timestamp=parse_timestamp(raw.get("timestamp")),
            )
        )
    claims = tuple(
        Claim(
            text=str(raw["text"]),
            citation_ids=tuple(str(value) for value in raw.get("citation_ids") or ()),
        )
        for raw in data.get("claims") or ()
    )
    answer = Answer(
        status=str(data["status"]),
        claims=claims,
        citations=tuple(citations),
        timeline=merge_timeline(citations),
        mode="llm",
        coverage=coverage,
    )
    errors = CitationValidator().validate_answer(answer, repo, index_revision)
    if errors:
        raise errors[0]
    return answer
