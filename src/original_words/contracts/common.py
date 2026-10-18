"""Errors, progress and snapshot identities shared by all lanes."""
from dataclasses import dataclass
from typing import Literal

from .base import Contract, natural, nonempty, require

ErrorCode = Literal[
    "INVALID_INPUT", "UNSUPPORTED_FORMAT", "UNSUPPORTED_OPERATION", "PERMISSION_DENIED",
    "MODEL_UNAVAILABLE", "INDEX_NOT_READY", "CONSENT_REQUIRED", "RATE_LIMITED",
    "NETWORK_ERROR", "CANCELLED", "REVISION_MISMATCH", "INTERNAL_ERROR",
]


@dataclass(frozen=True, slots=True, repr=False)
class ErrorInfo(Contract):
    code: ErrorCode
    user_message: str
    retryable: bool = False
    task_id: str | None = None

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.user_message)


class ServiceFailure(Exception):
    """Services raise this with sanitized UI text; never wrap raw exceptions."""

    def __init__(self, error: ErrorInfo):
        self.error = error
        super().__init__(error.code)


@dataclass(frozen=True, slots=True, repr=False)
class SnapshotRef(Contract):
    dataset_revision: str
    index_revision: str

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.dataset_revision, self.index_revision)


@dataclass(frozen=True, slots=True, repr=False)
class TaskEvent(Contract):
    task_id: str
    request_id: str | None
    state: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    completed: int = 0
    total: int | None = None
    error: ErrorInfo | None = None
    seq: int = 0

    def __post_init__(self):
        Contract.__post_init__(self)
        nonempty(self.task_id)
        natural(self.completed)
        natural(self.seq)
        if self.total is not None:
            natural(self.total)
            require(self.completed <= self.total, "progress exceeds total")
        require((self.state == "failed") == (self.error is not None),
                "only failed task must carry an error")
        if self.state == "succeeded" and self.total is not None:
            require(self.completed == self.total, "success requires completed total")
