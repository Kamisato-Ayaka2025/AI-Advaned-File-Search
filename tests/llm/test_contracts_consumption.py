from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256

import pytest

from original_words.contracts.answers import Answer as ContractAnswer
from original_words.contracts.common import ServiceFailure, SnapshotRef
from original_words.contracts.data import CharSpan, Coverage
from original_words.contracts.search import EvidenceBundle
from original_words.contracts.sending import ConsentGrant, SendPlan as ContractSendPlan
from original_words.contracts.validation import validate_answer
from original_words.llm.answer import ExtractiveAnswerBuilder
from original_words.llm.contracts_bridge import (
    to_contract_answer,
    to_contract_send_plan,
)
from original_words.llm.deepseek import DeepSeekClient
from original_words.retrieval import SearchResponse
from original_words.retrieval.contracts_bridge import to_contract_evidence, to_contract_message

from .support import DictRepository, make_hit, message

SNAPSHOT = SnapshotRef("data-1", "index-1")


class FakeTransport:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        return {"choices": [{"message": {"content": '{"status":"not_found"}'}}]}


def _evidence() -> EvidenceBundle:
    return EvidenceBundle(
        snapshot=SNAPSHOT,
        message_ids=("a1",),
        coverage=Coverage(("qq",)),
    )


def test_send_plan_meets_exact_preview_contract():
    transport = FakeTransport()
    client = DeepSeekClient("test-key", transport=transport)
    plan = client.prepare_send(
        "req-1",
        "answer",
        [{"role": "user", "content": "我们什么时候换的供应商？"}],
        selected_message_ids=("a1",),
    )
    contract_plan = to_contract_send_plan(plan, snapshot=SNAPSHOT, evidence=_evidence())

    assert contract_plan.preview_text == plan.preview_text
    assert contract_plan.payload_hash == sha256(contract_plan.preview_text.encode("utf-8")).hexdigest()
    assert json.loads(contract_plan.preview_text)["model"] == "deepseek-flash"
    assert contract_plan.fingerprint
    assert transport.calls == []


def test_contract_send_plan_rejects_non_deepseek_endpoint():
    client = DeepSeekClient("test-key", endpoint="https://api.deepseek.com/chat/completions")
    plan = client.prepare_send("req-2", "answer", [{"role": "user", "content": "x"}])
    bad = replace(plan, endpoint="http://127.0.0.1:8080/chat/completions")
    with pytest.raises(ValueError):
        to_contract_send_plan(bad, snapshot=SNAPSHOT, evidence=_evidence())


def test_interior_answer_converts_to_contract_answer_and_validates():
    item = message()
    repo = DictRepository([item], revision="index-1")
    hit = make_hit(item, index_revision="index-1")
    response = SearchResponse(hits=(hit,), index_revision="index-1")
    internal = ExtractiveAnswerBuilder(repo).build("报价", response)
    evidence = to_contract_evidence(response, SNAPSHOT, ("qq",))
    assert evidence.message_ids == ("a1",)

    answer = to_contract_answer(internal, SNAPSHOT, request_id="req-2")
    contract_message = to_contract_message(item)
    validate_answer(answer, evidence, (contract_message,), ("qq",))
    assert answer.status == "answered"
    assert answer.mode == "local"
    citation = answer.citations[0]
    assert citation.snapshot == SNAPSHOT
    assert citation.char_span is not None
    assert not hasattr(citation, "quote")
    assert not hasattr(citation, "sender")


def test_not_found_answer_has_no_invented_evidence():
    repo = DictRepository([], revision="index-1")
    internal = ExtractiveAnswerBuilder(repo).build("没有证据", SearchResponse((), "index-1"))
    answer = to_contract_answer(internal, SNAPSHOT, request_id="req-2")
    assert answer.status == "not_found"
    assert answer.claims == ()
    assert answer.citations == ()
    assert answer.timeline == ()


def test_contract_grant_binds_plan_fingerprint():
    client = DeepSeekClient("test-key")
    plan = to_contract_send_plan(
        client.prepare_send("req-3", "answer", [{"role": "user", "content": "x"}]),
        snapshot=SNAPSHOT,
        evidence=_evidence(),
    )
    grant = ConsentGrant("grant-1", plan.fingerprint, "2026-12-01T00:00:00Z")
    assert grant.plan_fingerprint == plan.fingerprint
    edited = replace(plan, purpose="investigation")
    assert grant.plan_fingerprint != edited.fingerprint


def test_answer_requires_request_id_and_ambiguous_clarification():
    fields = ContractAnswer.__dataclass_fields__
    assert "request_id" in fields
    assert "clarification" in fields
    with pytest.raises(ValueError):
        ContractAnswer("ambiguous", request_id="r-1")
    answer = ContractAnswer("ambiguous", request_id="r-1", clarification="你是指哪一次？")
    assert answer.clarification


def test_send_plan_binds_snapshot_and_evidence_digest():
    client = DeepSeekClient("test-key")
    plan = to_contract_send_plan(
        client.prepare_send("req-4", "answer", [{"role": "user", "content": "x"}],
                            selected_message_ids=("a1",)),
        snapshot=SNAPSHOT,
        evidence=_evidence(),
    )
    fields = ContractSendPlan.__dataclass_fields__
    assert "snapshot" in fields
    assert "evidence_digest" in fields
    plan.validate_evidence(_evidence())
    other = EvidenceBundle(
        snapshot=SnapshotRef("data-2", "index-1"),
        message_ids=("a1",),
        coverage=Coverage(("qq",)),
    )
    with pytest.raises(ServiceFailure) as revision:
        plan.validate_evidence(other)
    assert revision.value.error.code == "REVISION_MISMATCH"

    same_snapshot_different_evidence = EvidenceBundle(
        snapshot=SNAPSHOT,
        message_ids=("a1",),
        char_spans=(CharSpan("a1", 0, 1),),
        coverage=Coverage(("qq",)),
    )
    with pytest.raises(ServiceFailure) as consent:
        plan.validate_evidence(same_snapshot_different_evidence)
    assert consent.value.error.code == "CONSENT_REQUIRED"
