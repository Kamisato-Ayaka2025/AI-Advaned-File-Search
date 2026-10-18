"""过渡 DTO（仅 C 线 mock/UI 阶段使用）。

⚠️ 正式契约由 A 线在 `contracts/` 发布（Plan.md §2、§4.2，G1 前冻结）。
本模块是 C-01 阶段按 Plan §4.1 字段语义与 ADR-001 §6 的最小可运行镜像，
A 发布 contracts v1 后应整体替换为正式 DTO/Protocol，不得把本模块当作契约源。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# ---------------------------------------------------------------------------
# 错误与状态码（Plan §4.2 统一错误对象）


class ErrorCode(str, Enum):  # noqa: UP042 兼容 Python 3.10 开发环境
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    INDEX_NOT_READY = "INDEX_NOT_READY"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    CANCELLED = "CANCELLED"


class ServiceError(Exception):
    """统一错误对象：code/user_message/retryable/task_id（堆栈不得含原文/密钥）。"""

    def __init__(
        self,
        code: ErrorCode,
        user_message: str,
        retryable: bool = False,
        task_id: str | None = None,
    ) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.retryable = retryable
        self.task_id = task_id


class TaskState(str, Enum):  # noqa: UP042 兼容 Python 3.10 开发环境
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# 数据契约（Plan §4.1）


@dataclass(frozen=True)
class Chat:
    chat_id: str
    chat_name: str
    chat_type: str  # group / private
    source_id: str
    participants: tuple[str, ...] = ()


@dataclass(frozen=True)
class Message:
    message_id: str
    chat_id: str
    chat_type: str
    sender_id: str
    sender_name: str
    timestamp: datetime | None
    message_type: str  # text / image / file / system / recalled / unknown
    content: str
    quote_of: str | None = None
    attachment_ref: dict | None = None
    raw_payload: dict | None = None
    source_id: str = "demo"
    seq: int = 0
    timestamp_status: str = "known"  # known / unknown
    timestamp_precision: str | None = "minute"  # minute / day / None
    timestamp_source: str | None = "file"
    parse_status: str = "ok"


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_id: str
    chat_id: str
    message_ids: tuple[str, ...]
    start: int
    end: int
    participants: tuple[str, ...]
    text: str
    dataset_revision: int


@dataclass(frozen=True)
class ChatFilters:
    """硬过滤：来源/会话/发送者/时间/类型（时间范围为 [start, end)，未知时间不匹配）。"""

    chat_ids: tuple[str, ...] | None = None
    chat_types: tuple[str, ...] | None = None
    sender_names: tuple[str, ...] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    message_types: tuple[str, ...] | None = None

    def is_empty(self) -> bool:
        return (
            all(
                value in (None, ())
                for value in (
                    self.chat_ids,
                    self.chat_types,
                    self.sender_names,
                    self.message_types,
                )
            )
            and self.start_time is None
            and self.end_time is None
        )


@dataclass(frozen=True)
class ParsedQuery:
    """查询理解结果（ADR-001：硬过滤与软线索必须分开展示）。"""

    query: str
    intent: str
    hard_filters: ChatFilters
    soft_hints: tuple[str, ...] = ()
    confidence: float = 1.0


@dataclass(frozen=True)
class SearchRequest:
    request_id: str
    query: str
    filters: ChatFilters
    top_k: int = 10
    history_ref: str | None = None


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    message_ids: tuple[str, ...]
    score: float
    reasons: tuple[str, ...]
    index_revision: int


@dataclass(frozen=True)
class Citation:
    message_id: str
    sender_name: str
    timestamp: datetime | None
    chat_id: str
    chat_name: str
    text: str
    chunk_id: str


@dataclass(frozen=True)
class Claim:
    text: str
    citation_ids: tuple[str, ...]


@dataclass(frozen=True)
class Answer:
    status: str  # answered / no_evidence / partial
    claims: tuple[Claim, ...]
    citations: tuple[Citation, ...]
    timeline_message_ids: tuple[str, ...]
    mode: str  # demo / local / llm_sim
    elapsed_ms: int = 0
    calls: int = 0
    tokens: int = 0
    stop_reason: str | None = None
    coverage_note: str = ""


@dataclass(frozen=True)
class ImportManifest:
    adapter_id: str
    adapter_version: str
    upstream_tool: str | None
    upstream_version: str | None
    client_build: str | None
    export_schema: str
    account_scope: str | None
    exported_at: datetime | None
    snapshot_hash: str


@dataclass(frozen=True)
class ImportReport:
    manifest: ImportManifest
    source_count: int | None
    read_count: int
    imported_count: int
    duplicate_count: int
    rejected_count: int
    unknown_count: int
    attachment_missing_count: int
    completeness: str  # unknown / partial / verified_for_scope
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None


@dataclass(frozen=True)
class SendPlan:
    request_id: str
    purpose: str
    mode: str  # full / partial
    payload_hash: str
    selected_message_ids: tuple[str, ...]
    preview_text: str
    model: str
    endpoint: str
    consent_scope: str  # one_time / session

    @staticmethod
    def compute_hash(preview_text: str, model: str, endpoint: str) -> str:
        payload = "\x1f".join((preview_text, model, endpoint)).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ConsentGrant:
    request_id: str
    scope: str
    payload_hash: str
    granted_at: datetime
    revoked: bool = False


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    request_id: str | None
    state: TaskState
    completed: int | None = None
    total: int | None = None
    error: ServiceError | None = None
    detail: str = ""


@dataclass(frozen=True)
class TimelineNode:
    message_id: str
    chat_id: str
    chat_name: str
    sender_name: str
    timestamp: datetime | None
    snippet: str
    unknown_time: bool = False


@dataclass(frozen=True)
class ContextWindow:
    chat: Chat
    anchor_id: str
    messages: tuple[Message, ...]
    anchor_index: int
    clipped_start: bool
    clipped_end: bool


@dataclass
class DatasetInfo:
    kind: str  # demo / imported
    label: str
    chat_count: int
    message_count: int
    reports: list[ImportReport] = field(default_factory=list)
