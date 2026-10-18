"""Provisional local retrieval index for B-01 development and evaluation.

Production writes are owned by A: B is expected to produce FTS/vector update
packages and let ``IndexStore.publish`` commit them atomically.  This SQLite
implementation exists so B-01 can be built and tested before that interface
lands.  Do not point it at real chat data before G5; it stores plaintext text
and vectors.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from .chunking import (
    CHILD_OVERLAP,
    CHILD_SIZE,
    MAX_CHILD_TOKENS,
    PARENT_OVERLAP,
    PARENT_SIZE,
    build_chunks,
)
from .embedders import Embedder
from .text import tokenize
from .types import MessageRecord, SearchFilters
from .vectors import VectorStore

TOKENIZER_VERSION = "cjk-char-v1"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filter_clause(filters: SearchFilters | None, alias: str = "u") -> tuple[str, list[Any]]:
    if filters is None or filters.is_empty():
        return "", []
    clauses: list[str] = []
    params: list[Any] = []

    def placeholders(values: Sequence[str]) -> str:
        return ", ".join("?" for _ in values)

    if filters.sources:
        clauses.append(f"{alias}.source IN ({placeholders(filters.sources)})")
        params.extend(filters.sources)
    if filters.chat_ids:
        clauses.append(f"{alias}.chat_id IN ({placeholders(filters.chat_ids)})")
        params.extend(filters.chat_ids)
    if filters.chat_types:
        clauses.append(f"{alias}.chat_type IN ({placeholders(filters.chat_types)})")
        params.extend(filters.chat_types)
    if filters.time_start is not None:
        clauses.append(f"{alias}.ts_end IS NOT NULL AND {alias}.ts_end >= ?")
        params.append(filters.time_start)
    if filters.time_end is not None:
        clauses.append(f"{alias}.ts_start IS NOT NULL AND {alias}.ts_start < ?")
        params.append(filters.time_end)
    if filters.sender_ids:
        clauses.append(
            f"EXISTS (SELECT 1 FROM unit_senders s WHERE s.unit_id = {alias}.unit_id "
            f"AND s.sender_id IN ({placeholders(filters.sender_ids)}))"
        )
        params.extend(filters.sender_ids)
    if filters.message_types:
        clauses.append(
            f"EXISTS (SELECT 1 FROM unit_types t WHERE t.unit_id = {alias}.unit_id "
            f"AND t.type IN ({placeholders(filters.message_types)}))"
        )
        params.extend(filters.message_types)
    return " AND ".join(clauses), params


def _compute_revision(chunks: Sequence[Any], embedder_name: str) -> str:
    digest = hashlib.sha256()
    digest.update(TOKENIZER_VERSION.encode("utf-8"))
    digest.update(embedder_name.encode("utf-8"))
    for chunk in chunks:
        digest.update(chunk.chunk_id.encode("utf-8"))
    return digest.hexdigest()[:16]


class RetrievalIndex:
    def __init__(
        self,
        path: str | Path,
        *,
        embedder: Embedder | None = None,
        revision: str | None = None,
    ) -> None:
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.embedder = embedder
        self.revision = revision or "unbuilt"
        self._explicit_revision = revision is not None
        self._vectors = VectorStore()
        self._create_schema()

    # ------------------------------------------------------------------ schema
    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS units (
                unit_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                chat_title TEXT NOT NULL,
                chat_type TEXT NOT NULL,
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                embed_text TEXT NOT NULL,
                ts_start REAL,
                ts_end REAL,
                seq_start INTEGER NOT NULL,
                seq_end INTEGER NOT NULL,
                parent_id TEXT NOT NULL,
                message_ids TEXT NOT NULL,
                char_spans TEXT NOT NULL,
                index_revision TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS unit_senders (
                unit_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                PRIMARY KEY (unit_id, sender_id)
            );
            CREATE TABLE IF NOT EXISTS unit_types (
                unit_id TEXT NOT NULL,
                type TEXT NOT NULL,
                PRIMARY KEY (unit_id, type)
            );
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                chat_type TEXT NOT NULL,
                source TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                ts REAL,
                seq INTEGER NOT NULL,
                text TEXT NOT NULL,
                message_type TEXT NOT NULL,
                quote_of TEXT,
                attachments TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5(
                unit_id UNINDEXED,
                body,
                tokenize='unicode61 remove_diacritics 2'
            );
            CREATE INDEX IF NOT EXISTS idx_units_chat ON units(chat_id);
            CREATE INDEX IF NOT EXISTS idx_units_ts ON units(ts_start, ts_end);
            CREATE INDEX IF NOT EXISTS idx_messages_chat_seq ON messages(chat_id, seq);
            """
        )
        self.conn.commit()

    def reset(self) -> None:
        self.conn.executescript(
            """
            DROP TABLE IF EXISTS units_fts;
            DROP TABLE IF EXISTS units;
            DROP TABLE IF EXISTS unit_senders;
            DROP TABLE IF EXISTS unit_types;
            DROP TABLE IF EXISTS messages;
            DROP TABLE IF EXISTS meta;
            """
        )
        self._create_schema()
        self._vectors = VectorStore()
        self.revision = "unbuilt"
        self._explicit_revision = False

    def close(self) -> None:
        self.conn.close()

    @property
    def vector_count(self) -> int:
        return len(self._vectors)

    def get_index_revision(self) -> str:
        return self.revision

    # ------------------------------------------------------------------- build
    def build(
        self,
        messages: Sequence[MessageRecord],
        *,
        chat_titles: dict[str, str] | None = None,
        parent_size: int = PARENT_SIZE,
        parent_overlap: int = PARENT_OVERLAP,
        child_size: int = CHILD_SIZE,
        child_overlap: int = CHILD_OVERLAP,
        max_tokens: int = MAX_CHILD_TOKENS,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """Rebuild the whole index.  Incremental publish belongs to A's store."""
        explicit = revision
        if explicit is None and self._explicit_revision:
            explicit = self.revision
        chunks = build_chunks(
            messages,
            chat_titles=chat_titles,
            parent_size=parent_size,
            parent_overlap=parent_overlap,
            child_size=child_size,
            child_overlap=child_overlap,
            max_tokens=max_tokens,
        )
        self.reset()
        if explicit is not None:
            self.revision = explicit
            self._explicit_revision = True
        else:
            self.revision = _compute_revision(
                chunks,
                self.embedder.name if self.embedder else "none",
            )

        with self.conn:
            self._insert_messages(messages)
            for chunk in chunks:
                self._insert_chunk(chunk)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("index_revision", self.revision),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("embedder", self.embedder.name if self.embedder else "none"),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("tokenizer", TOKENIZER_VERSION),
            )

        if self.embedder is not None and chunks:
            vectors = self.embedder.encode_documents([chunk.embed_text for chunk in chunks])
            self._vectors.build([chunk.chunk_id for chunk in chunks], vectors)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("vector_dim", str(self._vectors.dim)),
            )
            self.conn.commit()

        return {
            "messages": len(messages),
            "chunks": len(chunks),
            "vectors": len(self._vectors),
            "index_revision": self.revision,
            "degraded": self.embedder is None,
        }

    def _insert_messages(self, messages: Iterable[MessageRecord]) -> None:
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO messages(
                message_id, chat_id, chat_type, source, sender_id, sender_name,
                ts, seq, text, message_type, quote_of, attachments
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    message.message_id,
                    message.chat_id,
                    message.chat_type,
                    message.source,
                    message.sender_id,
                    message.sender_name,
                    message.timestamp,
                    message.seq,
                    message.text,
                    message.message_type,
                    message.quote_of,
                    json.dumps(list(message.attachments), ensure_ascii=False),
                )
                for message in messages
            ],
        )

    def _insert_chunk(self, chunk: Any) -> None:
        body = tokenize(
            " ".join(
                [
                    chunk.text,
                    " ".join(chunk.sender_names),
                    chunk.chat_title,
                    " ".join(chunk.message_types),
                ]
            )
        )
        self.conn.execute(
            """
            INSERT INTO units(
                unit_id, kind, chat_id, chat_title, chat_type, source, text,
                embed_text, ts_start, ts_end, seq_start, seq_end, parent_id,
                message_ids, char_spans, index_revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk.chunk_id,
                "chunk",
                chunk.chat_id,
                chunk.chat_title,
                chunk.chat_type,
                chunk.source,
                chunk.text,
                chunk.embed_text,
                chunk.ts_start,
                chunk.ts_end,
                chunk.seq_start,
                chunk.seq_end,
                chunk.parent_id,
                json.dumps(list(chunk.message_ids), ensure_ascii=False),
                json.dumps([list(span) for span in chunk.char_spans], ensure_ascii=False),
                self.revision,
            ),
        )
        self.conn.execute(
            "INSERT INTO units_fts(unit_id, body) VALUES (?, ?)",
            (chunk.chunk_id, body),
        )
        self.conn.executemany(
            "INSERT OR IGNORE INTO unit_senders(unit_id, sender_id) VALUES (?, ?)",
            [(chunk.chunk_id, sender_id) for sender_id in chunk.sender_ids],
        )
        self.conn.executemany(
            "INSERT OR IGNORE INTO unit_types(unit_id, type) VALUES (?, ?)",
            [(chunk.chunk_id, message_type) for message_type in chunk.message_types],
        )

    # ------------------------------------------------------------------ search
    def search_fts(
        self,
        fts_query: str,
        *,
        limit: int = 80,
        filters: SearchFilters | None = None,
    ) -> list[str]:
        if not fts_query:
            return []
        where, params = _filter_clause(filters)
        sql = (
            "SELECT u.unit_id FROM units_fts "
            "JOIN units u ON u.unit_id = units_fts.unit_id "
            "WHERE units_fts MATCH ?"
        )
        if where:
            sql += f" AND {where}"
        sql += " ORDER BY bm25(units_fts) LIMIT ?"
        try:
            rows = self.conn.execute(sql, [fts_query, *params, limit]).fetchall()
        except sqlite3.OperationalError:
            # A malformed user query must degrade to "no lexical hit", not crash
            # the search request.
            return []
        return [row["unit_id"] for row in rows]

    def search_exact(
        self,
        entities: Sequence[str],
        *,
        limit: int = 80,
        filters: SearchFilters | None = None,
    ) -> list[str]:
        if not entities:
            return []
        where, params = _filter_clause(filters)
        scores: dict[str, int] = {}
        for entity in entities:
            sql = "SELECT u.unit_id FROM units u WHERE u.text LIKE ? ESCAPE '\\'"
            if where:
                sql += f" AND {where}"
            sql += " LIMIT ?"
            pattern = f"%{_escape_like(entity)}%"
            try:
                rows = self.conn.execute(sql, [pattern, *params, max(limit, 200)]).fetchall()
            except sqlite3.OperationalError:
                continue
            for row in rows:
                unit_id = row["unit_id"]
                scores[unit_id] = scores.get(unit_id, 0) + 1
        ordered = sorted(scores, key=lambda unit_id: (-scores[unit_id], unit_id))
        return ordered[:limit]

    def filtered_unit_ids(self, filters: SearchFilters | None) -> set[str] | None:
        if filters is None or filters.is_empty():
            return None
        where, params = _filter_clause(filters)
        sql = "SELECT u.unit_id FROM units u"
        if where:
            sql += f" WHERE {where}"
        return {row["unit_id"] for row in self.conn.execute(sql, params).fetchall()}

    def vector_search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 80,
        allowed: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        return self._vectors.search(query_vector, k=limit, allowed=allowed)

    # ------------------------------------------------------------------- reads
    def get_units(self, unit_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        ids = list(unit_ids)
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT * FROM units WHERE unit_id IN ({placeholders})", ids
        ).fetchall()
        return {row["unit_id"]: _unit_row(row) for row in rows}

    def get_messages(self, message_ids: Iterable[str]) -> list[MessageRecord]:
        ids = list(message_ids)
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT * FROM messages WHERE message_id IN ({placeholders})", ids
        ).fetchall()
        by_id = {row["message_id"]: _message_row(row) for row in rows}
        return [by_id[message_id] for message_id in ids if message_id in by_id]

    def get_message(self, message_id: str) -> MessageRecord | None:
        row = self.conn.execute(
            "SELECT * FROM messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return _message_row(row) if row else None

    def get_context(
        self,
        chat_id: str,
        seq_start: int,
        seq_end: int,
        *,
        before: int = 10,
        after: int = 10,
    ) -> list[MessageRecord]:
        before_rows = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE chat_id = ? AND seq < ?
            ORDER BY seq DESC LIMIT ?
            """,
            (chat_id, seq_start, max(0, before)),
        ).fetchall()
        middle_rows = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE chat_id = ? AND seq >= ? AND seq <= ?
            ORDER BY seq ASC
            """,
            (chat_id, seq_start, seq_end),
        ).fetchall()
        after_rows = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE chat_id = ? AND seq > ?
            ORDER BY seq ASC LIMIT ?
            """,
            (chat_id, seq_end, max(0, after)),
        ).fetchall()
        rows = list(reversed(before_rows)) + list(middle_rows) + list(after_rows)
        return [_message_row(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        counts = {}
        for table in ("units", "messages", "unit_senders", "unit_types"):
            counts[table] = self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        counts["vectors"] = len(self._vectors)
        counts["index_revision"] = self.revision
        counts["embedded"] = self.embedder is not None
        return counts


def _unit_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "unit_id": row["unit_id"],
        "kind": row["kind"],
        "chat_id": row["chat_id"],
        "chat_title": row["chat_title"],
        "chat_type": row["chat_type"],
        "source": row["source"],
        "text": row["text"],
        "embed_text": row["embed_text"],
        "ts_start": row["ts_start"],
        "ts_end": row["ts_end"],
        "seq_start": row["seq_start"],
        "seq_end": row["seq_end"],
        "parent_id": row["parent_id"],
        "message_ids": tuple(json.loads(row["message_ids"])),
        "char_spans": tuple(tuple(span) for span in json.loads(row["char_spans"])),
        "index_revision": row["index_revision"],
    }


def _message_row(row: sqlite3.Row) -> MessageRecord:
    return MessageRecord(
        message_id=row["message_id"],
        chat_id=row["chat_id"],
        chat_type=row["chat_type"],
        source=row["source"],
        sender_id=row["sender_id"],
        sender_name=row["sender_name"],
        timestamp=row["ts"],
        seq=row["seq"],
        text=row["text"],
        message_type=row["message_type"],
        quote_of=row["quote_of"],
        attachments=tuple(json.loads(row["attachments"])),
    )
