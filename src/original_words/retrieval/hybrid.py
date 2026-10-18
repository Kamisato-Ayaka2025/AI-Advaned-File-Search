"""Hybrid retrieval: FTS5 + vector + exact entities, fused with RRF.

ADR-001: BM25 top-80 and vector top-80, exact entity/reference hits, candidate
pool <= 200, RRF = sum(1 / (60 + rank)).  Raw BM25 and cosine scores are never
added together; RRF is rank-based so the two channels do not need calibration.
"""

from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from typing import Iterable, Sequence

from .embedders import Embedder
from .index import RetrievalIndex
from .text import build_fts_query, extract_entities
from .types import SearchFilters, SearchHit, SearchRequest, SearchResponse


def rrf_fuse(
    rankings: dict[str, Sequence[str]],
    *,
    k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    weights = weights or {}
    scores: dict[str, float] = defaultdict(float)
    for channel, unit_ids in rankings.items():
        weight = weights.get(channel, 1.0)
        for rank, unit_id in enumerate(unit_ids):
            scores[unit_id] += weight / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


class HybridSearcher:
    def __init__(
        self,
        index: RetrievalIndex,
        embedder: Embedder | None = None,
        *,
        per_channel: int = 80,
        rrf_k: int = 60,
        pool_size: int = 200,
    ) -> None:
        self.index = index
        self.embedder = embedder if embedder is not None else index.embedder
        self.per_channel = per_channel
        self.rrf_k = rrf_k
        self.pool_size = max(pool_size, 1)

    def search(self, request: SearchRequest) -> SearchResponse:
        started = perf_counter()
        query = request.query.strip()
        if not query:
            return SearchResponse(
                hits=(),
                index_revision=self.index.revision,
                degraded=self._degraded(),
                timings_ms={"total": _elapsed_ms(started)},
            )

        semantic = (request.semantic_query or request.query).strip()
        filters = request.filters
        rankings: dict[str, list[str]] = {}
        timings: dict[str, float] = {}

        lexical_started = perf_counter()
        fts_ids = self.index.search_fts(
            build_fts_query(semantic, "and"),
            limit=self.per_channel,
            filters=filters,
        )
        if not fts_ids:
            # Precision first, then a bigram OR fallback for long natural queries.
            fts_ids = self.index.search_fts(
                build_fts_query(semantic, "or"),
                limit=self.per_channel,
                filters=filters,
            )
        if fts_ids:
            rankings["fts"] = fts_ids
        timings["fts"] = _elapsed_ms(lexical_started)

        exact_started = perf_counter()
        exact_ids = self.index.search_exact(
            extract_entities(request.query),
            limit=self.per_channel,
            filters=filters,
        )
        if exact_ids:
            rankings["exact"] = exact_ids
        timings["exact"] = _elapsed_ms(exact_started)

        vector_started = perf_counter()
        if self.embedder is not None and self.index.vector_count:
            allowed = self.index.filtered_unit_ids(filters)
            if allowed != set():  # empty set means the filter matches nothing
                query_vector = self.embedder.encode_queries([semantic])[0]
                vector_ids = [
                    unit_id
                    for unit_id, _score in self.index.vector_search(
                        query_vector,
                        limit=self.per_channel,
                        allowed=allowed,
                    )
                ]
                if vector_ids:
                    rankings["vector"] = vector_ids
        timings["vector"] = _elapsed_ms(vector_started)

        if not rankings:
            return SearchResponse(
                hits=(),
                index_revision=self.index.revision,
                degraded=self._degraded(),
                timings_ms={**timings, "total": _elapsed_ms(started)},
            )

        fused = rrf_fuse(
            rankings,
            k=self.rrf_k,
            weights={"fts": 1.0, "vector": 1.0, "exact": 1.15},
        )
        units = self.index.get_units(
            unit_id for unit_id, _score in fused[: self.pool_size]
        )
        in_fts = set(rankings.get("fts", ()))
        in_vector = set(rankings.get("vector", ()))
        in_exact = set(rankings.get("exact", ()))

        hits: list[SearchHit] = []
        kept_message_sets: list[set[str]] = []
        top_k = max(1, min(int(request.top_k), self.pool_size))
        for unit_id, score in fused[: self.pool_size]:
            unit = units.get(unit_id)
            if unit is None:
                continue
            message_ids = set(unit["message_ids"])
            if any(_overlap_ratio(message_ids, kept) > 0.5 for kept in kept_message_sets):
                continue
            reasons: list[str] = []
            if unit_id in in_fts:
                reasons.append("关键词命中")
            if unit_id in in_vector:
                reasons.append("语义命中")
            if unit_id in in_exact:
                reasons.append("精确实体命中")
            hits.append(
                SearchHit(
                    unit_id=unit_id,
                    chat_id=unit["chat_id"],
                    chat_title=unit["chat_title"],
                    message_ids=unit["message_ids"],
                    char_spans=unit["char_spans"],
                    score=float(score),
                    reasons=tuple(reasons),
                    index_revision=unit["index_revision"],
                    text=unit["text"],
                    ts_start=unit["ts_start"],
                    ts_end=unit["ts_end"],
                    seq_start=unit["seq_start"],
                    seq_end=unit["seq_end"],
                    kind=unit["kind"],
                )
            )
            kept_message_sets.append(message_ids)
            if len(hits) >= top_k:
                break

        return SearchResponse(
            hits=tuple(hits),
            index_revision=self.index.revision,
            degraded=self._degraded(),
            timings_ms={**timings, "total": _elapsed_ms(started)},
        )

    def _degraded(self) -> bool:
        return self.embedder is None or self.index.vector_count == 0


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0


def search_many(
    searcher: HybridSearcher,
    requests: Iterable[SearchRequest],
) -> list[SearchResponse]:
    return [searcher.search(request) for request in requests]
