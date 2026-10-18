"""DeepSeek adapter with an explicit send plan and consent check.

B owns the request/response shape; A owns the consent service.  This module
therefore never reads an API key from disk and never sends without an
authorization object whose payload hash matches the exact outbound body.
``prepare_send`` is local-only; ``generate`` is the only method that can leave
the machine.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Sequence

DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-flash"


class LLMError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ConsentRequired(LLMError):
    def __init__(self, message: str = "sending requires a matching user authorization") -> None:
        super().__init__("CONSENT_REQUIRED", message)


class ModelUnavailable(LLMError):
    def __init__(self, message: str = "DeepSeek is not configured or unavailable") -> None:
        super().__init__("MODEL_UNAVAILABLE", message)


class InvalidResponse(LLMError):
    def __init__(self, message: str = "model returned an invalid response") -> None:
        super().__init__("INVALID_RESPONSE", message)


class NetworkError(LLMError):
    def __init__(self, message: str = "network error", *, retryable: bool = True) -> None:
        super().__init__("NETWORK_ERROR", message, retryable=retryable)


class RateLimited(LLMError):
    def __init__(self, message: str = "rate limited") -> None:
        super().__init__("RATE_LIMITED", message, retryable=True)


class PermissionDenied(LLMError):
    def __init__(self, message: str = "permission denied") -> None:
        super().__init__("PERMISSION_DENIED", message)


@dataclass(frozen=True, slots=True)
class Authorization:
    """A's consent service hands this to B after the user approves a preview."""

    payload_hash: str
    approved: bool = True
    scope: str = "deepseek"


@dataclass(frozen=True, slots=True)
class SendPlan:
    request_id: str
    purpose: str
    payload: dict[str, Any]
    payload_hash: str
    preview_text: str
    model: str
    endpoint: str
    selected_message_ids: tuple[str, ...] = ()
    consent_scope: str = "deepseek"
    mode: str = "full"


def payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.transport = transport
        self._sleep = sleep

    # ---------------------------------------------------------------- planning
    def prepare_send(
        self,
        request_id: str,
        purpose: str,
        messages: Sequence[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = True,
        selected_message_ids: Sequence[str] = (),
        mode: str = "full",
        consent_scope: str = "deepseek",
    ) -> SendPlan:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        digest = payload_hash(payload)
        preview = json.dumps(payload["messages"], ensure_ascii=False, indent=2)
        return SendPlan(
            request_id=request_id,
            purpose=purpose,
            payload=payload,
            payload_hash=digest,
            preview_text=preview,
            model=str(payload["model"]),
            endpoint=self.endpoint,
            selected_message_ids=tuple(selected_message_ids),
            consent_scope=consent_scope,
            mode=mode,
        )

    # ------------------------------------------------------------------ send
    def generate(
        self,
        plan: SendPlan,
        authorization: Authorization | None,
        *,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        self._check_authorization(plan, authorization)
        if not self.api_key:
            raise ModelUnavailable()
        retries = self.max_retries if max_retries is None else max(0, max_retries)
        last_error: LLMError | None = None
        for attempt in range(retries + 1):
            try:
                if self.transport is not None:
                    response = self.transport(self.endpoint, self._headers(), plan.payload, self.timeout)
                else:
                    response = self._http_post(plan.payload)
                if not isinstance(response, dict):
                    raise InvalidResponse()
                return response
            except LLMError as error:
                last_error = error
                if not error.retryable or attempt >= retries:
                    raise
                self._sleep(min(0.5 * (2**attempt), 4.0))
        raise last_error or NetworkError()

    def chat_json(self, plan: SendPlan, authorization: Authorization | None) -> dict[str, Any]:
        response = self.generate(plan, authorization)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise InvalidResponse() from error
        if not isinstance(content, str):
            raise InvalidResponse()
        return _parse_json_content(content)

    # ------------------------------------------------------------------ prompts
    @staticmethod
    def build_query_request(
        query: str,
        *,
        participants: Sequence[str] = (),
        chats: Sequence[str] = (),
        now: str | None = None,
    ) -> list[dict[str, str]]:
        schema = (
            '{"semantic":"...", "keywords":["..."], '
            '"filters":{"sources":[],"chat_ids":[],"sender_ids":[],'
            '"message_types":[],"time_start":null,"time_end":null}, '
            '"soft_hints":{},"intent":"search"}'
        )
        system = (
            "你是聊天记录检索的查询解析器。只输出一个 JSON 对象，不要 Markdown。"
            "显式账号/会话/人物/日期是硬过滤；带“好像/可能/大概/左右”的猜测只能放进 soft_hints。"
            "时间边界使用 ISO-8601 且带 +08:00。无法确定的字段留空数组或 null。"
        )
        user = (
            f"当前时间：{now or ''}\n"
            f"已知参与者：{', '.join(participants) if participants else '（无）'}\n"
            f"已知会话：{', '.join(chats) if chats else '（无）'}\n"
            f"用户查询：{query}\n"
            f"输出 JSON schema：{schema}"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    @staticmethod
    def build_answer_request(query: str, evidence: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
        schema = (
            '{"status":"answered|partial|not_found|ambiguous",'
            '"claims":[{"text":"...","citation_ids":["c1"]}],'
            '"citations":[{"citation_id":"c1","message_id":"...","char_start":0,'
            '"char_end":10,"quote":"原文"}],'
            '"timeline":["c1"]}'
        )
        system = (
            "你是“原话考古”的回答器。只能使用给定 evidence 中的 message_id 和原文。"
            "每个 claim 必须绑定至少一个 citation；没有足够证据时 status=not_found，"
            "不要编造解决方案、时间或发送者。冲突证据同时保留。只输出 JSON。"
        )
        user = (
            f"用户问题：{query}\n"
            f"证据：{json.dumps(list(evidence), ensure_ascii=False)}\n"
            f"输出 JSON schema：{schema}"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ------------------------------------------------------------------ helpers
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key or ''}",
        }

    def _http_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise PermissionDenied() from error
            if error.code == 429:
                raise RateLimited() from error
            if error.code == 400:
                raise LLMError("INVALID_INPUT", "request rejected by provider") from error
            raise NetworkError(f"provider returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise NetworkError() from error
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise InvalidResponse() from error
        if not isinstance(data, dict):
            raise InvalidResponse()
        return data

    @staticmethod
    def _check_authorization(plan: SendPlan, authorization: Authorization | None) -> None:
        if authorization is None or not authorization.approved:
            raise ConsentRequired()
        actual = payload_hash(plan.payload)
        if actual != plan.payload_hash:
            raise ConsentRequired("the outbound payload changed after preview")
        if authorization.payload_hash != plan.payload_hash:
            raise ConsentRequired("authorization does not match this payload")
        if authorization.scope not in {"deepseek", plan.consent_scope, plan.purpose}:
            raise ConsentRequired("authorization scope does not cover this request")


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise InvalidResponse()
    try:
        data = json.loads(text[start : end + 1])
    except ValueError as error:
        raise InvalidResponse() from error
    if not isinstance(data, dict):
        raise InvalidResponse()
    return data


def validate_query_json(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise InvalidResponse("query response is not an object")
    filters = data.get("filters")
    if filters is not None and not isinstance(filters, dict):
        raise InvalidResponse("filters must be an object")
    keywords = data.get("keywords")
    if keywords is not None and not isinstance(keywords, list):
        raise InvalidResponse("keywords must be a list")
    return data


def validate_answer_json(data: dict[str, Any], allowed_message_ids: Sequence[str]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise InvalidResponse("answer response is not an object")
    if data.get("status") not in {"answered", "partial", "not_found", "ambiguous"}:
        raise InvalidResponse("invalid answer status")
    allowed = set(allowed_message_ids)
    citations = data.get("citations") or []
    if not isinstance(citations, list):
        raise InvalidResponse("citations must be a list")
    citation_ids: set[str] = set()
    for citation in citations:
        if not isinstance(citation, dict):
            raise InvalidResponse("citation must be an object")
        message_id = citation.get("message_id")
        if message_id not in allowed:
            raise InvalidResponse("citation references a message outside the evidence bundle")
        start, end = citation.get("char_start"), citation.get("char_end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            raise InvalidResponse("invalid citation character span")
        if not isinstance(citation.get("quote"), str):
            raise InvalidResponse("citation quote must be a string")
        citation_id = str(citation.get("citation_id") or message_id)
        if citation_id in citation_ids:
            raise InvalidResponse("duplicate citation id")
        citation_ids.add(citation_id)

    claims = data.get("claims") or []
    if not isinstance(claims, list):
        raise InvalidResponse("claims must be a list")
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
            raise InvalidResponse("claim must have text")
        references = claim.get("citation_ids") or []
        if not isinstance(references, list) or any(str(ref) not in citation_ids for ref in references):
            raise InvalidResponse("claim references an unknown citation")
    if data["status"] == "answered" and not claims:
        raise InvalidResponse("answered status requires at least one claim")
    return data
