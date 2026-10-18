"""Layered evaluation on the real C:/D: index.

L1-exact   : query == filename stem (the common "I remember the name" case)
L1-partial : query == a 3-4 char Chinese slice of the filename
L2-semantic: paraphrased content queries with no filename keywords
"""

import json
import random
import re
import time
from pathlib import Path


from aimem import db  # noqa: E402
from aimem.embedders import make_embedder  # noqa: E402
from aimem.rerank import make_reranker  # noqa: E402
from aimem.search.pipeline import search  # noqa: E402
from aimem.vectors import VectorStore  # noqa: E402

import os
DB = os.environ.get("AIMEM_DB", r"C:\Users\user\aimem-test\cdisk.db")
STORE = os.environ.get("AIMEM_STORE", r"C:\Users\user\aimem-test\cdisk.vectors")
EMBED = os.environ.get("AIMEM_EMBED", "st:BAAI/bge-small-zh-v1.5")
GOLD = r"real_semantic_gold.json"
OUT = os.environ.get("AIMEM_OUT", r"C:\Users\user\aimem-test\eval_real.json")
RERANK = os.environ.get("AIMEM_RERANK") or None
RERANKER = None
RERANK_WEIGHT = float(os.environ.get("AIMEM_RERANK_WEIGHT", "0.75"))

DOC_EXT = {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "txt", "md", "csv"}
CJK = re.compile(r"[\u4e00-\u9fff]")


def _norm(p):
    return (p or "").replace("\\", "/")


def _rank(paths, target):
    for i, p in enumerate(paths):
        if p == target:
            return i + 1
    return None


def _summ(items):
    denom = max(1, len(items))
    return {
        "n": len(items),
        "recall@10": round(sum(1 for x in items if x["rank"]) / denom, 3),
        "mrr": round(sum(1 / (x["rank"] or 999) for x in items) / denom, 3),
        "items": items,
    }


def layer1_exact(conn, store, emb, n=15):
    rows = conn.execute(
        "select id,title,path,ext from units where kind='file' and length(title)>=3"
    ).fetchall()
    docs = [r for r in rows if (r["ext"] or "").lower() in DOC_EXT]
    random.seed(11)
    picked = random.sample(docs, min(n, len(docs)))
    items = []
    for r in picked:
        t0 = time.perf_counter()
        res = search(conn, store, emb, r["title"], limit=10, reranker=RERANKER, rerank_weight=RERANK_WEIGHT)
        ms = round((time.perf_counter() - t0) * 1000)
        paths = [x.unit.path for x in res]
        items.append({"query": r["title"], "target": r["path"], "rank": _rank(paths, r["path"]), "ms": ms})
    return _summ(items)


def layer1_partial(conn, store, emb, n=15):
    rows = conn.execute(
        "select id,title,path,ext from units where kind='file' and length(title)>=6"
    ).fetchall()
    docs = [
        r
        for r in rows
        if (r["ext"] or "").lower() in DOC_EXT and len(CJK.findall(r["title"] or "")) >= 4
    ]
    random.seed(23)
    picked = random.sample(docs, min(n, len(docs)))
    items = []
    for r in picked:
        title = r["title"]
        runs = re.findall(r"[\u4e00-\u9fff]{4,}", title)
        if not runs:
            continue
        run = max(runs, key=len)
        start = max(0, len(run) // 2 - 2)
        q = run[start : start + 4]
        t0 = time.perf_counter()
        res = search(conn, store, emb, q, limit=10, reranker=RERANKER, rerank_weight=RERANK_WEIGHT)
        ms = round((time.perf_counter() - t0) * 1000)
        paths = [_norm(x.unit.path) for x in res]
        rank = next((i + 1 for i, p in enumerate(paths) if q in p), None)
        items.append(
            {"query": q, "target": _norm(r["path"]), "rank": rank, "top": paths[:3], "ms": ms}
        )
    return _summ(items)


def layer2(conn, store, emb, gold_path):
    gold = json.loads(Path(gold_path).read_text("utf-8"))
    items = []
    for item in gold:
        t0 = time.perf_counter()
        res = search(conn, store, emb, item["query"], limit=10, reranker=RERANKER, rerank_weight=RERANK_WEIGHT)
        ms = round((time.perf_counter() - t0) * 1000)
        hay = [_norm(x.unit.path) + " " + (x.unit.title or "") for x in res]
        rank = None
        for i, h in enumerate(hay):
            if any(p.lower() in h.lower() for p in item["relevant"]):
                rank = i + 1
                break
        items.append({"query": item["query"], "rank": rank, "top": hay[:3], "ms": ms})
    return _summ(items)


def main():
    global RERANKER
    conn = db.connect(DB)
    store = VectorStore(STORE).load()
    emb = make_embedder(EMBED, "cuda")
    RERANKER = make_reranker(RERANK, "cuda", "float16") if RERANK else None

    t = time.time()
    r1a = layer1_exact(conn, store, emb)
    r1b = layer1_partial(conn, store, emb)
    r2 = layer2(conn, store, emb, GOLD) if Path(GOLD).exists() else None
    payload = {"l1_exact": r1a, "l1_partial": r1b, "l2_semantic": r2, "elapsed": round(time.time() - t, 1)}
    Path(OUT).write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")

    for name, r in (("L1-exact", r1a), ("L1-partial", r1b), ("L2-semantic", r2)):
        if r:
            print(f"{name:12s} n={r['n']:2d}  recall@10={r['recall@10']:.3f}  MRR={r['mrr']:.3f}")
    print("elapsed", payload["elapsed"], "s")


if __name__ == "__main__":
    main()
