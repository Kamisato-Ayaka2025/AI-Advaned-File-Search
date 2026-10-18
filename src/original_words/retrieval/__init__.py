"""B-owned retrieval core (hybrid recall, context, evaluation)."""

from .chunking import build_chunks, split_text_by_tokens
from .context import ContextExpander
from .embedders import (
    Embedder,
    FastEmbedEmbedder,
    HashingEmbedder,
    SentenceTransformerEmbedder,
    make_embedder,
)
from .evaluate import evaluate, format_report, load_gold
from .hybrid import HybridSearcher, rrf_fuse
from .index import RetrievalIndex
from .types import (
    ChunkRecord,
    MessageRecord,
    MessageRepository,
    SearchFilters,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from .vectors import VectorStore

__all__ = [
    "ChunkRecord",
    "ContextExpander",
    "Embedder",
    "FastEmbedEmbedder",
    "HashingEmbedder",
    "HybridSearcher",
    "MessageRecord",
    "MessageRepository",
    "RetrievalIndex",
    "SearchFilters",
    "SearchHit",
    "SearchRequest",
    "SearchResponse",
    "SentenceTransformerEmbedder",
    "VectorStore",
    "build_chunks",
    "evaluate",
    "format_report",
    "load_gold",
    "make_embedder",
    "rrf_fuse",
    "split_text_by_tokens",
]
