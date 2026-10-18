"""B-owned LLM boundary: query parsing, DeepSeek adapter, answer validation."""

from .answer import (
    Answer,
    Citation,
    CitationError,
    CitationValidator,
    Claim,
    ExtractiveAnswerBuilder,
    answer_from_json,
    answer_to_dict,
    merge_timeline,
)
from .deepseek import (
    Authorization,
    ConsentRequired,
    DeepSeekClient,
    InvalidResponse,
    LLMError,
    ModelUnavailable,
    SendPlan,
    payload_hash,
    validate_answer_json,
    validate_query_json,
)
from .query import QuerySpec, RuleQueryParser

__all__ = [
    "Answer",
    "Authorization",
    "Citation",
    "CitationError",
    "CitationValidator",
    "Claim",
    "ConsentRequired",
    "DeepSeekClient",
    "ExtractiveAnswerBuilder",
    "InvalidResponse",
    "LLMError",
    "ModelUnavailable",
    "QuerySpec",
    "RuleQueryParser",
    "SendPlan",
    "answer_from_json",
    "answer_to_dict",
    "merge_timeline",
    "payload_hash",
    "validate_answer_json",
    "validate_query_json",
]
