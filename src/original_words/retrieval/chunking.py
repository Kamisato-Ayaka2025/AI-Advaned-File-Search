"""Parent/child window construction (ADR-001 section 2).

Parent: 30 messages with 5 overlap, used for context and display.
Child: 4-8 messages with 1-2 overlap, used for retrieval; long messages are
split by character span so a hit can still cite the original message range.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Iterable, Sequence

from .text import date_label, is_cjk, token_count
from .types import ChunkRecord, MessageRecord

PARENT_SIZE = 30
PARENT_OVERLAP = 5
CHILD_SIZE = 6
CHILD_OVERLAP = 1
MAX_CHILD_TOKENS = 384


def stable_id(*parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:24]


def split_text_by_tokens(text: str, max_tokens: int) -> list[tuple[int, int]]:
    """Split text into character spans of at most ``max_tokens`` approximate tokens."""
    if not text:
        return [(0, 0)]
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if token_count(text) <= max_tokens:
        return [(0, len(text))]

    spans: list[tuple[int, int]] = []
    start = 0
    count = 0
    in_word = False
    for index, char in enumerate(text):
        increment = 0
        if is_cjk(char):
            increment = 1
            in_word = False
        elif char.isalnum() or char == "_":
            if not in_word:
                increment = 1
            in_word = True
        else:
            in_word = False

        if increment and count + increment > max_tokens and index > start:
            spans.append((start, index))
            start = index
            count = 0
            # Re-evaluate this character as the first character of the new span.
            count = 1 if is_cjk(char) or char.isalnum() or char == "_" else 0
        else:
            count += increment

    if start < len(text):
        spans.append((start, len(text)))
    return spans or [(0, len(text))]


def _message_order(message: MessageRecord) -> tuple[bool, float, int, str]:
    # Known timestamps first; unknown timestamps keep source order (seq), as
    # required by Plan section 4.1.  Never fabricate a time from a neighbour.
    return (
        message.timestamp is None,
        message.timestamp if message.timestamp is not None else 0.0,
        message.seq,
        message.message_id,
    )


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(OrderedDict.fromkeys(value for value in values if value))


def _chunk_id(chat_id: str, parent_id: str, message_ids: Sequence[str], spans: Sequence[tuple[int, int]]) -> str:
    return stable_id("chunk", chat_id, parent_id, *message_ids, *[f"{start}:{end}" for start, end in spans])


def _make_chunk(
    messages: Sequence[MessageRecord],
    spans: Sequence[tuple[int, int]],
    *,
    chat_id: str,
    chat_title: str,
    parent_id: str,
) -> ChunkRecord:
    if len(messages) != len(spans):
        raise ValueError("messages and spans must have the same length")
    text = "\n".join(
        message.text[start:end] for message, (start, end) in zip(messages, spans)
    )
    sender_ids = _unique(message.sender_id for message in messages)
    sender_names = _unique(message.sender_name for message in messages)
    message_types = _unique(message.message_type for message in messages)
    known_times = [message.timestamp for message in messages if message.timestamp is not None]
    labels = _unique(date_label(value) for value in known_times)
    body = "\n".join(
        f"{message.sender_name}: {message.text[start:end]}"
        for message, (start, end) in zip(messages, spans)
    )
    embed_text = " | ".join(
        [
            f"会话:{chat_title}",
            f"参与者:{','.join(sender_names)}",
            f"日期:{','.join(labels) if labels else '未知时间'}",
            body,
        ]
    )[:2000]
    return ChunkRecord(
        chunk_id=_chunk_id(chat_id, parent_id, [message.message_id for message in messages], spans),
        chat_id=chat_id,
        chat_title=chat_title,
        message_ids=tuple(message.message_id for message in messages),
        char_spans=tuple((int(start), int(end)) for start, end in spans),
        text=text,
        embed_text=embed_text,
        ts_start=min(known_times) if known_times else None,
        ts_end=max(known_times) if known_times else None,
        seq_start=min(message.seq for message in messages),
        seq_end=max(message.seq for message in messages),
        sender_ids=sender_ids,
        sender_names=sender_names,
        message_types=message_types,
        participants=sender_names,
        parent_id=parent_id,
        source=messages[0].source,
        chat_type=messages[0].chat_type,
    )


def _window_chunks(
    window: Sequence[MessageRecord],
    *,
    chat_id: str,
    chat_title: str,
    parent_id: str,
    max_tokens: int,
) -> list[ChunkRecord]:
    total = sum(token_count(message.text) for message in window)
    if len(window) == 1 or total <= max_tokens:
        if len(window) == 1 and total > max_tokens:
            return _split_message(window[0], chat_id=chat_id, chat_title=chat_title, parent_id=parent_id, max_tokens=max_tokens)
        return [
            _make_chunk(
                window,
                [(0, len(message.text)) for message in window],
                chat_id=chat_id,
                chat_title=chat_title,
                parent_id=parent_id,
            )
        ]

    # A multi-message window that is too long is split per message rather than
    # silently truncated.  The window remains represented by smaller children.
    chunks: list[ChunkRecord] = []
    for message in window:
        chunks.extend(
            _split_message(
                message,
                chat_id=chat_id,
                chat_title=chat_title,
                parent_id=parent_id,
                max_tokens=max_tokens,
            )
        )
    return chunks


def _split_message(
    message: MessageRecord,
    *,
    chat_id: str,
    chat_title: str,
    parent_id: str,
    max_tokens: int,
) -> list[ChunkRecord]:
    spans = split_text_by_tokens(message.text, max_tokens)
    return [
        _make_chunk(
            [message],
            [span],
            chat_id=chat_id,
            chat_title=chat_title,
            parent_id=parent_id,
        )
        for span in spans
    ]


def build_chunks(
    messages: Sequence[MessageRecord],
    *,
    chat_titles: dict[str, str] | None = None,
    parent_size: int = PARENT_SIZE,
    parent_overlap: int = PARENT_OVERLAP,
    child_size: int = CHILD_SIZE,
    child_overlap: int = CHILD_OVERLAP,
    max_tokens: int = MAX_CHILD_TOKENS,
) -> list[ChunkRecord]:
    """Build retrieval children for a batch of normalized messages.

    Chunks never cross a chat boundary.  Parent windows are only a grouping
    device; they do not imply that all messages in a window describe one event.
    """
    if parent_size <= 0 or child_size <= 0:
        raise ValueError("window sizes must be positive")
    if parent_overlap >= parent_size or child_overlap >= child_size:
        raise ValueError("overlap must be smaller than window size")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    titles = chat_titles or {}
    groups: dict[str, list[MessageRecord]] = {}
    for message in messages:
        groups.setdefault(message.chat_id, []).append(message)

    parent_step = max(1, parent_size - parent_overlap)
    child_step = max(1, child_size - child_overlap)
    chunks: list[ChunkRecord] = []
    seen: set[tuple[str, tuple[str, ...], tuple[tuple[int, int], ...]]] = set()

    for chat_id, group in groups.items():
        ordered = sorted(group, key=_message_order)
        chat_title = titles.get(chat_id, chat_id)
        for parent_start in range(0, len(ordered), parent_step):
            parent = ordered[parent_start : parent_start + parent_size]
            if not parent:
                continue
            parent_id = stable_id(
                "parent",
                chat_id,
                parent[0].message_id,
                parent[-1].message_id,
                len(parent),
            )
            for local_start in range(0, len(parent), child_step):
                window = parent[local_start : local_start + child_size]
                if not window:
                    continue
                for chunk in _window_chunks(
                    window,
                    chat_id=chat_id,
                    chat_title=chat_title,
                    parent_id=parent_id,
                    max_tokens=max_tokens,
                ):
                    key = (chunk.chat_id, chunk.message_ids, chunk.char_spans)
                    if key in seen:
                        continue
                    seen.add(key)
                    chunks.append(chunk)

    chunks.sort(key=lambda chunk: (chunk.chat_id, chunk.seq_start, chunk.seq_end, chunk.chunk_id))
    return chunks
