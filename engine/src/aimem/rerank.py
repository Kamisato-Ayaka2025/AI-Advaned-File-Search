from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    name: str

    def score(
        self, query: str, passages: list[str], batch_size: int = 16
    ) -> list[float]: ...


class CrossEncoderReranker:
    """bge-reranker / Qwen3-Reranker style cross-encoder."""

    def __init__(
        self,
        model: str,
        device: str | None = None,
        dtype: str | None = None,
        max_length: int = 512,
    ) -> None:
        from sentence_transformers import CrossEncoder

        kwargs: dict = {"trust_remote_code": True, "max_length": max_length}
        if device:
            kwargs["device"] = device
        if dtype:
            import torch

            kwargs["model_kwargs"] = {"torch_dtype": getattr(torch, dtype)}
        self.model = CrossEncoder(model, **kwargs)
        self.name = f"ce:{model}"

    def score(
        self, query: str, passages: list[str], batch_size: int = 16
    ) -> list[float]:
        if not passages:
            return []
        pairs = [(query, p) for p in passages]
        out = self.model.predict(
            pairs, batch_size=batch_size, show_progress_bar=False
        )
        return [float(x) for x in out]


def make_reranker(
    spec: str | None, device: str | None = None, dtype: str | None = None
) -> Reranker | None:
    """spec: none | bge | ce:<model>"""
    if not spec or spec in ("none", "off"):
        return None
    spec = spec.strip()
    if spec in ("bge", "default"):
        return CrossEncoderReranker("BAAI/bge-reranker-v2-m3", device, dtype)
    if spec.startswith("ce:"):
        return CrossEncoderReranker(spec[3:], device, dtype)
    raise ValueError(f"unknown reranker spec: {spec!r}")
