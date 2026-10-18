from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def stable_id(*parts: str) -> str:
    """Deterministic short id, stable across runs and platforms."""
    raw = "\x1f".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:24]


@dataclass
class Unit:
    """The only retrieval unit the engine knows about.

    filesystem:  kind="file" (identity) and kind="chunk" (body)
    chat:        kind="message" (display) and kind="segment" (retrieval window)
    """

    id: str
    source: str  # fs | wechat | qq | jsonl | ...
    kind: str  # file | chunk | message | segment
    text: str = ""  # what FTS indexes (title + body)
    embed_text: str = ""  # what the embedder sees (may include context)
    title: str = ""
    parent_id: str | None = None
    scope: str | None = None  # directory root or conversation id
    acl: str = "*"  # "*" or JSON list of tags
    ts: float | None = None
    ts_end: float | None = None
    path: str | None = None
    ext: str = ""
    size: int | None = None
    aliases: str = ""  # pinyin / initials / alternative names
    meta: dict[str, Any] = field(default_factory=dict)

    def embed_source(self) -> str:
        return self.embed_text or self.text or self.title

    def meta_json(self) -> str:
        return json.dumps(self.meta, ensure_ascii=False, default=str)


@dataclass
class FileMeta:
    path: str
    name: str
    size: int | None = None
    mtime: float | None = None
    ext: str = ""


@dataclass
class QueryPlan:
    raw: str
    semantic: str = ""
    keywords: list[str] = field(default_factory=list)
    exts: list[str] = field(default_factory=list)
    ts_from: float | None = None
    ts_to: float | None = None
    size_min: int | None = None
    size_max: int | None = None
    sources: list[str] = field(default_factory=list)
    scope_prefix: str | None = None

    def has_time_filter(self) -> bool:
        return self.ts_from is not None or self.ts_to is not None


@dataclass
class SearchResult:
    unit: Unit
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    snippet: str = ""
    matched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        u = self.unit
        return {
            "id": u.id,
            "source": u.source,
            "kind": u.kind,
            "title": u.title,
            "path": u.path,
            "ext": u.ext,
            "size": u.size,
            "ts": u.ts,
            "scope": u.scope,
            "score": round(self.score, 6),
            "reasons": self.reasons,
            "snippet": self.snippet,
            "matched": self.matched,
        }
