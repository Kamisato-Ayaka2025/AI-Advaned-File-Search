from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

from .models import SearchResult


def load_gold(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    for line in Path(path).read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        rows.append(json.loads(line))
    return rows


def _haystack(r: SearchResult) -> str:
    u = r.unit
    return " ".join(filter(None, [u.path, u.title, u.text, r.snippet])).lower()


def _hits(r: SearchResult, patterns: list[str]) -> bool:
    hay = _haystack(r)
    return any(p.lower() in hay for p in patterns)


def _ndcg(rel: list[bool], k: int) -> float:
    dcg = sum((1.0 if r else 0.0) / math.log2(i + 2) for i, r in enumerate(rel[:k]))
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, sum(rel))))
    return dcg / ideal if ideal else 0.0


def evaluate(
    run: Callable[[str, int], list[SearchResult]],
    gold: list[dict],
    *,
    limit: int = 50,
) -> dict:
    per: list[dict] = []
    for item in gold:
        query = item["query"]
        patterns = item.get("relevant") or item.get("paths") or []
        results = run(query, limit)
        rel = [_hits(r, patterns) for r in results]
        first = next((i for i, v in enumerate(rel) if v), None)
        rr = 1.0 / (first + 1) if first is not None else 0.0
        found = set()
        for r in results:
            hay = _haystack(r)
            for p in patterns:
                if p.lower() in hay:
                    found.add(p)
        recall = len(found) / len(patterns) if patterns else 0.0
        per.append(
            {
                "query": query,
                "recall": recall,
                "rr": rr,
                "ndcg10": _ndcg(rel, 10),
                "first_rank": None if first is None else first + 1,
                "top": [r.unit.path or r.unit.title for r in results[:3]],
            }
        )
    n = len(per) or 1
    return {
        "n": len(per),
        "recall": sum(p["recall"] for p in per) / n,
        "mrr": sum(p["rr"] for p in per) / n,
        "ndcg10": sum(p["ndcg10"] for p in per) / n,
        "zero": sum(1 for p in per if p["first_rank"] is None) / n,
        "per_query": per,
    }


def format_report(report: dict, *, show_per_query: bool = True) -> str:
    lines = [
        f"queries={report['n']}  Recall@K={report['recall']:.3f}  "
        f"MRR={report['mrr']:.3f}  nDCG@10={report['ndcg10']:.3f}  "
        f"zero-result={report['zero']:.0%}",
    ]
    if show_per_query:
        lines.append("")
        for p in report["per_query"]:
            mark = "✓" if p["first_rank"] else "✗"
            lines.append(
                f" {mark} recall={p['recall']:.2f} rr={p['rr']:.2f} "
                f"nDCG={p['ndcg10']:.2f}  {p['query']}"
            )
            if p["first_rank"] is None:
                lines.append(f"      top: {p['top']}")
    return "\n".join(lines)
