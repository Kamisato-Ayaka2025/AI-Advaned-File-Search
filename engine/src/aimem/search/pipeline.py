from __future__ import annotations

import math
import re
import time
from collections import defaultdict

from .. import db, planner
from ..embedders import Embedder
from ..ingest.fs import unit_from_path
from ..models import QueryPlan, SearchResult, Unit, stable_id
from ..paths import path_depth
from ..text import normalize
from ..vectors import VectorStore


def rrf(
    rankings: dict[str, list[tuple[str, float]]],
    *,
    k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. Rank-based, so score scales never need calibration."""
    weights = weights or {}
    scores: dict[str, float] = defaultdict(float)
    for name, items in rankings.items():
        w = weights.get(name, 1.0)
        for rank, (uid, _score) in enumerate(items):
            scores[uid] += w / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def _match(u: Unit, plan: QueryPlan) -> bool:
    if plan.sources and u.source not in plan.sources:
        return False
    if plan.exts and u.ext not in plan.exts:
        return False
    if plan.ts_from is not None and (u.ts is None or u.ts < plan.ts_from):
        return False
    if plan.ts_to is not None and (u.ts is None or u.ts >= plan.ts_to):
        return False
    if plan.size_min is not None and (u.size is None or u.size < plan.size_min):
        return False
    if plan.size_max is not None and (u.size is None or u.size > plan.size_max):
        return False
    if plan.scope_prefix and not (u.scope or "").startswith(plan.scope_prefix):
        return False
    return True


def _heuristic_score(
    r: SearchResult, plan: QueryPlan, raw_query: str, max_base: float
) -> float:
    """Blend retrieval (0.78) with cheap priors.

    Retrieval is normalised to [0,1] first: raw RRF scores are ~1/60, so adding
    any absolute bonus without normalising lets "modified recently" swamp rank.
    """
    u = r.unit
    base = (r.score / max_base) if max_base else 0.0
    nq = normalize(raw_query)
    ns = normalize(plan.semantic)
    nt = normalize(u.title)

    # Recency is a filesystem prior. Chat is a timeline: an old message that
    # matches exactly must not be pushed under a recently-touched file.
    if u.source == "fs" and u.ts:
        days = max(0.0, (time.time() - u.ts) / 86400.0)
        s = base * (0.94 + 0.06 * math.exp(-days / 90.0))
        if days <= 7:
            r.reasons.append("最近修改")
    else:
        s = base
        if u.source != "fs":
            s += 0.01

    if nt and nt == nq:
        s += 0.20
        r.reasons.append("标题精确匹配")
    elif ns and ns in nt:
        s += 0.08
        r.reasons.append("标题包含查询词")

    if plan.exts and u.ext in plan.exts:
        s += 0.03

    s -= 0.003 * path_depth(u.path)
    if u.kind == "file":
        s += 0.01
    if u.meta.get("unindexed"):
        r.reasons.append("Everything 实时结果（未建索引）")
    return s


def _passage(r: SearchResult, max_chars: int = 600) -> str:
    u = r.unit
    parts = [u.title]
    if u.path:
        parts.append(u.path)
    if r.snippet:
        parts.append(r.snippet)
    return " | ".join(p for p in parts if p)[:max_chars]


def search(
    conn,
    store: VectorStore | None,
    embedder: Embedder | None,
    query: str,
    *,
    limit: int = 20,
    plan: QueryPlan | None = None,
    use_semantic: bool = True,
    everything=None,
    rerank: bool = True,
    reranker=None,
    rerank_top: int = 50,
    rerank_weight: float = 0.75,
    per_source: int = 200,
    k_rrf: int = 60,
) -> list[SearchResult]:
    plan = plan or planner.plan(query)
    semantic_query = plan.semantic or query
    rankings: dict[str, list[tuple[str, float]]] = {}
    extra: dict[str, Unit] = {}

    # 1) lexical: SQLite FTS5 over indexed units
    fts = db.search_fts(conn, semantic_query, limit=per_source, plan=plan)
    if fts:
        rankings["fts"] = fts

    # 1b) substring fallback for Latin fragments (e.g. "WifiSenseSur")
    if re.search(r"[A-Za-z0-9]{4,}", semantic_query):
        like = db.search_like(conn, semantic_query, limit=30, plan=plan)
        if like:
            rankings["substring"] = like

    # 2) live Everything pass (covers files that are not indexed yet)
    if everything is not None:
        try:
            metas = everything.search(semantic_query, limit=100)
        except Exception:
            metas = []
        ev: list[tuple[str, float]] = []
        for m in metas:
            uid = stable_id("fs", m.path)
            if uid not in extra:
                extra[uid] = unit_from_path(m.path, size=m.size, mtime=m.mtime)
            ev.append((uid, 0.0))
        if ev:
            rankings["everything"] = ev

    # 3) semantic: vector store
    if use_semantic and embedder is not None and store is not None and len(store):
        qv = embedder.encode_queries([semantic_query])[0]
        cand = store.search(qv, k=max(per_source * 2, 200))
        units = db.get_units(conn, [uid for uid, _ in cand])
        vec: list[tuple[str, float]] = []
        for uid, score in cand:
            u = units.get(uid)
            if u is None or not _match(u, plan):
                continue
            vec.append((uid, score))
            if len(vec) >= per_source:
                break
        if vec:
            rankings["vector"] = vec

    if not rankings:
        return []

    # Resolve every candidate to its display unit *before* fusion. Otherwise a
    # file that appears as both `file` and `chunk` has its RRF score summed and
    # systematically outranks a single message.
    all_ids: set[str] = set()
    for lst in rankings.values():
        all_ids.update(uid for uid, _ in lst)
    units = db.get_units(conn, [i for i in all_ids if i not in extra])
    units.update(extra)

    # fetch parents of chunk hits so they can be folded into the file unit
    parent_ids = {u.parent_id for u in units.values() if u.parent_id}
    missing_parents = [p for p in parent_ids if p not in units]
    if missing_parents:
        units.update(db.get_units(conn, missing_parents))

    collapsed: dict[str, list[tuple[str, float]]] = {}
    snippets: dict[str, str] = {}
    for name, lst in rankings.items():
        out: list[tuple[str, float]] = []
        seen_base: set[str] = set()
        for uid, score in lst:
            u = units.get(uid)
            if u is None:
                continue
            base = u.parent_id or u.id
            if base not in units:
                base = u.id
            if u.kind == "chunk" and base not in snippets:
                snippets[base] = u.text
            if base in seen_base:
                continue
            seen_base.add(base)
            out.append((base, score))
        if out:
            collapsed[name] = out

    if not collapsed:
        return []

    fused = rrf(collapsed, k=k_rrf, weights={"fts": 1.0, "vector": 1.0, "substring": 0.6, "everything": 0.8})

    fused_ids = [uid for uid, _ in fused[:400]]
    missing = [i for i in fused_ids if i not in units]
    if missing:
        units.update(db.get_units(conn, missing))

    fts_set = {x for x, _ in collapsed.get("fts", [])}
    vec_set = {x for x, _ in collapsed.get("vector", [])}
    ev_set = {x for x, _ in collapsed.get("everything", [])}

    results: list[SearchResult] = []
    for uid, score in fused[:400]:
        u = units.get(uid)
        if u is None:
            continue
        reasons: list[str] = []
        if uid in fts_set:
            reasons.append("关键词命中")
        if uid in vec_set:
            reasons.append("语义命中")
        if uid in ev_set:
            reasons.append("Everything 实时结果")
        if u.kind == "chunk":
            reasons.append("正文命中")
        results.append(
            SearchResult(
                unit=u,
                score=score,
                reasons=reasons,
                snippet=(snippets.get(uid) or u.text or u.title or "")[:220],
                matched=[u.kind],
            )
        )

    # dedupe by path (an indexed unit and a live Everything hit can be the same file)
    results.sort(key=lambda r: -r.score)
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for r in results:
        key = r.unit.path or r.unit.id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # A cross-encoder must not overturn a literal title match: "学与技术" or an
    # exact filename already has the strongest possible evidence.
    nq = normalize(query)
    skip_rerank = (
        bool(deduped)
        and len(nq) >= 4
        and nq in normalize(deduped[0].unit.title or "")
    )

    if reranker is not None and deduped and not skip_rerank:
        top = deduped[: max(1, rerank_top)]
        passages = [_passage(r) for r in top]
        ce = reranker.score(query, passages)
        max_raw = max(r.score for r in deduped) or 1.0
        for r, s_ce in zip(top, ce):
            base = r.score / max_raw
            r.score = (1.0 - rerank_weight) * base + rerank_weight * s_ce
            r.reasons.append(f"精排 {s_ce:.2f}")

    if rerank and deduped:
        max_base = max(r.score for r in deduped) or 1.0
        for r in deduped:
            r.score = _heuristic_score(r, plan, query, max_base)
        deduped.sort(key=lambda r: -r.score)

    return deduped[:limit]
