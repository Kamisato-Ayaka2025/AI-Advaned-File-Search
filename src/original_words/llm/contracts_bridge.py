"""B-side conversions from internal LLM answers/plans to contracts 0.2.0-draft.

A's Citation deliberately carries no model-authored quote, sender or timestamp;
UI hydrates those from the pinned snapshot.  B keeps its rich internal citation
for extractive display, then drops the non-contract fields here.
"""

from __future__ import annotations

from ..contracts.answers import (
    Answer as ContractAnswer,
    Citation as ContractCitation,
    Claim as ContractClaim,
    TimelineEntry,
)
from ..contracts.common import SnapshotRef
from ..contracts.data import CharSpan
from ..contracts.sending import SendPlan as ContractSendPlan, evidence_digest
from .answer import Answer as InternalAnswer, Citation as InternalCitation
from .deepseek import SendPlan as InternalSendPlan

_ALLOWED_STATUS = {"answered", "partial", "not_found", "ambiguous"}
_ALLOWED_MODES = {"local", "deepseek", "demo"}
_ALLOWED_PURPOSES = {"query_parse", "investigation", "answer"}
_ALLOWED_SEND_MODES = {"full", "partial", "summary", "keywords"}


def to_contract_citation(citation: InternalCitation, snapshot: SnapshotRef) -> ContractCitation:
    span = None
    if citation.char_end > citation.char_start:
        span = CharSpan(citation.message_id, citation.char_start, citation.char_end)
    return ContractCitation(
        citation_id=citation.citation_id,
        message_id=citation.message_id,
        snapshot=snapshot,
        char_span=span,
    )


def to_contract_answer(
    answer: InternalAnswer,
    snapshot: SnapshotRef,
    *,
    request_id: str,
    clarification: str | None = None,
) -> ContractAnswer:
    if answer.status not in _ALLOWED_STATUS:
        raise ValueError(f"unsupported answer status: {answer.status}")
    citations = tuple(to_contract_citation(citation, snapshot) for citation in answer.citations)
    claims = tuple(
        ContractClaim(text=claim.text, citation_ids=claim.citation_ids)
        for claim in answer.claims
    )
    for claim in claims:
        if not claim.citation_ids:
            raise ValueError("contract claim requires citations")

    grouped: dict[str, list[str]] = {}
    for citation in answer.timeline or answer.citations:
        grouped.setdefault(citation.message_id, []).append(citation.citation_id)
    timeline = tuple(
        TimelineEntry(message_id=message_id, citation_ids=tuple(dict.fromkeys(ids)))
        for message_id, ids in grouped.items()
    )
    mode = "local" if answer.mode == "extractive" else "deepseek" if answer.mode == "llm" else answer.mode
    if mode not in _ALLOWED_MODES:
        mode = "local"
    return ContractAnswer(
        status=answer.status,
        claims=claims,
        citations=citations,
        timeline=timeline,
        mode=mode,
        request_id=request_id,
        clarification=clarification,
    )


def to_contract_send_plan(
    plan: InternalSendPlan,
    *,
    snapshot: SnapshotRef,
    evidence,
) -> ContractSendPlan:
    purpose = plan.purpose if plan.purpose in _ALLOWED_PURPOSES else "answer"
    mode = plan.mode if plan.mode in _ALLOWED_SEND_MODES else "full"
    scope = (plan.consent_scope,) if isinstance(plan.consent_scope, str) else tuple(plan.consent_scope)
    scope = tuple(dict.fromkeys((*scope, *evidence.coverage.source_ids)))
    if not scope:
        scope = ("deepseek",)
    return ContractSendPlan(
        request_id=plan.request_id,
        purpose=purpose,
        mode=mode,
        payload_hash=plan.payload_hash,
        selected_message_ids=plan.selected_message_ids,
        preview_text=plan.preview_text,
        model=plan.model,
        endpoint=plan.endpoint,
        consent_scope=scope,
        snapshot=snapshot,
        evidence_digest=evidence_digest(evidence),
    )


__all__ = ["to_contract_answer", "to_contract_citation", "to_contract_send_plan"]
