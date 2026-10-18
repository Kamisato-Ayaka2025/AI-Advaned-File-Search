from __future__ import annotations

import json

from aimem import db
from aimem.embedders import HashEmbedder
from aimem.index.indexer import Indexer
from aimem.ingest.jsonl import Message, build_units
from aimem.search.pipeline import search
from aimem.vectors import VectorStore


def _setup(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    store = VectorStore(tmp_path / "t.vectors").load()
    emb = HashEmbedder()
    indexer = Indexer(conn, store, emb, verbose=False)
    return conn, store, emb, indexer


def _write(p, text, mtime=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_index_and_search_exact_name(tmp_path):
    corpus = tmp_path / "corpus"
    _write(corpus / "2025Q3_设备采购方案_终版.csv", "项目,供应商,报价\n服务器,华信,128000\n")
    _write(corpus / "会议纪要_0321.md", "新能源项目立项讨论，预算和时间表。")
    _write(corpus / "GPU_thermal_throttling_analysis.md", "显卡温度过高导致降频，游戏掉帧。")
    _write(corpus / "node_modules" / "junk.js", "must not be indexed")

    conn, store, emb, indexer = _setup(tmp_path)
    stats = indexer.index_files([str(corpus)], want_text=True)
    assert stats.units >= 3

    res = search(conn, store, emb, "设备采购方案", limit=5)
    assert res and "设备采购方案" in (res[0].unit.path or "")

    # excluded dir must not leak in
    assert not any("node_modules" in (r.unit.path or "") for r in res)

    # content-only match (filename has no "掉帧")
    res = search(conn, store, emb, "游戏掉帧", limit=5)
    assert any("GPU_thermal" in (r.unit.path or "") for r in res)


def test_chinese_two_char_query(tmp_path):
    corpus = tmp_path / "corpus"
    _write(corpus / "合同_供应商A_违约金条款.md", "第 8 条 违约责任：每日 0.5% 违约金。")
    conn, store, emb, indexer = _setup(tmp_path)
    indexer.index_files([str(corpus)])
    res = search(conn, store, emb, "违约", limit=5)
    assert res, "two-character Chinese query must match"


def test_jsonl_reuses_the_same_engine(tmp_path):
    corpus = tmp_path / "corpus"
    _write(corpus / "报价对比表.csv", "供应商,单价\n华信,12800\n")

    conn, store, emb, indexer = _setup(tmp_path)
    indexer.index_files([str(corpus)])

    msgs = [
        Message("wechat", "设备采购群", "张经理", 1760263680.0,
                "新报价已经发给你了，之前那个版本别用了。", [], "wx_1"),
        Message("wechat", "设备采购群", "我", 1760263740.0,
                "收到，设备采购方案我按最终版更新。", [], "wx_2"),
    ]
    units = build_units(msgs)
    indexer.index_units(units)

    # no engine change: same search() call, now with chat units in the db
    res = search(conn, store, emb, "之前那个版本别用了", limit=5)
    assert res
    assert res[0].unit.source == "wechat"
    assert "版本" in res[0].unit.text

    # both sources are searchable together
    res = search(conn, store, emb, "报价", limit=10)
    sources = {r.unit.source for r in res}
    assert "fs" in sources and "wechat" in sources


def test_incremental_skips_unchanged(tmp_path):
    corpus = tmp_path / "corpus"
    f = _write(corpus / "a.md", "hello world")
    conn, store, emb, indexer = _setup(tmp_path)
    s1 = indexer.index_files([str(corpus)])
    assert s1.changed == 1
    s2 = indexer.index_files([str(corpus)])
    assert s2.changed == 0 and s2.skipped == 1
    assert f.exists()


class _FakeEverything:
    def search(self, query, limit=100):
        from aimem.models import FileMeta

        return [
            FileMeta(
                path="/fake/实时报价单_张经理.xlsx",
                name="实时报价单_张经理.xlsx",
                size=1024,
                mtime=1760263680.0,
                ext="xlsx",
            )
        ]


def test_everything_live_overlay(tmp_path):
    conn, store, emb, indexer = _setup(tmp_path)
    res = search(conn, store, emb, "实时报价单", everything=_FakeEverything(), limit=5)
    assert res
    assert res[0].unit.meta.get("unindexed") is True
    assert "Everything" in " ".join(res[0].reasons)


def test_source_filter(tmp_path):
    corpus = tmp_path / "corpus"
    _write(corpus / "报价对比表.csv", "供应商,单价\n华信,12800\n")
    conn, store, emb, indexer = _setup(tmp_path)
    indexer.index_files([str(corpus)])
    msgs = [
        Message("wechat", "设备采购群", "张经理", 1760263680.0, "新报价发你了", [], "w1"),
        Message("qq", "老同学", "陈同学", 1760263680.0, "报价的事再说", [], "q1"),
    ]
    indexer.index_units(build_units(msgs))
    res = search(conn, store, emb, "报价 微信", limit=10)
    assert res
    assert all(r.unit.source == "wechat" for r in res)


class _FakeReranker:
    name = "fake"

    def score(self, query, passages, batch_size=16):
        # boost whatever mentions "beta", regardless of the retrieval order
        return [1.0 if "beta" in p.lower() else 0.0 for p in passages]


def test_reranker_can_reorder(tmp_path):
    corpus = tmp_path / "corpus"
    _write(corpus / "alpha.md", "alpha alpha alpha")
    _write(corpus / "beta.md", "beta beta beta")
    _write(corpus / "gamma.md", "gamma gamma gamma")

    conn, store, emb, indexer = _setup(tmp_path)
    indexer.index_files([str(corpus)])

    base = search(conn, store, emb, "alpha alpha", limit=3)
    assert base and "alpha" in (base[0].unit.path or "")

    boosted = search(conn, store, emb, "alpha alpha", limit=3, reranker=_FakeReranker())
    assert boosted and "beta" in (boosted[0].unit.path or "")


def test_make_reranker_none():
    from aimem.rerank import make_reranker

    assert make_reranker(None) is None
    assert make_reranker("none") is None


def test_changed_message_is_reembedded(tmp_path):
    conn, store, emb, indexer = _setup(tmp_path)
    units = build_units([Message("wechat", "c", "s", 1.0, "alpha content", [], "m1")])
    indexer.index_units(units)

    res = search(conn, store, emb, "alpha", limit=5)
    assert res and "alpha" in (res[0].unit.text or "")

    # same message id, changed text (e.g. OCR caption added on re-export)
    changed = build_units([Message("wechat", "c", "s", 1.0, "beta content", [], "m1")])
    stats = indexer.index_units(changed, force_embed=False)
    assert stats.embedded == 1

    res = search(conn, store, emb, "beta", limit=5)
    assert res and "beta" in (res[0].unit.text or "")
    old = search(conn, store, emb, "alpha", limit=5)
    assert not old or "alpha" not in (old[0].unit.text or "")
