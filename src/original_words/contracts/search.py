"""Search DTOs for Plan section 4 and ADR-001; budgets are limits, not SLAs."""
from dataclasses import dataclass, field
from typing import Literal

from .base import Contract, natural, nonempty, require, time_range, unique
from .common import SnapshotRef
from .data import CharSpan, Coverage

Stage = Literal["problem", "attempt", "solution", "verification"]


@dataclass(frozen=True, slots=True, repr=False)
class SearchFilters(Contract):
    source_ids: tuple[str, ...] = ()
    chat_ids: tuple[str, ...] = ()
    sender_ids: tuple[str, ...] = ()
    start: str | None = None
    end: str | None = None
    message_types: tuple[Literal["text", "image", "file", "system", "recalled", "unknown"], ...] = ()

    def __post_init__(self):
        Contract.__post_init__(self)
        for values in (self.source_ids, self.chat_ids, self.sender_ids, self.message_types):
            unique(values)
        time_range(self.start, self.end)


@dataclass(frozen=True, slots=True, repr=False)
class SearchRequest(Contract):
    request_id: str
    query: str
    filters: SearchFilters = field(default_factory=SearchFilters)
    top_k: int = 10
    history_ref: str | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.request_id, self.query)
        require(1 <= self.top_k <= 200, "invalid first-screen result limit")


@dataclass(frozen=True, slots=True, repr=False)
class SearchBudget(Contract):
    max_rounds: int = 2
    queries_per_round: int = 3
    remote_calls: int = 3
    cumulative_input_tokens: int = 24000
    first_decision_input_tokens: int = 4000
    second_decision_input_tokens: int = 6000
    decision_output_tokens: int = 512
    answer_input_tokens: int = 12000
    answer_output_tokens: int = 1500
    machine_seconds: float = 30.0
    answer_reserve_seconds: float = 12.0
    candidate_pool: int = 200
    fused_candidates: int = 80
    seeds: int = 12
    expansion_messages: int = 120
    relation_hops: int = 2

    def __post_init__(self):
        Contract.__post_init__(self)
        caps = dict(max_rounds=2, queries_per_round=3, remote_calls=3,
                    cumulative_input_tokens=24000, first_decision_input_tokens=4000,
                    second_decision_input_tokens=6000, decision_output_tokens=512,
                    answer_input_tokens=12000, answer_output_tokens=1500,
                    candidate_pool=200, fused_candidates=80, seeds=12,
                    expansion_messages=120, relation_hops=2)
        for name, cap in caps.items():
            require(0 <= getattr(self, name) <= cap, "budget exceeds standard-mode cap")
        require(0 < self.machine_seconds <= 30, "invalid machine deadline")
        require(0 <= self.answer_reserve_seconds <= self.machine_seconds,
                "invalid answer time reserve")
        require(self.seeds <= self.fused_candidates <= self.candidate_pool,
                "candidate budget ordering is invalid")


@dataclass(frozen=True, slots=True, repr=False)
class SearchSpec(Contract):
    request: SearchRequest
    snapshot: SnapshotRef
    authorized_source_ids: tuple[str, ...]
    intent: Literal["exact", "question", "process"] = "question"
    soft_hints: tuple[str, ...] = ()
    budget: SearchBudget = field(default_factory=SearchBudget)

    def __post_init__(self):
        Contract.__post_init__(self)
        require(bool(self.authorized_source_ids), "authorized search scope is required")
        unique(self.authorized_source_ids)
        require(set(self.request.filters.source_ids) <= set(self.authorized_source_ids),
                "hard filter exceeds authorized scope")

    @property
    def hard_filters(self) -> SearchFilters:
        return self.request.filters


@dataclass(frozen=True, slots=True, repr=False)
class SearchHit(Contract):
    chunk_id: str
    message_ids: tuple[str, ...]
    score: float
    reasons: tuple[str, ...]
    index_revision: str

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.chunk_id, self.index_revision)
        require(bool(self.message_ids), "search hit requires messages")
        unique(self.message_ids)


