from __future__ import annotations

from original_words.retrieval import (
    ContextExpander,
    HybridSearcher,
    RetrievalIndex,
    SearchFilters,
    SearchRequest,
)
from original_words.retrieval.hybrid import rrf_fuse

from .support import CHAT_TITLES, ConceptEmbedder, ts


def _messages_of(response):
    return {message_id for hit in response.hits for message_id in hit.message_ids}


def test_fts_hit_has_reason_and_message_ids(searcher):
    response = searcher.search(SearchRequest("旧版本", top_k=5))
    assert response.hits
    assert "a1" in _messages_of(response)
    assert any("关键词命中" in hit.reasons for hit in response.hits)


def test_two_character_chinese_query(searcher):
    response = searcher.search(SearchRequest("报价", top_k=5))
    assert {"a1", "a3"} & _messages_of(response)


def test_vector_channel_recalls_paraphrase(searcher):
    response = searcher.search(SearchRequest("发烫", top_k=5))
    assert "b1" in _messages_of(response)
    assert any("语义命中" in hit.reasons for hit in response.hits)
    assert response.degraded is False


def test_time_filter_excludes_unknown_time(searcher):
    filters = SearchFilters(
        time_start=ts(2025, 10, 12),
        time_end=ts(2025, 10, 13),
    )
    response = searcher.search(SearchRequest("旧版本", filters=filters, top_k=10))
    assert response.hits
    assert "c1" not in _messages_of(response)


def test_sender_filter(searcher):
    filters = SearchFilters(sender_ids=("u1",))
    response = searcher.search(SearchRequest("报价", filters=filters, top_k=10))
    assert response.hits
    assert "a1" in _messages_of(response)


def test_chat_filter(searcher):
    filters = SearchFilters(chat_ids=("chat-b",))
    response = searcher.search(SearchRequest("显卡", filters=filters, top_k=10))
    assert response.hits
    assert all(hit.chat_id == "chat-b" for hit in response.hits)


def test_hits_are_deduplicated_by_message_overlap(searcher):
    response = searcher.search(SearchRequest("报价", top_k=10))
    ids = [hit.unit_id for hit in response.hits]
    assert len(ids) == len(set(ids))
    message_sets = [set(hit.message_ids) for hit in response.hits]
    for left in range(len(message_sets)):
        for right in range(left + 1, len(message_sets)):
            union = message_sets[left] | message_sets[right]
            if union:
                assert len(message_sets[left] & message_sets[right]) / len(union) <= 0.5


def test_empty_query_returns_empty(searcher):
    response = searcher.search(SearchRequest("   ", top_k=5))
    assert response.hits == ()


def test_no_result_does_not_raise(searcher):
    response = searcher.search(SearchRequest("zzzz-not-present", top_k=5))
    assert response.hits == ()


def test_revision_is_reported(searcher):
    response = searcher.search(SearchRequest("报价", top_k=5))
    assert response.index_revision == "rev-test"


def test_model_missing_is_visible_degradation(tmp_path, messages):
    store = RetrievalIndex(tmp_path / "lexical.db", embedder=None, revision="lexical-rev")
    store.build(messages, chat_titles=CHAT_TITLES)
    response = HybridSearcher(store).search(SearchRequest("报价", top_k=5))
    assert response.degraded is True
    assert response.hits
    store.close()


def test_context_expands_before_and_after(index):
    context = index.get_context("chat-a", 2, 2, before=1, after=1)
    assert [message.message_id for message in context] == ["a1", "a2", "a3"]


def test_explicit_reply_expansion_follows_quote(index):
    expander = ContextExpander(index)
    seed = index.get_message("a4")
    assert seed is not None
    expanded = expander.expand_replies([seed], max_hops=1)
    assert {message.message_id for message in expanded} == {"a1", "a4"}


def test_rrf_is_rank_based():
    fused = rrf_fuse({"fts": ["a", "b"], "vector": ["b", "c"]}, k=60)
    assert [unit_id for unit_id, _score in fused][0] == "b"


def test_index_stats(index):
    stats = index.stats()
    assert stats["units"] > 0
    assert stats["messages"] == 7
    assert stats["vectors"] > 0
    assert stats["index_revision"] == "rev-test"


def test_vector_store_rejects_wrong_dimension(index):
    import pytest

    with pytest.raises(ValueError):
        index.vector_search([1.0], limit=1)


def test_exact_filename_channel(searcher):
    response = searcher.search(SearchRequest("报价单_最终版.xlsx", top_k=5))
    assert response.hits
    assert any("精确实体命中" in hit.reasons for hit in response.hits)


def test_auto_revision_is_stable(tmp_path, messages):
    first = RetrievalIndex(tmp_path / "a.db", embedder=ConceptEmbedder())
    first.build(messages, chat_titles=CHAT_TITLES)
    second = RetrievalIndex(tmp_path / "b.db", embedder=ConceptEmbedder())
    second.build(messages, chat_titles=CHAT_TITLES)
    try:
        assert first.revision != "unbuilt"
        assert first.revision == second.revision
    finally:
        first.close()
        second.close()
