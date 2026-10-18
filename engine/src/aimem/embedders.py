from __future__ import annotations

import re
import zlib
from typing import Protocol

import numpy as np

from .text import normalize


class Embedder(Protocol):
    name: str
    dim: int
    query_prefix: str

    def encode_documents(self, texts: list[str], batch_size: int = 32) -> np.ndarray: ...

    def encode_queries(self, texts: list[str], batch_size: int = 32) -> np.ndarray: ...


class HashEmbedder:
    """Dependency-free embedder for plumbing tests and CPU fallback.

    It is a hashed character n-gram vectorizer: strings sharing substrings get
    similar vectors. Not semantic, but deterministic and useful for smoke tests.
    """

    name = "hash"
    query_prefix = ""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _one(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        s = normalize(text).replace(" ", "")
        for n in (2, 3):
            for i in range(len(s) - n + 1):
                v[zlib.crc32(s[i : i + n].encode("utf-8", "ignore")) % self.dim] += 1.0
        for w in re.findall(r"[a-z0-9]+", normalize(text)):
            v[zlib.crc32(w.encode("utf-8", "ignore")) % self.dim] += 1.0
        norm = float(np.linalg.norm(v))
        return v / norm if norm else v

    def encode_documents(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._one(t) for t in texts])

    def encode_queries(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        return self.encode_documents(texts, batch_size=batch_size)


class SentenceTransformerEmbedder:
    """Real semantic embedder (BGE / Qwen3-Embedding / Granite ...)."""

    query_prefix = ""

    def __init__(
        self,
        model: str,
        device: str | None = None,
        name: str | None = None,
        dtype: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.name = name or f"st:{model}"
        self.model_name = model
        kwargs = {"trust_remote_code": True}
        if device:
            kwargs["device"] = device
        if dtype:
            import torch

            kwargs["model_kwargs"] = {"torch_dtype": getattr(torch, dtype)}
        self.model = SentenceTransformer(model, **kwargs)
        try:
            self.dim = int(self.model.get_embedding_dimension())
        except AttributeError:  # sentence-transformers < 6
            self.dim = int(self.model.get_sentence_embedding_dimension())
        self.prompts = getattr(self.model, "prompts", {}) or {}
        self.query_prompt_name = "query" if "query" in self.prompts else None
        low = model.lower()
        # BGE v1.5 Chinese models expect this instruction on the query side only.
        if "bge" in low and "m3" not in low and not self.query_prompt_name:
            self.query_prefix = "为这个句子生成表示以用于检索相关文章："

    def _encode(
        self, texts: list[str], batch_size: int, prompt_name: str | None = None
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        kwargs = {"prompt_name": prompt_name} if prompt_name else {}
        vecs = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            **kwargs,
        )
        return np.asarray(vecs, dtype=np.float32)

    def encode_documents(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        return self._encode(texts, batch_size)

    def encode_queries(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        if self.query_prompt_name:
            return self._encode(texts, batch_size, prompt_name=self.query_prompt_name)
        if self.query_prefix:
            texts = [self.query_prefix + t for t in texts]
        return self._encode(texts, batch_size)


def make_embedder(
    spec: str | None, device: str | None = None, dtype: str | None = None
) -> Embedder | None:
    """spec: none | hash | st | st:<model> | qwen"""
    if not spec or spec in ("none", "off"):
        return None
    spec = spec.strip()
    if spec == "hash":
        return HashEmbedder()
    if spec in ("st", "bge"):
        return SentenceTransformerEmbedder("BAAI/bge-small-zh-v1.5", device=device, dtype=dtype)
    if spec == "qwen":
        return SentenceTransformerEmbedder("Qwen/Qwen3-Embedding-0.6B", device=device, dtype=dtype)
    if spec.startswith("st:"):
        return SentenceTransformerEmbedder(spec[3:], device=device, dtype=dtype)
    raise ValueError(f"unknown embedder spec: {spec!r}")
