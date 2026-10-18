from __future__ import annotations

import os
from dataclasses import dataclass, field

from .. import db
from ..embedders import Embedder
from ..everything import scan_local
from ..ingest.fs import file_units
from ..models import Unit, stable_id
from ..vectors import VectorStore


@dataclass
class IndexStats:
    scanned: int = 0
    changed: int = 0
    skipped: int = 0
    units: int = 0
    chunks: int = 0
    embedded: int = 0
    deleted: int = 0
    per_root: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"scanned={self.scanned} changed={self.changed} skipped={self.skipped} "
            f"units={self.units} chunks={self.chunks} embedded={self.embedded} "
            f"deleted={self.deleted}"
        )


class Indexer:
    def __init__(
        self,
        conn,
        store: VectorStore | None,
        embedder: Embedder | None = None,
        *,
        batch_size: int = 32,
        verbose: bool = True,
    ) -> None:
        self.conn = conn
        self.store = store
        self.embedder = embedder
        self.batch_size = batch_size
        self.verbose = verbose
        if embedder is not None:
            db.set_meta(conn, "embedder", embedder.name)
            db.set_meta(conn, "dim", str(embedder.dim))

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    def _embed(self, units: list[Unit], *, force: bool = True) -> int:
        if self.embedder is None or self.store is None or not units:
            return 0
        todo = [u for u in units if u.embed_source().strip()]
        if not force:
            todo = [u for u in todo if u.id not in self.store.id_to_row]
        if not todo:
            return 0
        done = 0
        for i in range(0, len(todo), 256):
            batch = todo[i : i + 256]
            texts = [u.embed_source() for u in batch]
            vecs = self.embedder.encode_documents(texts, batch_size=self.batch_size)
            self.store.add([u.id for u in batch], vecs)
            done += len(batch)
            self._log(f"  embedded {done}/{len(todo)}")
        self.store.save()
        return done

    # -- generic entry point (files, messages, anything) --------------------
    def index_units(self, units: list[Unit], *, force_embed: bool = True) -> IndexStats:
        stats = IndexStats(units=len(units))
        if not units:
            return stats

        import hashlib

        # Snapshot old content hashes BEFORE upsert: a re-export may keep the same
        # message id but change its text (e.g. OCR captions added). Those units
        # must be re-embedded, otherwise semantic search keeps stale vectors.
        old: dict[str, tuple[str | None, bool]] = {}
        if not force_embed:
            for u in units:
                prev = db.get_unit(self.conn, u.id)
                old[u.id] = (
                    prev.meta.get("h") if prev else None,
                    self.store is not None and u.id in self.store.id_to_row,
                )

        for u in units:
            u.meta["h"] = hashlib.sha1(
                u.embed_source().encode("utf-8", "ignore")
            ).hexdigest()[:12]

        with self.conn:
            db.upsert_units(self.conn, units)

        todo = units
        if not force_embed:
            todo = [
                u
                for u in units
                if (not old.get(u.id, (None, False))[1])
                or old.get(u.id, (None, False))[0] != u.meta["h"]
            ]
        stats.embedded = self._embed(todo, force=True)
        return stats

    # -- filesystem ---------------------------------------------------------
    def index_files(
        self,
        roots: list[str],
        *,
        force: bool = False,
        want_chunks: bool = True,
        want_text: bool = True,
        max_files: int = 200_000,
        max_chars: int = 4000,
        max_chunks: int = 12,
    ) -> IndexStats:
        stats = IndexStats()
        new_units: list[Unit] = []
        seen_by_scope: dict[str, tuple[set[str], bool]] = {}

        for root in roots:
            scope = os.path.abspath(os.path.expanduser(root))
            seen: set[str] = set()
            count = 0
            self._log(f"[index] scanning {scope}")
            for meta in scan_local(scope, max_files=max_files):
                count += 1
                stats.scanned += 1
                fid = stable_id("fs", meta.path)
                seen.add(fid)
                sig = db.existing_signature(self.conn, fid)
                if not force and sig is not None and sig == (meta.mtime, meta.size):
                    stats.skipped += 1
                    continue
                units = file_units(
                    meta,
                    scope,
                    want_chunks=want_chunks,
                    want_text=want_text,
                    max_chars=max_chars,
                    max_chunks=max_chunks,
                )
                new_units.extend(units)
                stats.chunks += sum(1 for u in units if u.kind == "chunk")
                stats.changed += 1
            full_scan = count < max_files
            seen_by_scope[scope] = (seen, full_scan)
            stats.per_root[scope] = count
            self._log(f"[index] {scope}: scanned={count} new_units={len(new_units)}")

        # remove files that disappeared (only for complete scans)
        stale: list[str] = []
        for scope, (seen, full) in seen_by_scope.items():
            if not full:
                continue
            rows = self.conn.execute(
                "SELECT id, parent_id FROM units WHERE source='fs' AND scope=?", (scope,)
            ).fetchall()
            for r in rows:
                base = r["parent_id"] or r["id"]
                if base not in seen:
                    stale.append(r["id"])
        if stale:
            with self.conn:
                stats.deleted = db.delete_units(self.conn, stale)
            self._log(f"[index] deleted {stats.deleted} stale units")

        if new_units:
            with self.conn:
                db.upsert_units(self.conn, new_units)
            stats.units = len(new_units)
            stats.embedded = self._embed(new_units, force=True)
        self._log(f"[index] done: {stats.summary()}")
        return stats
