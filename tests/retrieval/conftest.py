from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from original_words.retrieval import (  # noqa: E402
    HybridSearcher,
    MessageRecord,
    RetrievalIndex,
)

from .support import CHAT_TITLES, ConceptEmbedder, ts  # noqa: E402,F401


@pytest.fixture
def messages() -> list[MessageRecord]:
    return [
        MessageRecord(
            "a1", "chat-a", "u1", "张经理", ts(2025, 10, 12, 15, 28),
            "新报价已经发给你了，之前那个版本别用了。", seq=1,
        ),
        MessageRecord(
            "a2", "chat-a", "u2", "我", ts(2025, 10, 12, 15, 31),
            "收到，设备采购方案我按最终版更新。", seq=2,
        ),
        MessageRecord(
            "a3", "chat-a", "u1", "张经理", ts(2025, 10, 12, 16, 2),
            "报价单_最终版.xlsx 已经放到共享盘。", seq=3,
        ),
        MessageRecord(
            "a4", "chat-a", "u3", "李四", ts(2025, 10, 14, 9, 5),
            "这个旧版本的报价不能再用了。", seq=4, quote_of="a1",
        ),
        MessageRecord(
            "b1", "chat-b", "u4", "王工", ts(2025, 10, 13, 11, 0),
            "GPU thermal throttling 是显卡过热导致的。", seq=1,
        ),
        MessageRecord(
            "b2", "chat-b", "u2", "我", ts(2025, 10, 13, 11, 3),
            "先换硅脂再测一次温度。", seq=2,
        ),
        MessageRecord(
            "c1", "chat-c", "u5", "赵六", None,
            "我们决定换供应商，旧合同月底到期。", seq=1,
        ),
    ]


@pytest.fixture
def index(tmp_path, messages):
    store = RetrievalIndex(tmp_path / "index.db", embedder=ConceptEmbedder(), revision="rev-test")
    store.build(messages, chat_titles=CHAT_TITLES)
    yield store
    store.close()


@pytest.fixture
def searcher(index):
    return HybridSearcher(index)
