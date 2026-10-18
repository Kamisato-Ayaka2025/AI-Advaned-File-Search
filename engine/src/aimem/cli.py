from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import db
from .embedders import make_embedder
from .eval import evaluate, format_report, load_gold
from .everything import EverythingClient
from .index.indexer import Indexer
from .ingest.jsonl import build_units, load_jsonl
from .ingest.markdown import parse_dir, parse_markdown
from .rerank import make_reranker
from .search.pipeline import search
from .text import date_label, size_label
from .vectors import VectorStore


def _store_path(db_path: str) -> Path:
    return Path(db_path).with_suffix(".vectors")


def _open(args) -> tuple:
    conn = db.connect(args.db)
    store = VectorStore(_store_path(args.db)).load()
    return conn, store


def _embedder(args, conn, *, default: str = "hash"):
    spec = args.embed or db.get_meta(conn, "embedder") or default
    if spec in ("none", "off"):
        return None
    return make_embedder(spec, getattr(args, "device", None))


def _check_dim(conn, embedder) -> None:
    if embedder is None:
        return
    stored = db.get_meta(conn, "embedder")
    if stored and stored != embedder.name:
        raise SystemExit(
            f"索引使用的 embedder 是 {stored!r}，当前是 {embedder.name!r}。"
            f"请改用 --embed {stored}，或用 --force 重建索引。"
        )
    dim = db.get_meta(conn, "dim")
    if dim and int(dim) != embedder.dim:
        raise SystemExit(
            f"embedding 维度不一致：索引是 {dim}，当前模型是 {embedder.dim}。"
            "请用同一个 --embed，或重建索引。"
        )


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_init(args) -> None:
    conn, store = _open(args)
    store.save()
    print(f"initialized db={args.db} vectors={_store_path(args.db)}")


def cmd_index(args) -> None:
    conn, store = _open(args)
    stored = db.get_meta(conn, "embedder")
    embedder = _embedder(args, conn)
    if stored and embedder is not None and stored != embedder.name and not args.force:
        raise SystemExit(
            f"已有索引使用 {stored!r}，当前请求 {embedder.name!r}。\n"
            "换 embedder 必须重建：加 --force（会重新嵌入全部文件）。"
        )
    indexer = Indexer(conn, store, embedder, batch_size=args.batch)
    stats = indexer.index_files(
        args.roots,
        force=args.force,
        want_chunks=not args.no_chunks,
        want_text=not args.no_text,
        max_files=args.max_files,
        max_chars=args.max_chars,
    )
    print(stats.summary())


def cmd_search(args) -> None:
    conn, store = _open(args)
    embedder = None if args.no_semantic else _embedder(args, conn)
    if embedder is not None:
        _check_dim(conn, embedder)
    everything = EverythingClient(port=args.port) if args.everything else None
    reranker = make_reranker(args.rerank, args.device, args.rerank_dtype) if args.rerank else None
    results = search(
        conn,
        store,
        embedder,
        args.query,
        limit=args.limit,
        use_semantic=not args.no_semantic,
        everything=everything,
        rerank=not args.no_rerank,
        reranker=reranker,
        rerank_top=args.rerank_top,
    )
    if args.json:
        print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
        return
    if not results:
        print("(no results)")
        return
    for i, r in enumerate(results, 1):
        u = r.unit
        title = u.title or u.path or u.id
        print(f"{i:>2}. {title}")
        bits = [f"[{u.source}/{u.kind}]", date_label(u.ts), size_label(u.size)]
        print("    " + "  ".join(b for b in bits if b) + f"  score={r.score:.3f}")
        if u.path:
            print(f"    {u.path}")
        if r.reasons:
            print("    " + " · ".join(r.reasons))
        snippet = " ".join((r.snippet or "").split())
        if snippet:
            print(f"    {snippet[:160]}")
        print()


def cmd_import_jsonl(args) -> None:
    conn, store = _open(args)
    embedder = _embedder(args, conn)
    msgs = load_jsonl(args.file)
    if not msgs:
        raise SystemExit(f"没有从 {args.file} 读到消息")
    units = build_units(msgs, window=args.window)
    indexer = Indexer(conn, store, embedder, batch_size=args.batch)
    stats = indexer.index_units(units, force_embed=args.force)
    print(
        f"imported messages={len(msgs)} units={len(units)} embedded={stats.embedded} "
        f"db={args.db}"
    )


def cmd_import_markdown(args) -> None:
    conn, store = _open(args)
    embedder = _embedder(args, conn)
    path = Path(args.path)
    if path.is_dir():
        msgs = parse_dir(path, platform=args.platform)
    else:
        msgs = parse_markdown(path, platform=args.platform)
    if not msgs:
        raise SystemExit(f"没有从 {path} 解析出消息")
    units = build_units(msgs, window=args.window)
    indexer = Indexer(conn, store, embedder, batch_size=args.batch)
    stats = indexer.index_units(units, force_embed=args.force)
    print(
        f"imported messages={len(msgs)} units={len(units)} embedded={stats.embedded} "
        f"db={args.db}"
    )


