"""Provisional retrieval DTOs used by B-01/B-02 while contracts v1 is pending.

These mirror the fields frozen in ``Plan.md`` section 4.1.  They are deliberately
kept inside ``retrieval/`` and must be adapted to (or replaced by)
``contracts/search.py`` once A publishes it.  Do not import Qt, sqlite3 or the
network layer here: these objects are the boundary between retrieval and the
application service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """One normalized message, as read from A's fact store."""

    message_id: str
    chat_id: str
    sender_id: str
    sender_name: str
    timestamp: float | None
    text: str
    chat_type: str = "group"
    source: str = "qq"
    seq: int = 0
    attachments: tuple[str, ...] = ()
    quote_of: str | None = None
    message_type: str = "text"

    def __post_init__(self) -> None:
        if not self.message_id:
            raise ValueError("message_id must not be empty")
        if not self.chat_id:
            raise ValueError("chat_id must not be empty")
        if self.timestamp is not None and self.timestamp < 0:
            raise ValueError("timestamp must be a UTC epoch second or None")


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """A retrieval child: 4-8 messages, or a character slice of a long message."""

    chunk_id: str
    chat_id: str
    chat_title: str
    message_ids: tuple[str, ...]
    char_spans: tuple[tuple[int, int], ...]
    text: str
    embed_text: str
    ts_start: float | None
    ts_end: float | None
    seq_start: int
    seq_end: int
    sender_ids: tuple[str, ...] = ()
    sender_names: tuple[str, ...] = ()
    message_types: tuple[str, ...] = ()
    participants: tuple[str, ...] = ()
    parent_id: str = ""
    source: str = "qq"
    chat_type: str = "group"

    def __post_init__(self) -> None:
        if len(self.message_ids) != len(self.char_spans):
            raise ValueError("message_ids and char_spans must have the same length")
        if not self.message_ids:
            raise ValueError("a chunk must contain at least one message")


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Hard filters.  Unknown timestamps never match a bounded time range."""

    sources: tuple[str, ...] = ()
    chat_ids: tuple[str, ...] = ()
    chat_types: tuple[str, ...] = ()
    sender_ids: tuple[str, ...] = ()
    message_types: tuple[str, ...] = ()
    time_start: float | None = None
    time_end: float | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.sources,
                self.chat_ids,
                self.chat_types,
                self.sender_ids,
                self.message_types,
                self.time_start is not None,
                self.time_end is not None,
            )
        )


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    request_id: str = ""
    filters: SearchFilters = field(default_factory=SearchFilters)
    top_k: int = 10
    semantic_query: str | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    unit_id: str
    chat_id: str
    chat_title: str
    message_ids: tuple[str, ...]
    char_spans: tuple[tuple[int, int], ...]
    score: float
    reasons: tuple[str, ...]
    index_revision: str
    text: str = ""
    ts_start: float | None = None
    ts_end: float | None = None
    seq_start: int = 0
    seq_end: int = 0
    kind: str = "chunk"

    def to_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "chat_id": self.chat_id,
            "chat_title": self.chat_title,
            "message_ids": list(self.message_ids),
            "char_spans": [list(span) for span in self.char_spans],
            "score": round(self.score, 6),
            "reasons": list(self.reasons),
            "index_revision": self.index_revision,
            "ts_start": self.ts_start,
            "ts_end": self.ts_end,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class SearchResponse:
    hits: tuple[SearchHit, ...]
    index_revision: str
    degraded: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "hits": [hit.to_dict() for hit in self.hits],
            "index_revision": self.index_revision,
            "degraded": self.degraded,
            "timings_ms": {key: round(value, 3) for key, value in self.timings_ms.items()},
        }


class MessageRepository(Protocol):
    """Minimal read surface B needs from A's storage layer."""

    def get_message(self, message_id: str) -> MessageRecord | None: ...

    def get_messages(self, message_ids: Sequence[str]) -> list[MessageRecord]: ...

    def get_index_revision(self) -> str: ...
