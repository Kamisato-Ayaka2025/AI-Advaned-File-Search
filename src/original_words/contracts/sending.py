"""Exact-payload preview and grant records; DTOs do not authorize network I/O."""
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal
from urllib.parse import urlsplit

from .base import Contract, load_json, nonempty, require, to_json, unique, utc
from .common import ErrorInfo, ServiceFailure, SnapshotRef
from .search import EvidenceBundle


def evidence_digest(evidence: EvidenceBundle) -> str:
    return sha256(to_json(evidence).encode("utf-8")).hexdigest()



@dataclass(frozen=True, slots=True, repr=False)
class SendPlan(Contract):
    request_id: str
    purpose: Literal["query_parse", "investigation", "answer"]
    mode: Literal["full", "partial", "summary", "keywords"]
    payload_hash: str
    selected_message_ids: tuple[str, ...]
    preview_text: str
    model: str
    endpoint: str
    consent_scope: tuple[str, ...]
    snapshot: SnapshotRef = field(kw_only=True)
    evidence_digest: str = field(kw_only=True)

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.request_id, self.model, self.preview_text)
        require(len(self.evidence_digest) == 64
                and all(c in "0123456789abcdef" for c in self.evidence_digest),
                "invalid evidence digest")
        if self.purpose != "query_parse" and self.mode in {"partial", "keywords", "summary"}:
            require(bool(self.selected_message_ids), "evidence send requires selection")
        unique(self.selected_message_ids)
        unique(self.consent_scope)
        require(bool(self.consent_scope), "explicit consent scope is required")
        body = load_json(self.preview_text)
        # Preview is the exact UTF-8 JSON request body, including model and query.
        require(self.payload_hash == sha256(self.preview_text.encode("utf-8")).hexdigest(),
                "preview does not match payload digest")
        try:
            url = urlsplit(self.endpoint)
            valid = (url.scheme == "https" and url.hostname == "api.deepseek.com"
                     and url.port in (None, 443) and not url.username and not url.password
                     and not url.query and not url.fragment
                     and url.path in ("/chat/completions", "/v1/chat/completions"))
        except (ValueError, RecursionError):
            raise ValueError("invalid send request") from None
        require(valid, "unsupported DeepSeek endpoint")
        require(type(body) is dict and body.get("model") == self.model,
                "payload model differs from preview metadata")
        require(type(body.get("messages")) is list and bool(body["messages"]),
                "send payload requires messages")

    def validate_evidence(self, evidence: EvidenceBundle) -> None:
        """Call before consume/send; a mismatch must not consume the existing grant."""
        if self.snapshot != evidence.snapshot:
            raise ServiceFailure(ErrorInfo("REVISION_MISMATCH", "证据版本已变化，请重新预览"))
        if self.evidence_digest != evidence_digest(evidence):
            raise ServiceFailure(ErrorInfo("CONSENT_REQUIRED", "证据内容已变化，请重新预览"))
        selected = set(self.selected_message_ids)
        if (not selected <= set(evidence.message_ids)
                or not set(evidence.coverage.source_ids) <= set(self.consent_scope)
                or (self.mode == "full" and selected != set(evidence.message_ids))):
            raise ServiceFailure(ErrorInfo("CONSENT_REQUIRED", "发送范围与证据不一致"))
        if self.purpose == "query_parse" and (selected or evidence.message_ids):
            raise ServiceFailure(ErrorInfo("CONSENT_REQUIRED", "查询解析不得夹带消息证据"))

    @property
    def fingerprint(self) -> str:
        """Bind all metadata as well as exact bytes; never just the body hash."""
        return sha256(to_json(self).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class ConsentGrant(Contract):
    grant_id: str
    plan_fingerprint: str
    expires_at: str

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.grant_id)
        require(len(self.plan_fingerprint) == 64
                and all(c in "0123456789abcdef" for c in self.plan_fingerprint),
                "invalid plan fingerprint")
        utc(self.expires_at)
