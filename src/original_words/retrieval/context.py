"""Context and explicit-reply expansion.

Neighbouring messages are for understanding only: they do not turn a window into
one confirmed event.  Reply/quote edges are explicit provenance and are followed
separately, up to a bounded number of hops.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .index import RetrievalIndex
from .types import MessageRecord, SearchHit


class ContextExpander:
    def __init__(self, index: RetrievalIndex) -> None:
        self.index = index

    def context(self, hit: SearchHit, *, before: int = 10, after: int = 10) -> list[MessageRecord]:
        return self.index.get_context(
            hit.chat_id,
            hit.seq_start,
            hit.seq_end,
            before=before,
            after=after,
        )

    def expand_replies(
        self,
        messages: Sequence[MessageRecord],
        *,
        max_hops: int = 2,
        max_messages: int = 120,
    ) -> list[MessageRecord]:
        if max_hops < 0:
            raise ValueError("max_hops must be non-negative")
        if max_messages <= 0:
            return []
        result: list[MessageRecord] = list(messages[:max_messages])
        seen = {message.message_id for message in result}
        frontier = [message.quote_of for message in result if message.quote_of]

        for _ in range(max_hops):
            next_frontier: list[str | None] = []
            for message_id in frontier:
                if not message_id or message_id in seen or len(result) >= max_messages:
                    continue
                quoted = self.index.get_message(message_id)
                if quoted is None:
                    # An unresolved quote is explicit, not silently dropped.
                    continue
                result.append(quoted)
                seen.add(quoted.message_id)
                next_frontier.append(quoted.quote_of)
            frontier = next_frontier
            if not frontier:
                break

        result.sort(
            key=lambda message: (
                message.timestamp is None,
                message.timestamp if message.timestamp is not None else 0.0,
                message.seq,
                message.message_id,
            )
        )
        return result

    def expand_messages(
        self,
        message_ids: Iterable[str],
        *,
        max_hops: int = 2,
        max_messages: int = 120,
    ) -> list[MessageRecord]:
        seeds = self.index.get_messages(message_ids)
        return self.expand_replies(seeds, max_hops=max_hops, max_messages=max_messages)
