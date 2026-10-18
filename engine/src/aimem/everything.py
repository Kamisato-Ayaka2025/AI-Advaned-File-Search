from __future__ import annotations

import datetime as dt
import os
from typing import Iterator

import requests

from .models import FileMeta
from .paths import ext_of, norm_sep

# Everything's HTTP server returns JSON with these (lowercase) keys:
#   {"totalResults": 12, "results": [
#       {"type":"file","name":"a.xlsx","path":"C:\\Users\\me\\",
#        "size":12345,"date_modified":"2025-10-12T15:30:00"}]}
# Exact keys vary a little between 1.4 / 1.5 and the plugin build, so parse
# defensively.


class EverythingError(RuntimeError):
    pass


def _as_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_ts(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[: len(fmt) + 2], fmt).timestamp()
        except ValueError:
            continue
    return None


def _join(path: str, name: str) -> str:
    if not path:
        return name
    if path.endswith(("\\", "/")):
        return path + name
    return path + "\\" + name


class EverythingClient:
    """Talk to a running Everything instance over its HTTP server.

    Enable it in Everything: Tools -> Options -> HTTP Server -> Enable.
    Bind to 127.0.0.1 if you do not want it exposed on the LAN.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 80, timeout: float = 3.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.base = f"http://{host}:{port}/"

    def probe(self) -> tuple[bool, str]:
        try:
            r = requests.get(
                self.base,
                params={"search": "", "json": 1, "count": 1},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            return False, f"无法连接 {self.base}: {exc}"
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        try:
            r.json()
        except ValueError:
            return False, "返回内容不是 JSON（HTTP 服务可能未启用）"
        return True, "ok"

    def search(self, query: str, limit: int = 500) -> list[FileMeta]:
        params = {
            "search": query,
            "json": 1,
            "count": int(limit),
            "path_column": 1,
            "size_column": 1,
            "date_modified_column": 1,
            "extension_column": 1,
        }
        try:
            r = requests.get(self.base, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise EverythingError(str(exc)) from exc
        if r.status_code != 200:
            raise EverythingError(f"HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError as exc:
            raise EverythingError("响应不是 JSON；请确认 Everything HTTP 服务已启用") from exc

        rows = data.get("results") or data.get("Results") or []
        out: list[FileMeta] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("Name") or ""
            folder = row.get("path") or row.get("Path") or ""
            full = row.get("full_path") or row.get("FullPath") or _join(folder, name)
            if not full:
                continue
            if row.get("type") in ("folder", "Folder"):
                continue
            out.append(
                FileMeta(
                    path=norm_sep(full).replace("/", "\\") if "\\" in folder else full,
                    name=name or norm_sep(full).rsplit("/", 1)[-1],
                    size=_as_int(row.get("size") or row.get("Size")),
                    mtime=_as_ts(row.get("date_modified") or row.get("DateModified")),
                    ext=ext_of(name),
                )
            )
        return out


# ---------------------------------------------------------------------------
# Local scanner: dev fallback on Linux/macOS and a non-Everything backend.
# ---------------------------------------------------------------------------

DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache", ".tox",
    "$recycle.bin", "system volume information", "windows", "winsxs",
    "programdata", "appdata", "library", ".gradle", ".conda", ".npm",
}

DEFAULT_EXCLUDE_SUBSTRINGS = (
    "/appdata/local/temp/",
    "/appdata/local/packages/",
    "/programdata/package cache/",
    "/windows/winsxs/",
    "/$recycle.bin/",
    "/node_modules/",
    "/.git/",
)


def _excluded_dir(name: str, path: str, include_hidden: bool) -> bool:
    low = name.lower()
    if not include_hidden and name.startswith("."):
        return True
    if low in DEFAULT_EXCLUDE_DIRS:
        return True
    p = norm_sep(path).lower() + "/"
    return any(s in p for s in DEFAULT_EXCLUDE_SUBSTRINGS)


def scan_local(
    root: str,
    *,
    max_files: int = 200_000,
    include_hidden: bool = False,
    exts: set[str] | None = None,
) -> Iterator[FileMeta]:
    root = os.path.abspath(os.path.expanduser(root))
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None, followlinks=False):
        dirnames[:] = [
            d for d in dirnames if not _excluded_dir(d, os.path.join(dirpath, d), include_hidden)
        ]
        for fn in filenames:
            if fn.startswith(".") and not include_hidden:
                continue
            p = os.path.join(dirpath, fn)
            e = ext_of(fn)
            if exts and e not in exts:
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not os.path.isfile(p):
                continue
            yield FileMeta(path=p, name=fn, size=st.st_size, mtime=st.st_mtime, ext=e)
            count += 1
            if count >= max_files:
                return