@dataclass(frozen=True, slots=True, repr=False)
class Candidate(Contract):
    hit: SearchHit
    source_id: str
    chat_id: str
    char_spans: tuple[CharSpan, ...] = ()

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.source_id, self.chat_id)
        require(all(s.message_id in self.hit.message_ids for s in self.char_spans),
                "candidate span outside hit")


@dataclass(frozen=True, slots=True, repr=False)
class SearchResult(Contract):
    request_id: str
    snapshot: SnapshotRef
    hits: tuple[SearchHit, ...]
    coverage: Coverage = field(default_factory=Coverage)
    truncated: bool = False

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.request_id)
        unique(tuple(h.chunk_id for h in self.hits))
        require(all(h.index_revision == self.snapshot.index_revision for h in self.hits),
                "search result mixes index revisions")


@dataclass(frozen=True, slots=True, repr=False)
class MessageEdge(Contract):
    from_id: str
    to_id: str | None
    type: Literal["reply", "quote"]
    provenance: str
    revision: str
    unresolved: bool = False

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.from_id, self.provenance, self.revision)
        require(self.unresolved == (self.to_id is None), "unresolved edge requires null target")
        if self.to_id is not None:
            nonempty(self.to_id)


@dataclass(frozen=True, slots=True, repr=False)
class StageCandidate(Contract):
    stage: Stage
    message_ids: tuple[str, ...]

    def __post_init__(self):
        Contract.__post_init__(self)
        require(bool(self.message_ids), "stage candidate requires evidence")
        unique(self.message_ids)


@dataclass(frozen=True, slots=True, repr=False)
class EvidenceBundle(Contract):
    snapshot: SnapshotRef
    message_ids: tuple[str, ...] = ()
    char_spans: tuple[CharSpan, ...] = ()
    stage_candidates: tuple[StageCandidate, ...] = ()
    edge_provenance: tuple[MessageEdge, ...] = ()
    missing_stages: tuple[Stage, ...] = ()
    coverage: Coverage = field(default_factory=Coverage)
    truncated: bool = False

    def __post_init__(self):
        Contract.__post_init__(self)
        unique(self.message_ids)
        unique(self.missing_stages)
        require(all(s.message_id in self.message_ids for s in self.char_spans),
                "evidence span outside bundle")
        for stage in self.stage_candidates:
            require(set(stage.message_ids) <= set(self.message_ids), "stage evidence outside bundle")
        for edge in self.edge_provenance:
            require(edge.revision == self.snapshot.dataset_revision, "edge revision mismatch")
            require(edge.from_id in self.message_ids, "edge origin outside bundle")
            require(edge.to_id is None or edge.to_id in self.message_ids,
                    "resolved edge target outside bundle")


@dataclass(frozen=True, slots=True, repr=False)
class InvestigationDecision(Contract):
    action: Literal["search", "finalize", "clarify"]
    evidence_ids: tuple[str, ...] = ()
    missing_stages: tuple[Stage, ...] = ()
    queries: tuple[str, ...] = ()
    expand_message_ids: tuple[str, ...] = ()
    clarification: str | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        for values in (self.evidence_ids, self.missing_stages, self.queries, self.expand_message_ids):
            unique(values)
        require(len(self.queries) <= 3 and len(self.expand_message_ids) <= 120,
                "decision exceeds batch limits")
        if self.action == "search":
            require(bool(self.queries or self.expand_message_ids), "search action needs work")
        else:
            require(not self.queries and not self.expand_message_ids, "non-search action has work")
        require((self.action == "clarify") == (self.clarification is not None),
                "clarify action requires a clarification")
        if self.clarification is not None:
            nonempty(self.clarification)

    def validate_against(self, bundle: EvidenceBundle, budget: SearchBudget) -> None:
        require(set(self.evidence_ids + self.expand_message_ids) <= set(bundle.message_ids),
                "decision references unknown evidence")
        require(len(self.queries) <= budget.queries_per_round
                and len(self.expand_message_ids) <= budget.expansion_messages,
                "decision exceeds configured budget")
