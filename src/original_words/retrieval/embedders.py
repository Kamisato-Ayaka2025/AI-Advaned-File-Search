"""Embedder wrappers.

The project baseline is ``bge-small-zh-v1.5`` through FastEmbed/ONNX Runtime
(Plan.md section 2.1).  ``HashingEmbedder`` is dependency-free and exists only
for tests and for an explicit degraded/plumbing path; it is not a semantic
model and must never be presented as one.
"""

from __future__ import annotations

import math
import re
import zlib
from typing import Protocol, Sequence

from .text import is_cjk, normalize

_DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-zh-v1.5"
_LATIN = re.compile(r"[a-z0-9_]+")


class Embedder(Protocol):
    name: str
    dim: int

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Deterministic hashed character n-grams (test/plumbing only)."""

    name = "hash"

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        normalized = normalize(text)
        if not normalized:
            return vector

        def add(token: str) -> None:
            vector[zlib.crc32(token.encode("utf-8")) % self.dim] += 1.0

        chars = [ch for ch in normalized if is_cjk(ch)]
        for ch in chars:
            add(ch)
        for left, right in zip(chars, chars[1:]):
            add(left + right)
        for word in _LATIN.findall(normalized):
            add(word)
            if len(word) > 4:
                add(word[:4])

        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]


class FastEmbedEmbedder:
    """Baseline wrapper: FastEmbed + ONNX Runtime, CPU-friendly and offline.

    ``fastembed`` is an optional dependency owned by C's lock file.  Import is
    lazy so unit tests and environments without the wheel still work.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_FASTEMBED_MODEL,
        *,
        cache_dir: str | None = None,
        threads: int | None = None,
    ) -> None:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]

        kwargs: dict[str, object] = {"model_name": model_name}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        if threads:
            kwargs["threads"] = threads
        self.model = TextEmbedding(**kwargs)
        self.name = f"fastembed:{model_name}"
        self.dim = 0

    def _encode(self, texts: Sequence[str], query: bool) -> list[list[float]]:
        if not texts:
            return []
        iterator = self.model.query_embed(texts) if query else self.model.embed(texts)
        vectors = [[float(value) for value in vector] for vector in iterator]
        if vectors and not self.dim:
            self.dim = len(vectors[0])
        return vectors

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, query=False)

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, query=True)


class SentenceTransformerEmbedder:
    """Optional experiment wrapper; not the project baseline.

    Useful for comparing bge-small with Qwen3-Embedding, but it pulls torch and
    changes the packaging/RSS story.  Any adoption needs an A/product decision.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_FASTEMBED_MODEL,
        *,
        device: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        self.model = SentenceTransformer(model_name, device=device)
        self.name = f"st:{model_name}"
        try:
            self.dim = int(self.model.get_embedding_dimension())
        except AttributeError:
            self.dim = int(self.model.get_sentence_embedding_dimension())
        self._query_prompt = "query" if "query" in (getattr(self.model, "prompts", {}) or {}) else None
        self._query_prefix = ""
        lowered = model_name.lower()
        if "bge" in lowered and "m3" not in lowered and not self._query_prompt:
            self._query_prefix = "为这个句子生成表示以用于检索相关文章："

    def _encode(
        self,
        texts: Sequence[str],
        *,
        query: bool,
    ) -> list[list[float]]:
        if not texts:
            return []
        kwargs: dict[str, object] = {
            "batch_size": 32,
            "normalize_embeddings": True,
            "show_progress_bar": False,
        }
        items = list(texts)
        if query and self._query_prompt:
            kwargs["prompt_name"] = self._query_prompt
        elif query and self._query_prefix:
            items = [self._query_prefix + text for text in items]
        vectors = self.model.encode(items, **kwargs)
        return [[float(value) for value in vector] for vector in vectors]

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, query=False)

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts, query=True)


def make_embedder(spec: str | None, *, device: str | None = None) -> Embedder | None:
    """Build an embedder from a short spec.

    ``none`` / empty -> None (explicit lexical-only degradation)
    ``hash``        -> dependency-free test embedder
    ``fastembed``   -> baseline bge-small-zh-v1.5
    ``fastembed:<model>``
    ``st`` / ``st:<model>`` -> optional experiment
    """
    if not spec or spec in {"none", "off"}:
        return None
    spec = spec.strip()
    if spec == "hash":
        return HashingEmbedder()
    if spec == "fastembed":
        return FastEmbedEmbedder()
    if spec.startswith("fastembed:"):
        return FastEmbedEmbedder(spec.split(":", 1)[1])
    if spec in {"st", "bge"}:
        return SentenceTransformerEmbedder(device=device)
    if spec.startswith("st:"):
        return SentenceTransformerEmbedder(spec.split(":", 1)[1], device=device)
    raise ValueError(f"unknown embedder spec: {spec!r}")
