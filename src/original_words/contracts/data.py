"""Storage and import DTOs. Unknown counts stay null, never inferred as zero."""
from dataclasses import dataclass
from typing import Literal

from .base import Contract, natural, nonempty, require, time_range, unique, utc
from .messages import Message

Completeness = Literal["unknown", "partial", "verified_for_scope"]


@dataclass(frozen=True, slots=True, repr=False)
class CharSpan(Contract):
    message_id: str
    start: int
    end: int

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.message_id)
        natural(self.start)
        require(self.end > self.start, "character range must be nonempty and half-open")


@dataclass(frozen=True, slots=True, repr=False)
class Coverage(Contract):
    source_ids: tuple[str, ...] = ()
    start: str | None = None
    end: str | None = None
    completeness: Completeness = "unknown"

    def __post_init__(self):
        Contract.__post_init__(self)
        unique(self.source_ids)
        time_range(self.start, self.end)


@dataclass(frozen=True, slots=True, repr=False)
class Chunk(Contract):
    chunk_id: str
    source_id: str
    chat_id: str
    message_ids: tuple[str, ...]
    start: str | None
    end: str | None
    participants: tuple[str, ...]
    text: str
    dataset_revision: str
    parent_id: str | None = None
    char_spans: tuple[CharSpan, ...] = ()

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.chunk_id, self.source_id, self.chat_id, self.dataset_revision)
        require(bool(self.message_ids), "chunk requires messages")
        unique(self.message_ids)
        unique(self.participants)
        time_range(self.start, self.end)
        require(all(s.message_id in self.message_ids for s in self.char_spans),
                "span references message outside chunk")


@dataclass(frozen=True, slots=True, repr=False)
class ImportManifest(Contract):
    adapter_id: str
    adapter_version: str
    export_schema: str
    account_scope: tuple[str, ...]
    snapshot_hash: str
    upstream_tool: str | None = None
    upstream_version: str | None = None
    client_build: str | None = None
    exported_at: str | None = None
    coverage_start: str | None = None
    coverage_end: str | None = None
    source_count: int | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.adapter_id, self.adapter_version, self.export_schema, self.snapshot_hash)
        require(bool(self.account_scope), "import scope is required")
        unique(self.account_scope)
        time_range(self.coverage_start, self.coverage_end)
        if self.exported_at is not None:
            utc(self.exported_at)
        if self.source_count is not None:
            natural(self.source_count)


@dataclass(frozen=True, slots=True, repr=False)
class ImportReport(Contract):
    manifest: ImportManifest
    read_count: int | None
    imported_count: int | None
    duplicate_count: int | None
    rejected_count: int | None
    unknown_count: int | None
    attachment_missing_count: int | None
    completeness: Completeness = "unknown"

    def __post_init__(self):
        Contract.__post_init__(self)
        counts = (self.read_count, self.imported_count, self.duplicate_count,
                  self.rejected_count, self.unknown_count, self.attachment_missing_count)
        for count in counts:
            if count is not None:
                natural(count)
        primary = counts[:4]
        if all(c is not None for c in primary):
            require(self.read_count == self.imported_count + self.duplicate_count
                    + self.rejected_count, "import counts do not reconcile")
        if self.unknown_count is not None and self.imported_count is not None:
            require(self.unknown_count <= self.imported_count,
                    "unknown count must be a subset of accepted messages")
        if self.manifest.source_count is None:
            require(self.completeness == "unknown", "unknown source count requires unknown coverage")
        if self.completeness == "verified_for_scope":
            require(all(c is not None for c in counts), "verified coverage requires known counts")
            require(self.read_count == self.manifest.source_count and self.rejected_count == 0,
                    "verified coverage requires complete reconciliation")


@dataclass(frozen=True, slots=True, repr=False)
class ImportBatch(Contract):
    batch_id: str
    manifest: ImportManifest
    messages: tuple[Message, ...]

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.batch_id)
        unique(tuple(m.message_id for m in self.messages))
        require(all(m.source_id in self.manifest.account_scope for m in self.messages),
                "batch contains out-of-scope source")


@dataclass(frozen=True, slots=True, repr=False)
class ImportResult(Contract):
    report: ImportReport
    dataset_revision: str

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.dataset_revision)
