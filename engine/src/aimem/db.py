from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import QueryPlan, Unit
from .text import build_fts_query, tokenize_cjk

SCHEMA_VERSION = 1

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS units (
  rid         INTEGER PRIMARY KEY,
  id          TEXT NOT NULL UNIQUE,
  source      TEXT NOT NULL,
  kind        TEXT NOT NULL,
  parent_id   TEXT,
  scope       TEXT,
  acl         TEXT NOT NULL DEFAULT '*',
  ts          REAL,
  ts_end      REAL,
  title       TEXT NOT NULL DEFAULT '',
  text        TEXT NOT NULL DEFAULT '',
  embed_text  TEXT NOT NULL DEFAULT '',
  path        TEXT,
  ext         TEXT NOT NULL DEFAULT '',
  size        INTEGER,
  aliases     TEXT NOT NULL DEFAULT '',
  meta        TEXT NOT NULL DEFAULT '{}',
  title_tok   TEXT NOT NULL DEFAULT '',
  text_tok    TEXT NOT NULL DEFAULT '',
  path_tok    TEXT NOT NULL DEFAULT '',
  aliases_tok TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_units_source ON units(source);
CREATE INDEX IF NOT EXISTS idx_units_scope  ON units(scope);
CREATE INDEX IF NOT EXISTS idx_units_ts     ON units(ts);
CREATE INDEX IF NOT EXISTS idx_units_parent ON units(parent_id);
CREATE INDEX IF NOT EXISTS idx_units_ext    ON units(ext);
CREATE INDEX IF NOT EXISTS idx_units_path   ON units(path);

CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5(
  title_tok, text_tok, path_tok, aliases_tok,
  content='units', content_rowid='rid',
  tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS units_ai AFTER INSERT ON units BEGIN
  INSERT INTO units_fts(rowid, title_tok, text_tok, path_tok, aliases_tok)
  VALUES (new.rid, new.title_tok, new.text_tok, new.path_tok, new.aliases_tok);
END;

CREATE TRIGGER IF NOT EXISTS units_ad AFTER DELETE ON units BEGIN
  INSERT INTO units_fts(units_fts, rowid, title_tok, text_tok, path_tok, aliases_tok)
  VALUES ('delete', old.rid, old.title_tok, old.text_tok, old.path_tok, old.aliases_tok);
END;

CREATE TRIGGER IF NOT EXISTS units_au AFTER UPDATE ON units BEGIN
  INSERT INTO units_fts(units_fts, rowid, title_tok, text_tok, path_tok, aliases_tok)
  VALUES ('delete', old.rid, old.title_tok, old.text_tok, old.path_tok, old.aliases_tok);
  INSERT INTO units_fts(rowid, title_tok, text_tok, path_tok, aliases_tok)
  VALUES (new.rid, new.title_tok, new.text_tok, new.path_tok, new.aliases_tok);
END;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS links (
  a_id    TEXT NOT NULL,
  b_id    TEXT NOT NULL,
  kind    TEXT NOT NULL,
  score   REAL NOT NULL DEFAULT 0,
  reasons TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (a_id, b_id, kind)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    return conn


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------

_UPSERT = """
INSERT INTO units (
  id, source, kind, parent_id, scope, acl, ts, ts_end, title, text, embed_text,
  path, ext, size, aliases, meta,
  title_tok, text_tok, path_tok, aliases_tok
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(id) DO UPDATE SET
  source=excluded.source, kind=excluded.kind, parent_id=excluded.parent_id,
  scope=excluded.scope, acl=excluded.acl, ts=excluded.ts, ts_end=excluded.ts_end,
  title=excluded.title, text=excluded.text, embed_text=excluded.embed_text,
  path=excluded.path, ext=excluded.ext, size=excluded.size,
  aliases=excluded.aliases, meta=excluded.meta,
  title_tok=excluded.title_tok, text_tok=excluded.text_tok,
  path_tok=excluded.path_tok, aliases_tok=excluded.aliases_tok
"""


def upsert_unit(conn: sqlite3.Connection, u: Unit) -> None:
    conn.execute(
        _UPSERT,
        (
            u.id,
            u.source,
            u.kind,
            u.parent_id,
            u.scope,
            u.acl,
            u.ts,
            u.ts_end,
            u.title or "",
            u.text or "",
            u.embed_text or "",
            u.path,
            u.ext or "",
            u.size,
            u.aliases or "",
            u.meta_json(),
            tokenize_cjk(u.title or ""),
            tokenize_cjk(u.text or ""),
            tokenize_cjk(u.path or ""),
            tokenize_cjk(u.aliases or ""),
        ),
    )


def upsert_units(conn: sqlite3.Connection, units: Iterable[Unit]) -> int:
    n = 0
    for u in units:
        upsert_unit(conn, u)
        n += 1
    return n


def row_to_unit(row: sqlite3.Row) -> Unit:
    try:
        meta = json.loads(row["meta"] or "{}")
    except json.JSONDecodeError:
        meta = {}
    return Unit(
        id=row["id"],
        source=row["source"],
        kind=row["kind"],
        parent_id=row["parent_id"],
        scope=row["scope"],
        acl=row["acl"],
        ts=row["ts"],
        ts_end=row["ts_end"],
        title=row["title"],
        text=row["text"],
        embed_text=row["embed_text"],
        path=row["path"],
        ext=row["ext"],
        size=row["size"],
        aliases=row["aliases"],
        meta=meta,
    )


def get_units(conn: sqlite3.Connection, ids: list[str]) -> dict[str, Unit]:
    if not ids:
        return {}
    out: dict[str, Unit] = {}
    # chunk the IN clause to stay under SQLite's variable limit
    for i in range(0, len(ids), 500):
        part = ids[i : i + 500]
        marks = ",".join("?" for _ in part)
        for row in conn.execute(f"SELECT * FROM units WHERE id IN ({marks})", part):
            u = row_to_unit(row)
            out[u.id] = u
    return out


def get_unit(conn: sqlite3.Connection, unit_id: str) -> Unit | None:
    row = conn.execute("SELECT * FROM units WHERE id=?", (unit_id,)).fetchone()
    return row_to_unit(row) if row else None


def existing_signature(conn: sqlite3.Connection, unit_id: str) -> tuple[float | None, int | None] | None:
    row = conn.execute("SELECT ts, size FROM units WHERE id=?", (unit_id,)).fetchone()
    if not row:
        return None
    return row["ts"], row["size"]


def delete_scope(conn: sqlite3.Connection, scope: str) -> int:
    cur = conn.execute("DELETE FROM units WHERE scope=?", (scope,))
    return cur.rowcount


def delete_units(conn: sqlite3.Connection, ids: Iterable[str]) -> int:
    n = 0
    for uid in ids:
        n += conn.execute("DELETE FROM units WHERE id=?", (uid,)).rowcount
    return n


# ---------------------------------------------------------------------------
# FTS search
# ---------------------------------------------------------------------------


def _append_filters(sql: list[str], params: list, plan: QueryPlan | None) -> None:
    if plan is None:
        return
    if plan.sources:
        marks = ",".join("?" for _ in plan.sources)
        sql.append(f"AND u.source IN ({marks})")
        params.extend(plan.sources)
    if plan.exts:
        marks = ",".join("?" for _ in plan.exts)
        sql.append(f"AND u.ext IN ({marks})")
        params.extend(plan.exts)
    if plan.ts_from is not None:
        sql.append("AND u.ts >= ?")
        params.append(plan.ts_from)
    if plan.ts_to is not None:
        sql.append("AND u.ts < ?")
        params.append(plan.ts_to)
    if plan.size_min is not None:
        sql.append("AND u.size >= ?")
        params.append(plan.size_min)
    if plan.size_max is not None:
        sql.append("AND u.size <= ?")
        params.append(plan.size_max)
    if plan.scope_prefix:
        sql.append("AND u.scope LIKE ?")
        params.append(plan.scope_prefix.rstrip("%") + "%")


def _run_fts(
    conn: sqlite3.Connection,
    fts_q: str,
    limit: int,
    plan: QueryPlan | None,
) -> list[tuple[str, float]]:
    # IMPORTANT: rank inside a subquery first, then join. Putting
    # `u.source IN (...)` next to MATCH makes SQLite pick a plan that
    # re-evaluates the match per row (observed: >15s on 111k units).
    inner = max(limit * 5, 1000)
    sql = [
        "SELECT u.id AS id, f.rank AS rank FROM (",
        "  SELECT rowid, bm25(units_fts) AS rank FROM units_fts",
        "  WHERE units_fts MATCH ? ORDER BY rank LIMIT ?",
        ") f JOIN units u ON u.rid = f.rowid",
        "WHERE 1=1",
    ]
    params: list = [fts_q, inner]
    _append_filters(sql, params, plan)
    sql.append("ORDER BY f.rank LIMIT ?")
    params.append(limit)
    try:
        rows = conn.execute(" ".join(sql), params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(r["id"], -float(r["rank"])) for r in rows]


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 200,
    plan: QueryPlan | None = None,
) -> list[tuple[str, float]]:
    """Strict AND first; fall back to bigram OR for long / fuzzy queries."""
    if not query.strip():
        return []
    strict_q = build_fts_query(query, "and")
    if strict_q:
        rows = _run_fts(conn, strict_q, limit, plan)
        if len(rows) >= 5:
            return rows
    loose_q = build_fts_query(query, "or")
    if not loose_q:
        return []
    rows = _run_fts(conn, loose_q, limit, plan)
    return rows


def search_like(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 50,
    plan: QueryPlan | None = None,
) -> list[tuple[str, float]]:
    """Substring fallback for Latin tokens (FTS only does prefix, not infix)."""
    import re

    tokens = re.findall(r"[A-Za-z0-9]{4,}", query)
    if not tokens:
        return []
    token = max(tokens, key=len)
    sql = ["SELECT u.id AS id FROM units u", "WHERE (u.title LIKE ? OR u.path LIKE ?)"]
    params: list = [f"%{token}%", f"%{token}%"]
    _append_filters(sql, params, plan)
    sql.append("LIMIT ?")
    params.append(limit)
    try:
        rows = conn.execute(" ".join(sql), params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(r["id"], 0.0) for r in rows]


def stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) c FROM units").fetchone()["c"]
    by_source = {
        r["source"]: r["c"]
        for r in conn.execute("SELECT source, COUNT(*) c FROM units GROUP BY source")
    }
    by_kind = {
        r["kind"]: r["c"]
        for r in conn.execute("SELECT kind, COUNT(*) c FROM units GROUP BY kind")
    }
    return {
        "units": total,
        "by_source": by_source,
        "by_kind": by_kind,
        "embedder": get_meta(conn, "embedder"),
        "dim": get_meta(conn, "dim"),
    }
