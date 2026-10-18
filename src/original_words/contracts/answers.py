"""Citation references carry no model-authored sender, timestamp or quotation."""
from dataclasses import dataclass, field
from typing import Literal

from .base import Contract, natural, nonempty, require, unique
from .common import SnapshotRef
from .data import CharSpan
from .search import EvidenceBundle, SearchBudget

AnswerStatus = Literal["answered", "partial", "not_found", "ambiguous"]
AnswerMode = Literal["local", "deepseek", "demo"]


@dataclass(frozen=True, slots=True, repr=False)
class Citation(Contract):
    citation_id: str
    message_id: str
    snapshot: SnapshotRef
    char_span: CharSpan | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.citation_id, self.message_id)
        require(self.char_span is None or self.char_span.message_id == self.message_id,
                "citation span references another message")


@dataclass(frozen=True, slots=True, repr=False)
class Claim(Contract):
    text: str
    citation_ids: tuple[str, ...]

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.text)
        require(bool(self.citation_ids), "claim requires citations")
        unique(self.citation_ids)


@dataclass(frozen=True, slots=True, repr=False)
class TimelineEntry(Contract):
    message_id: str
    citation_ids: tuple[str, ...]

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.message_id)
        require(bool(self.citation_ids), "timeline entry requires citations")
        unique(self.citation_ids)


@dataclass(frozen=True, slots=True, repr=False)
class Answer(Contract):
    status: AnswerStatus
    claims: tuple[Claim, ...] = ()
    citations: tuple[Citation, ...] = ()
    timeline: tuple[TimelineEntry, ...] = ()
    mode: AnswerMode = "local"

    def __post_init__(self):
        Contract.__post_init__(self)
        ids = tuple(c.citation_id for c in self.citations)
        unique(ids)
        require(all(set(c.citation_ids) <= set(ids) for c in self.claims),
                "claim has dangling citation")
        require(len({c.snapshot for c in self.citations}) <= 1, "answer mixes snapshots")
        lookup = {c.citation_id: c.message_id for c in self.citations}
        for entry in self.timeline:
            require(all(lookup.get(cid) == entry.message_id for cid in entry.citation_ids),
                    "timeline citation does not match message")
        if self.status == "answered":
            require(bool(self.claims), "answered result requires supported claims")
        if self.status == "not_found":
            require(not self.claims and not self.citations and not self.timeline,
                    "not-found answer cannot invent evidence")


@dataclass(frozen=True, slots=True, repr=False)
class SearchUsage(Contract):
    machine_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    remote_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    rounds: int = 0

    def __post_init__(self):
        Contract.__post_init__(self)
        require(0 <= self.machine_seconds <= self.elapsed_seconds, "invalid elapsed time")
        for count in (self.remote_calls, self.input_tokens, self.output_tokens, self.rounds):
            natural(count)


@dataclass(frozen=True, slots=True, repr=False)
class SearchOutcome(Contract):
    request_id: str
    answer: Answer
    evidence: EvidenceBundle
    stop_reason: Literal["complete", "no_evidence", "no_new_evidence", "budget",
                         "deadline", "cancelled", "revoked", "ambiguous", "error"]
    usage: SearchUsage = field(default_factory=SearchUsage)
    budget_exhausted: bool = False

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.request_id)
        for citation in self.answer.citations:
            require(citation.snapshot == self.evidence.snapshot, "citation revision mismatch")
            require(citation.message_id in self.evidence.message_ids, "citation outside evidence")
        if self.stop_reason in {"budget", "deadline"}:
            require(self.budget_exhausted, "budget stop requires exhaustion flag")
        if self.stop_reason in {"budget", "deadline", "cancelled", "revoked", "error"}:
            require(self.answer.status == "partial", "incomplete execution must be partial")
        if self.stop_reason == "no_evidence":
            require(self.answer.status == "not_found" and not self.evidence.message_ids,
                    "no-evidence stop must not carry results")
        if self.answer.status == "answered":
            require(not self.budget_exhausted and not self.evidence.missing_stages
                    and not self.evidence.truncated, "incomplete evidence cannot claim answered")

    @property
    def status(self) -> AnswerStatus:
        return self.answer.status

    def validate_budget(self, budget: SearchBudget) -> None:
        require(self.usage.remote_calls <= budget.remote_calls
                and self.usage.rounds <= budget.max_rounds
                and self.usage.input_tokens <= budget.cumulative_input_tokens,
                "observed usage exceeds configured budget")
        require(self.usage.output_tokens <= budget.max_rounds * budget.decision_output_tokens
                + budget.answer_output_tokens, "observed output exceeds configured budget")
