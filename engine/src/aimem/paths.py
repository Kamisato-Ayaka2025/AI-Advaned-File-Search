from __future__ import annotations


def norm_sep(p: str | None) -> str:
    return (p or "").replace("\\", "/")


def basename_any(p: str | None) -> str:
    s = norm_sep(p).rstrip("/")
    return s.rsplit("/", 1)[-1] if s else ""


def dirname_any(p: str | None) -> str:
    s = norm_sep(p).rstrip("/")
    return s.rsplit("/", 1)[0] if "/" in s else ""


def ext_of(name: str) -> str:
    name = basename_any(name)
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def path_depth(p: str | None) -> int:
    return len([x for x in norm_sep(p).split("/") if x])
