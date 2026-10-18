from __future__ import annotations

import os

from ..models import FileMeta, Unit, stable_id
from ..paths import basename_any, dirname_any, ext_of
from ..text import (
    chunk_text,
    date_label,
    extract_text,
    pinyin_aliases,
    size_label,
)


def _labels(meta: FileMeta, stem: str) -> tuple[str, str, str]:
    parent = basename_any(dirname_any(meta.path))
    grand = basename_any(dirname_any(dirname_any(meta.path)))
    ext = meta.ext or ext_of(meta.name or meta.path)
    aliases = pinyin_aliases(stem)
    lexical = " ".join(x for x in (stem, parent, grand, ext, aliases) if x)
    semantic = " | ".join(
        x
        for x in (stem, parent, grand, ext, size_label(meta.size), date_label(meta.mtime))
        if x
    )
    return lexical, semantic, aliases


def file_units(
    meta: FileMeta,
    scope: str,
    *,
    want_chunks: bool = True,
    want_text: bool = True,
    max_chars: int = 4000,
    max_chunks: int = 12,
) -> list[Unit]:
    """Build the `file` unit plus optional `chunk` units for one file."""
    name = meta.name or basename_any(meta.path)
    stem = name.rsplit(".", 1)[0] if "." in name else name
    ext = meta.ext or ext_of(name)
    file_id = stable_id("fs", meta.path)
    lexical, semantic, aliases = _labels(meta, stem)

    units = [
        Unit(
            id=file_id,
            source="fs",
            kind="file",
            title=stem,
            text=lexical,
            embed_text=semantic,
            path=meta.path,
            ext=ext,
            size=meta.size,
            ts=meta.mtime,
            scope=scope,
            aliases=aliases,
            meta={"name": name, "mtime": meta.mtime, "size": meta.size},
        )
    ]

    if want_chunks and want_text and os.path.exists(meta.path):
        body = extract_text(meta.path, max_chars=max_chars)
        for i, chunk in enumerate(chunk_text(body, max_chunks=max_chunks)):
            units.append(
                Unit(
                    id=stable_id("fs", meta.path, "chunk", str(i)),
                    source="fs",
                    kind="chunk",
                    parent_id=file_id,
                    title=f"{stem} #{i + 1}",
                    text=f"{stem} {chunk}",
                    embed_text=f"{stem} | {chunk}",
                    path=meta.path,
                    ext=ext,
                    size=meta.size,
                    ts=meta.mtime,
                    scope=scope,
                    aliases=aliases,
                    meta={"chunk": i, "name": name},
                )
            )
    return units


def unit_from_path(path: str, *, scope: str | None = None, size: int | None = None,
                   mtime: float | None = None) -> Unit:
    """Synthetic unit for a file found by Everything but not indexed yet."""
    name = basename_any(path)
    stem = name.rsplit(".", 1)[0] if "." in name else name
    ext = ext_of(name)
    lexical, semantic, aliases = _labels(
        FileMeta(path=path, name=name, size=size, mtime=mtime, ext=ext), stem
    )
    return Unit(
        id=stable_id("fs", path),
        source="fs",
        kind="file",
        title=stem,
        text=lexical,
        embed_text=semantic,
        path=path,
        ext=ext,
        size=size,
        ts=mtime,
        scope=scope or dirname_any(path),
        aliases=aliases,
        meta={"unindexed": True},
    )
