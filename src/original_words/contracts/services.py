"""Synchronous worker-thread protocols; implementations must not run on Qt UI thread.

Methods return DTOs or raise ServiceFailure with sanitized ErrorInfo. No implicit
network calls: only AnswerService.generate may send after atomic consent consume.
Runtime Protocol checks verify method presence, not behavioral or type correctness.
"""
from dataclasses import dataclass
from typing import Iterable, Literal, Protocol, runtime_checkable

from .answers import Answer
from .base import Contract, natural, nonempty, require, unique
from .common import ErrorInfo, SnapshotRef
from .data import Chunk, ImportBatch, ImportManifest, ImportReport, ImportResult
from .messages import Message
from .search import EvidenceBundle, SearchRequest, SearchResult, SearchSpec
from .sending import ConsentGrant, SendPlan


@dataclass(frozen=True, slots=True, repr=False)
class SourceDescriptor(Contract):
    source_id: str
    display_name: str
    tier: Literal["A", "B"]
    available: bool
    error: ErrorInfo | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.source_id, self.display_name)
        require(not self.available or self.error is None, "available source cannot carry an error")


@dataclass(frozen=True, slots=True, repr=False)
class SourceAuthorization(Contract):
    source_id: str
    authorization_id: str

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.source_id, self.authorization_id)


@dataclass(frozen=True, slots=True, repr=False)
class ProbeResult(Contract):
    supported: bool
    manifest: ImportManifest | None = None
    error: ErrorInfo | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        require(self.supported == (self.manifest is not None), "probe manifest mismatch")
        require(self.supported == (self.error is None), "unsupported probe needs error")


@dataclass(frozen=True, slots=True, repr=False)
class ContextResult(Contract):
    snapshot: SnapshotRef
    anchor_id: str
    source_id: str
    chat_id: str
    messages: tuple[Message, ...]
    truncated: bool = False

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.anchor_id, self.source_id, self.chat_id)
        unique(tuple(m.message_id for m in self.messages))
        require(self.anchor_id in {m.message_id for m in self.messages}, "context lacks anchor")
        require(all(m.source_id == self.source_id and m.chat_id == self.chat_id
                    for m in self.messages), "context crosses source or chat")


@dataclass(frozen=True, slots=True, repr=False)
class IndexRecord(Contract):
    chunk_id: str
    terms: str
    vector: tuple[float, ...]

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.chunk_id)
        require(bool(self.vector), "index vector is empty")


@dataclass(frozen=True, slots=True, repr=False)
class IndexUpdate(Contract):
    snapshot: SnapshotRef
    expected_active_revision: str | None
    model_version: str
    tokenizer_version: str
    chunker_version: str
    records: tuple[IndexRecord, ...]
    deleted_chunk_ids: tuple[str, ...] = ()

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.model_version, self.tokenizer_version, self.chunker_version)
        unique(tuple(r.chunk_id for r in self.records))
        unique(self.deleted_chunk_ids)
        require(not ({r.chunk_id for r in self.records} & set(self.deleted_chunk_ids)),
                "index update writes and deletes same chunk")
        require(len({len(r.vector) for r in self.records}) <= 1, "mixed vector dimensions")


@dataclass(frozen=True, slots=True, repr=False)
class CleanupItem(Contract):
    resource: Literal["database", "index", "attachments", "cache", "logs", "keys", "pending_sends"]
    status: Literal["deleted", "absent", "failed"]
    error: ErrorInfo | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        require((self.status == "failed") == (self.error is not None),
                "failed cleanup item requires error")


@dataclass(frozen=True, slots=True, repr=False)
class CleanupReport(Contract):
    task_id: str
    items: tuple[CleanupItem, ...]

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.task_id)
        unique(tuple(i.resource for i in self.items))
        require({i.resource for i in self.items} == {
            "database", "index", "attachments", "cache", "logs", "keys", "pending_sends"
        }, "cleanup report must cover every resource")

    @property
    def succeeded(self) -> bool:
        return all(i.status != "failed" for i in self.items)


@dataclass(frozen=True, slots=True, repr=False)
class ExportReceipt(Contract):
    destination: str
    format: Literal["markdown", "json"]
    bytes_written: int

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.destination)
        natural(self.bytes_written)