def cmd_eval(args) -> None:
    conn, store = _open(args)
    embedder = None if args.no_semantic else _embedder(args, conn)
    if embedder is not None:
        _check_dim(conn, embedder)
    gold = load_gold(args.gold)
    reranker = make_reranker(args.rerank, args.device, args.rerank_dtype) if args.rerank else None

    def run(query: str, limit: int):
        return search(
            conn,
            store,
            embedder,
            query,
            limit=limit,
            use_semantic=not args.no_semantic,
            rerank=not args.no_rerank,
            reranker=reranker,
            rerank_top=args.rerank_top,
            rerank_weight=args.rerank_weight,
        )

    report = evaluate(run, gold, limit=args.limit)
    print(format_report(report, show_per_query=not args.quiet))


def cmd_serve(args) -> None:
    from .server import serve

    conn = db.connect(args.db)
    embed = args.embed or db.get_meta(conn, "embedder") or "st:BAAI/bge-small-zh-v1.5"
    store = args.store or str(_store_path(args.db))
    serve(
        args.db,
        store,
        host=args.host,
        port=args.port,
        embed=embed,
        rerank=args.rerank,
        device=args.device,
    )


def cmd_stats(args) -> None:
    conn, _ = _open(args)
    print(json.dumps(db.stats(conn), ensure_ascii=False, indent=2))


def cmd_probe(args) -> None:
    client = EverythingClient(host=args.host, port=args.port)
    ok, msg = client.probe()
    print(f"{'OK' if ok else 'FAIL'} {client.base} :: {msg}")
    if ok and args.query:
        rows = client.search(args.query, limit=5)
        for m in rows:
            print(f"  {m.path}  ({size_label(m.size)})")


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aimem",
        description="可复用的个人信息记忆检索引擎（文件系统优先，聊天记录可复用同一核心）",
    )
    p.add_argument("--db", default=os.environ.get("AIMEM_DB", "aimem.db"))
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="初始化数据库")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("index", help="索引文件系统目录")
    s.add_argument("roots", nargs="+")
    s.add_argument("--force", action="store_true")
    s.add_argument("--no-chunks", action="store_true")
    s.add_argument("--no-text", action="store_true")
    s.add_argument("--max-files", type=int, default=200_000)
    s.add_argument("--max-chars", type=int, default=4000)
    s.add_argument("--embed", default=None, help="none|hash|st|qwen|st:<model>")
    s.add_argument("--device", default=None, help="cpu|cuda|auto")
    s.add_argument("--batch", type=int, default=32)
    s.set_defaults(func=cmd_index)

    s = sub.add_parser("search", help="搜索")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-semantic", action="store_true")
    s.add_argument("--no-rerank", action="store_true")
    s.add_argument("--rerank", default=None, help="bge|ce:<model>|none")
    s.add_argument("--rerank-top", type=int, default=50)
    s.add_argument("--rerank-dtype", default="float16")
    s.add_argument("--rerank-weight", type=float, default=0.75)
    s.add_argument("--everything", action="store_true", help="叠加 Everything 实时结果")
    s.add_argument("--port", type=int, default=80)
    s.add_argument("--embed", default=None)
    s.add_argument("--device", default=None)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("import-jsonl", help="导入聊天记录（JSONL），复用同一检索核心")
    s.add_argument("file")
    s.add_argument("--window", type=int, default=2)
    s.add_argument("--force", action="store_true")
    s.add_argument("--embed", default=None)
    s.add_argument("--device", default=None)
    s.add_argument("--batch", type=int, default=32)
    s.set_defaults(func=cmd_import_jsonl)

    s = sub.add_parser("import-markdown", help="导入 Markdown 格式的聊天记录")
    s.add_argument("path")
    s.add_argument("--platform", default=None)
    s.add_argument("--window", type=int, default=2)
    s.add_argument("--force", action="store_true")
    s.add_argument("--embed", default=None)
    s.add_argument("--device", default=None)
    s.add_argument("--batch", type=int, default=32)
    s.set_defaults(func=cmd_import_markdown)

    s = sub.add_parser("eval", help="跑评测集")
    s.add_argument("gold")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--no-semantic", action="store_true")
    s.add_argument("--no-rerank", action="store_true")
    s.add_argument("--rerank", default=None, help="bge|ce:<model>|none")
    s.add_argument("--rerank-top", type=int, default=50)
    s.add_argument("--rerank-dtype", default="float16")
    s.add_argument("--rerank-weight", type=float, default=0.75)
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--embed", default=None)
    s.add_argument("--device", default=None)
    s.set_defaults(func=cmd_eval)

    s = sub.add_parser("serve", help="启动本地搜索 Web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--store", default=None)
    s.add_argument("--embed", default=None)
    s.add_argument("--rerank", default=None)
    s.add_argument("--device", default=None)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("stats", help="查看索引统计")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("probe", help="测试 Everything HTTP 服务")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=80)
    s.add_argument("--query", default=None)
    s.set_defaults(func=cmd_probe)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if getattr(args, "device", None) == "auto":
        args.device = _auto_device()
    args.func(args)


def _auto_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


if __name__ == "__main__":
    main(sys.argv[1:])
