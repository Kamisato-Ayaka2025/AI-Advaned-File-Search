from __future__ import annotations

from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))

CHAT_TITLES = {
    "chat-a": "设备采购群",
    "chat-b": "硬件讨论",
    "chat-c": "项目讨论",
}


def ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=TZ).timestamp()


class ConceptEmbedder:
    """Tiny deterministic stand-in for semantic recall in unit tests.

    It maps paraphrases ("发烫" / "过热" / "thermal") to the same axis, so the
    vector channel can be tested without downloading a model.
    """

    name = "concept"
    dim = 3

    def _one(self, text: str) -> list[float]:
        lowered = text.lower()
        vector = [0.0, 0.0, 0.0]
        if any(word in lowered for word in ("发烫", "过热", "显卡", "gpu", "thermal", "温度")):
            vector[0] += 1.0
        if any(word in lowered for word in ("报价", "版本", "采购", "供应商")):
            vector[1] += 1.0
        if any(word in lowered for word in ("退款", "退货", "refund")):
            vector[2] += 1.0
        norm = sum(value * value for value in vector) ** 0.5
        return [value / norm for value in vector] if norm else vector

    def encode_documents(self, texts):
        return [self._one(text) for text in texts]

    def encode_queries(self, texts):
        return [self._one(text) for text in texts]
