"""Small retrieval evaluation harness (Recall@K, MRR, nDCG@10, zero-result rate).

Gold rows are JSON objects with ``query`` and either ``relevant_message_ids`` or
``relevant_chunk_ids``.  The 80-question set and its dev/test split live in
``tests/evaluation/``; this module only computes metrics.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .types import SearchHit, SearchResponse

Run = Callable[[str], SearchResponse | Sequence[SearchHit]]


def load_gold(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        rows.append(json.loads(line))
    return rows


def _ndcg(flags: Sequence[bool], k: int, relevant_total: int) -> float:
    dcg = sum(1.0 / math.log2(index + 2) for index, flag in enumerate(flags[:k]) if flag)
    ideal_count = min(k, relevant_total)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return dcg / idcg if idcg else 0.0


def evaluate(run: Run, gold: Iterable[dict], *, k: int = 10) -> dict:
    per_query: list[dict] = []
    for item in gold:
        query = str(item["query"])
        response = run(query)
        hits = list(response.hits if isinstance(response, SearchResponse) else response)[:k]
        relevant_messages = set(item.get("relevant_message_ids") or ())
        relevant_chunks = set(item.get("relevant_chunk_ids") or ())
        total_relevant = len(relevant_messages | relevant_chunks)

        flags: list[bool] = []
        covered_messages: set[str] = set()
        covered_chunks: set[str] = set()
        first_rank: int | None = None
        for rank, hit in enumerate(hits, 1):
            hit_messages = set(hit.message_ids)
            hit_relevant = bool(hit_messages & relevant_messages) or hit.unit_id in relevant_chunks
            flags.append(hit_relevant)
            covered_messages |= hit_messages & relevant_messages
            if hit.unit_id in relevant_chunks:
                covered_chunks.add(hit.unit_id)
            if hit_relevant and first_rank is None:
                first_rank = rank

        covered = len(covered_messages | covered_chunks)
        recall = covered / total_relevant if total_relevant else 0.0
        per_query.append(
            {
                "query": query,
                "recall": recall,
                "rr": 1.0 / first_rank if first_rank else 0.0,
                "ndcg10": _ndcg(flags, 10, total_relevant),
                "first_rank": first_rank,
                "zero": not hits,
                "top": [hit.unit_id for hit in hits[:3]],
            }
        )

    count = len(per_query) or 1
    return {
        "n": len(per_query),
        "k": k,
        "recall": sum(row["recall"] for row in per_query) / count,
        "mrr": sum(row["rr"] for row in per_query) / count,
        "ndcg10": sum(row["ndcg10"] for row in per_query) / count,
        "zero": sum(1 for row in per_query if row["zero"]) / count,
        "per_query": per_query,
    }


def format_report(report: dict, *, show_per_query: bool = True) -> str:
    lines = [
        f"queries={report['n']} k={report['k']} "
        f"Recall@K={report['recall']:.3f} MRR={report['mrr']:.3f} "
        f"nDCG@10={report['ndcg10']:.3f} zero-result={report['zero']:.0%}"
    ]
    if show_per_query:
        lines.append("")
        for row in report["per_query"]:
            mark = "✓" if row["first_rank"] else "✗"
            lines.append(
                f" {mark} recall={row['recall']:.2f} rr={row['rr']:.2f} "
                f"nDCG={row['ndcg10']:.2f} {row['query']}"
            )
            if row["first_rank"] is None:
                lines.append(f"      top: {row['top']}")
    return "\n".join(lines)
