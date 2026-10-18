from __future__ import annotations

from original_words.retrieval.chunking import build_chunks, split_text_by_tokens
from original_words.retrieval.types import MessageRecord


def _msg(index: int, *, chat_id: str = "chat-a", text: str | None = None) -> MessageRecord:
    return MessageRecord(
        message_id=f"m{index}",
        chat_id=chat_id,
        sender_id="u1" if index % 2 else "u2",
        sender_name="张经理" if index % 2 else "我",
        timestamp=1_760_000_000.0 + index * 60,
        text=text if text is not None else f"第{index}条消息",
        seq=index,
    )


def test_parent_child_windows_do_not_cross_chats():
    messages = [_msg(index) for index in range(40)]
    messages.append(_msg(0, chat_id="chat-b", text="另一个会话"))
    chunks = build_chunks(messages, chat_titles={"chat-a": "设备采购群", "chat-b": "硬件讨论"})

    assert chunks
    assert all(chunk.chat_id in {"chat-a", "chat-b"} for chunk in chunks)
    assert all(len(chunk.message_ids) <= 6 for chunk in chunks)
    assert len({chunk.parent_id for chunk in chunks if chunk.chat_id == "chat-a"}) >= 2


def test_child_windows_overlap_by_one_message():
    messages = [_msg(index) for index in range(12)]
    chunks = build_chunks(messages, parent_size=30, parent_overlap=5, child_size=6, child_overlap=1)
    chat_chunks = sorted(chunks, key=lambda chunk: chunk.seq_start)
    # The 12-message chat produces 0-5, 5-10 and 10-11.
    first, second = chat_chunks[0], chat_chunks[1]
    assert set(first.message_ids) & set(second.message_ids)


def test_long_message_is_split_by_character_span():
    text = "字" * 500
    spans = split_text_by_tokens(text, 100)
    assert len(spans) == 5
    assert "".join(text[start:end] for start, end in spans) == text

    message = _msg(1, text=text)
    chunks = build_chunks([message], max_tokens=100)
    assert len(chunks) == 5
    assert all(chunk.message_ids == ("m1",) for chunk in chunks)
    assert all(span[1] - span[0] <= 100 for chunk in chunks for span in chunk.char_spans)
    assert "".join(chunk.text for chunk in chunks) == text


def test_unknown_timestamp_is_preserved_as_none():
    message = MessageRecord(
        message_id="m1",
        chat_id="chat-a",
        sender_id="u1",
        sender_name="张经理",
        timestamp=None,
        text="没有时间的消息",
        seq=1,
    )
    chunk = build_chunks([message])[0]
    assert chunk.ts_start is None
    assert chunk.ts_end is None


def test_chunk_ids_are_deterministic():
    messages = [_msg(index) for index in range(8)]
    first = [chunk.chunk_id for chunk in build_chunks(messages)]
    second = [chunk.chunk_id for chunk in build_chunks(messages)]
    assert first == second
