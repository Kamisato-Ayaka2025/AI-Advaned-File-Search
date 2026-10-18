from __future__ import annotations

from dataclasses import replace

import pytest

from original_words.llm.answer import (
    Answer,
    Citation,
    CitationError,
    CitationValidator,
    Claim,
    ExtractiveAnswerBuilder,
    answer_to_dict,
)

from .support import DictRepository, make_hit, message, ts


def _repo_and_hit():
    item = message()
    repo = DictRepository([item], revision="rev-test")
    hit = make_hit(item)
    return item, repo, hit


def _citation(item) -> Citation:
    return Citation(
        citation_id="c1",
        message_id=item.message_id,
        char_start=0,
        char_end=len(item.text),
        quote=item.text,
        chat_id=item.chat_id,
        sender=item.sender_name,
        timestamp=item.timestamp,
    )


def test_extractive_answer_has_valid_citation():
    item, repo, hit = _repo_and_hit()
    answer = ExtractiveAnswerBuilder(repo).build("报价", [hit])
    assert answer.status == "answered"
    assert answer.claims
    assert answer.citations
    assert answer.citations[0].quote == item.text
    assert CitationValidator().validate_answer(answer, repo, "rev-test") == []
    assert answer.timeline


def test_no_hits_returns_not_found():
    _, repo, _ = _repo_and_hit()
    answer = ExtractiveAnswerBuilder(repo).build("报价", [])
    assert answer.status == "not_found"
    assert answer.claims == ()
    assert answer.citations == ()


def test_unknown_message_is_rejected():
    item, repo, _ = _repo_and_hit()
    citation = replace(_citation(item), message_id="missing")
    with pytest.raises(CitationError) as error:
        CitationValidator().validate(citation, repo, "rev-test")
    assert error.value.code == "UNKNOWN_MESSAGE"


def test_quote_mismatch_is_rejected():
    item, repo, _ = _repo_and_hit()
    citation = replace(_citation(item), quote="不是原文")
    with pytest.raises(CitationError) as error:
        CitationValidator().validate(citation, repo, "rev-test")
    assert error.value.code == "QUOTE_MISMATCH"


def test_bad_span_is_rejected():
    item, repo, _ = _repo_and_hit()
    citation = replace(_citation(item), char_start=0, char_end=len(item.text) + 5)
    with pytest.raises(CitationError) as error:
        CitationValidator().validate(citation, repo, "rev-test")
    assert error.value.code == "BAD_SPAN"


def test_stale_revision_is_rejected():
    item, repo, _ = _repo_and_hit()
    with pytest.raises(CitationError) as error:
        CitationValidator().validate(_citation(item), repo, "older-revision")
    assert error.value.code == "STALE_REVISION"


def test_sender_and_time_mismatch_are_rejected():
    item, repo, _ = _repo_and_hit()
    with pytest.raises(CitationError) as error:
        CitationValidator().validate(replace(_citation(item), sender="别人"), repo, "rev-test")
    assert error.value.code == "SENDER_MISMATCH"

    with pytest.raises(CitationError) as error:
        CitationValidator().validate(replace(_citation(item), timestamp=ts(2020, 1, 1)), repo, "rev-test")
    assert error.value.code == "TIME_MISMATCH"


def test_claim_must_reference_existing_citation():
    item, repo, _ = _repo_and_hit()
    citation = _citation(item)
    answer = Answer(
        status="answered",
        claims=(Claim(text="测试", citation_ids=("c9",)),),
        citations=(citation,),
    )
    errors = CitationValidator().validate_answer(answer, repo, "rev-test")
    assert any(error.code == "UNKNOWN_CITATION" for error in errors)


def test_duplicate_citation_ids_are_rejected():
    item, repo, _ = _repo_and_hit()
    citation = _citation(item)
    answer = Answer(
        status="answered",
        claims=(Claim(text="测试", citation_ids=("c1",)),),
        citations=(citation, citation),
    )
    errors = CitationValidator().validate_answer(answer, repo, "rev-test")
    assert any(error.code == "DUPLICATE_CITATION" for error in errors)


def test_answer_to_dict_is_json_ready():
    item, repo, hit = _repo_and_hit()
    answer = ExtractiveAnswerBuilder(repo).build("报价", [hit])
    data = answer_to_dict(answer)
    assert data["status"] == "answered"
    assert data["citations"][0]["message_id"] == item.message_id


def test_answer_from_json_accepts_minimal_citation():
    item, repo, _ = _repo_and_hit()
    data = {
        "status": "answered",
        "claims": [{"text": "结论", "citation_ids": ["c1"]}],
        "citations": [
            {
                "citation_id": "c1",
                "message_id": item.message_id,
                "char_start": 0,
                "char_end": len(item.text),
                "quote": item.text,
            }
        ],
    }
    from original_words.llm.answer import answer_from_json

    answer = answer_from_json(data, repo, "rev-test")
    assert answer.status == "answered"
    assert answer.mode == "llm"
    assert CitationValidator().validate_answer(answer, repo, "rev-test") == []


def test_answer_from_json_rejects_bad_quote():
    item, repo, _ = _repo_and_hit()
    data = {
        "status": "answered",
        "claims": [{"text": "结论", "citation_ids": ["c1"]}],
        "citations": [
            {
                "citation_id": "c1",
                "message_id": item.message_id,
                "char_start": 0,
                "char_end": len(item.text),
                "quote": "错误的原文",
            }
        ],
    }
    from original_words.llm.answer import answer_from_json

    with pytest.raises(CitationError) as error:
        answer_from_json(data, repo, "rev-test")
    assert error.value.code == "QUOTE_MISMATCH"
