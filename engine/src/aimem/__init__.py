"""Reusable personal-memory retrieval engine.

Design rule: everything is a `Unit` (file, chunk, message, segment), so the
filesystem half and the chat half share one retrieval core.
"""

__version__ = "0.1.0"

from .models import QueryPlan, SearchResult, Unit  # noqa: F401
