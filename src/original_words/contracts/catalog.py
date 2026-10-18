"""Catalog and bounded timeline pages for UI consumers."""
from dataclasses import dataclass, field
from typing import Literal

from .base import Contract, natural, nonempty, require, time_range, unique
from .common import SnapshotRef
from .data import Coverage
from .messages import Message, TimeFilterInfo


@dataclass(frozen=True, slots=True, repr=False)
class ChatSummary(Contract):
    source_id: str
    chat_id: str
    chat_type: Literal["group", "private", "unknown"]
    display_name: str | None
    participants: tuple[str, ...]
    message_count: int | None
    first_at: str | None
    last_at: str | None
    coverage: Coverage

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.source_id, self.chat_id)
        unique(self.participants)
        if self.message_count is not None:
            natural(self.message_count)
        time_range(self.first_at, self.last_at)
        require(set(self.coverage.source_ids) <= {self.source_id}, "chat coverage crosses source")


@dataclass(frozen=True, slots=True, repr=False)
class SourceSummary(Contract):
    source_id: str
    display_name: str | None
    chat_count: int | None
    message_count: int | None
    coverage: Coverage

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.source_id)
        for count in (self.chat_count, self.message_count):
            if count is not None:
                natural(count)
        require(set(self.coverage.source_ids) <= {self.source_id}, "source coverage crosses source")


@dataclass(frozen=True, slots=True, repr=False)
class ChatPage(Contract):
    snapshot: SnapshotRef
    chats: tuple[ChatSummary, ...]
    next_cursor: str | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        require(len(self.chats) <= 200, "chat page exceeds limit")
        require(len({(c.source_id, c.chat_id) for c in self.chats}) == len(self.chats),
                "duplicate chat in page")
        if self.next_cursor is not None:
            nonempty(self.next_cursor)
            require(bool(self.chats), "empty page cannot have continuation")


@dataclass(frozen=True, slots=True, repr=False)
class MessagePage(Contract):
    snapshot: SnapshotRef
    source_id: str
    chat_id: str
    messages: tuple[Message, ...]
    start: str | None = None
    end: str | None = None
    next_cursor: str | None = None
    time_filter: TimeFilterInfo = field(default_factory=TimeFilterInfo)

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.source_id, self.chat_id)
        time_range(self.start, self.end)
        require(len(self.messages) <= 200, "message page exceeds limit")
        unique(tuple(m.message_id for m in self.messages))
        require(all(m.source_id == self.source_id and m.chat_id == self.chat_id
                    for m in self.messages), "timeline crosses source or chat")
        require(self.time_filter.applied == (self.start is not None or self.end is not None),
                "time filter disclosure differs from query")
        require(all(m.matches_time_range(self.start, self.end) for m in self.messages),
                "timeline contains messages outside time filter")
        if self.next_cursor is not None:
            nonempty(self.next_cursor)
            require(bool(self.messages), "empty page cannot have continuation")
