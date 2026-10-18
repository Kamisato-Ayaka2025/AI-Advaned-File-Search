"""In-memory exact vector index for B-01 (10k-message baseline).

ADR-001 keeps exact cosine as the baseline and only moves to ANN after an
independent scale test.  Vectors here are derived data: production persistence
must go through A's encrypted IndexStore, never a plaintext side file.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


class VectorStore:
    def __init__(
        self,
        ids: Sequence[str] = (),
        vectors: Sequence[Sequence[float]] | None = None,
    ) -> None:
        self._ids: list[str] = []
        self._matrix = np.zeros((0, 0), dtype=np.float32)
        if ids or vectors is not None:
            self.build(ids, vectors or [])

    def __len__(self) -> int:
        return len(self._ids)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._ids)

    @property
    def dim(self) -> int:
        return int(self._matrix.shape[1]) if self._matrix.size else 0

    def build(self, ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors must have the same length")
        if not ids:
            self._ids = []
            self._matrix = np.zeros((0, 0), dtype=np.float32)
            return
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2:
            raise ValueError("vectors must be a 2-D array")
        self._ids = [str(value) for value in ids]
        self._matrix = _l2_normalize(matrix)

    def add(self, ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        if not ids:
            return
        incoming = np.asarray(vectors, dtype=np.float32)
        if incoming.ndim != 2:
            raise ValueError("vectors must be a 2-D array")
        if self._matrix.size and incoming.shape[1] != self._matrix.shape[1]:
            raise ValueError(
                f"dimension mismatch: store={self._matrix.shape[1]} new={incoming.shape[1]}"
            )
        incoming = _l2_normalize(incoming)
        if not self._matrix.size:
            self._matrix = incoming
            self._ids = [str(value) for value in ids]
            return
        self._matrix = np.vstack([self._matrix, incoming])
        self._ids.extend(str(value) for value in ids)

    def search(
        self,
        query: Sequence[float],
        *,
        k: int = 80,
        allowed: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        if k <= 0 or not self._ids:
            return []
        if allowed is not None and not allowed:
            return []
        query_vector = np.asarray(query, dtype=np.float32)
        if query_vector.ndim != 1 or query_vector.shape[0] != self._matrix.shape[1]:
            raise ValueError(
                f"query dimension {query_vector.shape} does not match index dimension "
                f"{self._matrix.shape[1]}"
            )
        norm = float(np.linalg.norm(query_vector))
        if norm == 0.0:
            return []
        query_vector = query_vector / norm

        scores = self._matrix @ query_vector
        if allowed is not None:
            mask = np.fromiter((uid in allowed for uid in self._ids), dtype=bool, count=len(self._ids))
            if not mask.any():
                return []
            scores = np.where(mask, scores, -np.inf)

        finite = np.flatnonzero(np.isfinite(scores))
        if finite.size == 0:
            return []
        top_k = min(int(k), int(finite.size))
        if top_k < finite.size:
            selected = finite[np.argpartition(-scores[finite], top_k - 1)[:top_k]]
        else:
            selected = finite
        ordered = sorted(
            (int(index) for index in selected),
            key=lambda index: (-float(scores[index]), self._ids[index]),
        )
        return [(self._ids[index], float(scores[index])) for index in ordered]


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return (matrix / norms).astype(np.float32, copy=False)
