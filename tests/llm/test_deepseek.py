from __future__ import annotations

from dataclasses import replace

import pytest

from original_words.llm.deepseek import (
    Authorization,
    ConsentRequired,
    DeepSeekClient,
    InvalidResponse,
    ModelUnavailable,
    PermissionDenied,
    RateLimited,
    payload_hash,
    validate_answer_json,
    validate_query_json,
)


class FakeTransport:
    def __init__(self, response=None, error=None) -> None:
        self.response = response or {
            "choices": [{"message": {"content": '{"ok": true}'}}]
        }
        self.error = error
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def _client(transport, *, api_key="test-key", max_retries=0):
    return DeepSeekClient(
        api_key,
        transport=transport,
        max_retries=max_retries,
        sleep=lambda _seconds: None,
    )


def _plan(client):
    return client.prepare_send(
        "req-1",
        "answer",
        [{"role": "user", "content": "我们什么时候换的供应商？"}],
    )


def test_prepare_send_is_local_only():
    transport = FakeTransport()
    client = _client(transport)
    plan = _plan(client)
    assert transport.calls == []
    assert plan.payload_hash == payload_hash(plan.payload)
    assert "供应商" in plan.preview_text
    assert plan.model == "deepseek-flash"


def test_generate_requires_authorization():
    transport = FakeTransport()
    client = _client(transport)
    plan = _plan(client)
    with pytest.raises(ConsentRequired):
        client.generate(plan, None)
    assert transport.calls == []


def test_generate_rejects_wrong_payload_hash():
    transport = FakeTransport()
    client = _client(transport)
    plan = _plan(client)
    with pytest.raises(ConsentRequired):
        client.generate(plan, Authorization("wrong"))
    assert transport.calls == []


def test_generate_sends_once_with_valid_authorization():
    transport = FakeTransport()
    client = _client(transport)
    plan = _plan(client)
    response = client.generate(plan, Authorization(plan.payload_hash))
    assert response["choices"][0]["message"]["content"] == '{"ok": true}'
    assert len(transport.calls) == 1
    url, headers, payload, _timeout = transport.calls[0]
    assert url.endswith("/chat/completions")
    assert headers["Authorization"] == "Bearer test-key"
    assert payload["model"] == "deepseek-flash"


def test_chat_json_parses_model_content():
    transport = FakeTransport(
        {"choices": [{"message": {"content": '```json\n{"semantic": "报价"}\n```'}}]}
    )
    client = _client(transport)
    plan = _plan(client)
    assert client.chat_json(plan, Authorization(plan.payload_hash)) == {"semantic": "报价"}


def test_payload_tampering_is_rejected():
    transport = FakeTransport()
    client = _client(transport)
    plan = _plan(client)
    tampered = replace(plan, payload={**plan.payload, "temperature": 1.0})
    with pytest.raises(ConsentRequired):
        client.generate(tampered, Authorization(plan.payload_hash))
    assert transport.calls == []


def test_scope_mismatch_is_rejected():
    transport = FakeTransport()
    client = _client(transport)
    plan = _plan(client)
    with pytest.raises(ConsentRequired):
        client.generate(plan, Authorization(plan.payload_hash, scope="other"))
    assert transport.calls == []


def test_missing_api_key_is_model_unavailable():
    transport = FakeTransport()
    client = _client(transport, api_key=None)
    plan = _plan(client)
    with pytest.raises(ModelUnavailable):
        client.generate(plan, Authorization(plan.payload_hash))
    assert transport.calls == []


def test_retryable_error_is_retried():
    transport = FakeTransport(error=RateLimited())
    client = _client(transport, max_retries=1)
    plan = _plan(client)
    with pytest.raises(RateLimited):
        client.generate(plan, Authorization(plan.payload_hash))
    assert len(transport.calls) == 2


def test_non_retryable_error_is_not_retried():
    transport = FakeTransport(error=PermissionDenied())
    client = _client(transport, max_retries=2)
    plan = _plan(client)
    with pytest.raises(PermissionDenied):
        client.generate(plan, Authorization(plan.payload_hash))
    assert len(transport.calls) == 1


def test_validate_query_json():
    assert validate_query_json({"semantic": "报价", "keywords": []})["semantic"] == "报价"
    with pytest.raises(InvalidResponse):
        validate_query_json({"keywords": "not-a-list"})


def test_validate_answer_json_rejects_unknown_message():
    data = {
        "status": "answered",
        "claims": [{"text": "结论", "citation_ids": ["c1"]}],
        "citations": [
            {"citation_id": "c1", "message_id": "a2", "char_start": 0, "char_end": 1, "quote": "x"}
        ],
        "timeline": ["c1"],
    }
    with pytest.raises(InvalidResponse):
        validate_answer_json(data, ["a1"])


def test_validate_answer_json_accepts_valid_payload():
    data = {
        "status": "answered",
        "claims": [{"text": "结论", "citation_ids": ["c1"]}],
        "citations": [
            {"citation_id": "c1", "message_id": "a1", "char_start": 0, "char_end": 1, "quote": "x"}
        ],
        "timeline": ["c1"],
    }
    assert validate_answer_json(data, ["a1"])["status"] == "answered"


def test_prompt_builders_include_contract():
    query_messages = DeepSeekClient.build_query_request(
        "上周张经理说的报价",
        participants=["张经理"],
        chats=["设备采购群"],
        now="2025-10-15T12:00:00+08:00",
    )
    assert "JSON" in query_messages[0]["content"]
    assert "设备采购群" in query_messages[1]["content"]

    answer_messages = DeepSeekClient.build_answer_request(
        "报价",
        [{"message_id": "a1", "text": "新报价"}],
    )
    assert "a1" in answer_messages[1]["content"]
