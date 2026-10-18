from __future__ import annotations

from original_words.retrieval import SearchRequest
from original_words.retrieval.evaluate import evaluate, format_report


def test_evaluate_recall_and_mrr(searcher):
    gold = [
        {"query": "旧版本", "relevant_message_ids": ["a1"]},
        {"query": "发烫", "relevant_message_ids": ["b1"]},
        {"query": "not-found-zzz", "relevant_message_ids": ["a1"]},
    ]
    report = evaluate(lambda query: searcher.search(SearchRequest(query, top_k=10)), gold, k=10)
    assert report["n"] == 3
    assert 0.0 <= report["recall"] <= 1.0
    assert report["mrr"] > 0.0
    assert report["zero"] == 1 / 3
    text = format_report(report)
    assert "Recall@K" in text


def test_evaluate_empty_gold_does_not_divide_by_zero(searcher):
    report = evaluate(lambda query: searcher.search(SearchRequest(query)), [], k=10)
    assert report["n"] == 0
    assert report["recall"] == 0.0


def test_smoke_gold_file(searcher):
    from pathlib import Path

    from original_words.retrieval.evaluate import load_gold

    path = Path(__file__).resolve().parents[1] / "evaluation" / "gold_smoke.jsonl"
    gold = [row for row in load_gold(path) if row.get("relevant_message_ids")]
    report = evaluate(lambda query: searcher.search(SearchRequest(query, top_k=10)), gold, k=10)
    assert report["n"] == 4
    assert report["recall"] >= 0.75
