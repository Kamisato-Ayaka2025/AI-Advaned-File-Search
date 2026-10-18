from __future__ import annotations

from datetime import datetime, timedelta, timezone

from original_words.retrieval.types import MessageRecord, SearchHit

TZ = timezone(timedelta(hours=8))


def ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=TZ).timestamp()


def message(
    *,
    message_id: str = "a1",
    chat_id: str = "chat-a",
    sender_id: str = "u1",
    sender_name: str = "张经理",
    timestamp: float | None = None,
    text: str = "新报价已经发给你了，之前那个版本别用了。",
    seq: int = 1,
) -> MessageRecord:
    return MessageRecord(
        message_id=message_id,
        chat_id=chat_id,
        sender_id=sender_id,
        sender_name=sender_name,
        timestamp=ts(2025, 10, 12, 15, 28) if timestamp is None else timestamp,
        text=text,
        seq=seq,
    )


class DictRepository:
    def __init__(self, messages, revision: str = "rev-test") -> None:
        self.messages = {item.message_id: item for item in messages}
        self.revision = revision

    def get_message(self, message_id: str) -> MessageRecord | None:
        return self.messages.get(message_id)

    def get_messages(self, message_ids):
        return [self.messages[item] for item in message_ids if item in self.messages]

    def get_index_revision(self) -> str:
        return self.revision


def make_hit(
    item: MessageRecord,
    *,
    score: float = 1.0,
    reasons: tuple[str, ...] = ("关键词命中",),
    index_revision: str = "rev-test",
) -> SearchHit:
    return SearchHit(
        unit_id=f"unit-{item.message_id}",
        chat_id=item.chat_id,
        chat_title=item.chat_id,
        message_ids=(item.message_id,),
        char_spans=((0, len(item.text)),),
        score=score,
        reasons=reasons,
        index_revision=index_revision,
        text=item.text,
        ts_start=item.timestamp,
        ts_end=item.timestamp,
        seq_start=item.seq,
        seq_end=item.seq,
    )