@runtime_checkable
class ChatSourceConnector(Protocol):
    def detect(self) -> tuple[SourceDescriptor, ...]: ...
    def authorize(self, source_id: str, *, user_confirmed: bool) -> SourceAuthorization: ...
    def read(self, authorization: SourceAuthorization) -> Iterable[ImportBatch]: ...
    def sync(self, authorization: SourceAuthorization, cursor: str | None) -> Iterable[ImportBatch]:
        """Tier A raises UNSUPPORTED_OPERATION; never silently performs full import."""
        ...


@runtime_checkable
class ExportAdapter(Protocol):
    def probe(self, path: str) -> ProbeResult: ...
    def read(self, path: str, manifest: ImportManifest) -> Iterable[ImportBatch]: ...
    def validate(self, path: str, manifest: ImportManifest) -> ImportReport:
        """Read-only; verify snapshot digest before and after parsing."""
        ...


@runtime_checkable
class Repository(Protocol):
    def import_batch(self, batch: ImportBatch) -> ImportResult:
        """Single writer; deterministic dedup and facts/revision commit together."""
        ...
    def get_messages(self, message_ids: tuple[str, ...], *, snapshot: SnapshotRef,
                     source_ids: tuple[str, ...]) -> tuple[Message, ...]: ...
    def get_context(self, message_id: str, *, snapshot: SnapshotRef,
                    source_ids: tuple[str, ...], before: int = 10,
                    after: int = 10) -> ContextResult: ...
    def get_chunks(self, chunk_ids: tuple[str, ...], *, snapshot: SnapshotRef,
                   source_ids: tuple[str, ...]) -> tuple[Chunk, ...]: ...


@runtime_checkable
class IndexStore(Protocol):
    def publish(self, update: IndexUpdate) -> SnapshotRef:
        """Compare expected active revision then atomically publish FTS and vectors."""
        ...
    def get_active_revision(self) -> SnapshotRef | None: ...


@runtime_checkable
class SearchService(Protocol):
    def parse_local(self, request: SearchRequest, *, snapshot: SnapshotRef,
                    authorized_source_ids: tuple[str, ...]) -> SearchSpec:
        """Never sends the query to a model."""
        ...
    def search(self, spec: SearchSpec) -> SearchResult: ...


@runtime_checkable
class AnswerService(Protocol):
    def prepare_send(self, spec: SearchSpec, evidence: EvidenceBundle, *,
                     purpose: Literal["query_parse", "investigation", "answer"],
                     mode: Literal["full", "partial", "summary", "keywords"],
                     model: str, endpoint: str) -> SendPlan:
        """Pure local preview; payload must contain only selected authorized evidence."""
        ...
    def generate(self, plan: SendPlan, grant: ConsentGrant, *,
                 consent: "ConsentService", evidence: EvidenceBundle) -> Answer:
        """Atomically consume consent immediately before sending exact preview bytes.

        Validate/hydrate citations from the pinned repository snapshot. No automatic
        retry of requests with uncertain send status. New payload requires new consent.
        """
        ...


@runtime_checkable
class ConsentService(Protocol):
    def grant(self, plan: SendPlan, *, user_confirmed: bool) -> ConsentGrant: ...
    def revoke(self, grant_id: str) -> None: ...
    def validate(self, grant: ConsentGrant, plan: SendPlan) -> bool:
        """Read-only check; insufficient by itself to authorize a send."""
        ...
    def consume(self, grant: ConsentGrant, plan: SendPlan) -> None:
        """Atomic one-shot check/consume of stored grant, expiry and revocation.

        Must recheck scope and fingerprint; failure raises CONSENT_REQUIRED.
        Grant DTO possession is not proof of a valid stored authorization.
        """
        ...


@runtime_checkable
class SecretStore(Protocol):
    def get(self, name: str) -> bytes | None: ...
    def set(self, name: str, value: bytes) -> None: ...
    def delete(self, name: str) -> None: ...


@runtime_checkable
class DataLifecycle(Protocol):
    def export(self, answer: Answer, *, snapshot: SnapshotRef, destination: str,
               format: Literal["markdown", "json"]) -> ExportReceipt: ...
    def delete(self, *, task_id: str, user_confirmed: bool) -> CleanupReport:
        """Maintenance lock, cancel/wait, invalidate sends, then clean every resource."""
        ...
