#!/usr/bin/env python3
"""Validate an export directory against the aimem Markdown contract (FORMAT.md)."""
import re, sys, pathlib

DATE = re.compile(r"^## (\d{4}-\d{2}-\d{2})$")
HEAD = re.compile(r"^\*\*(\d{2}:\d{2}:\d{2}) · (.+)\*\*$")
MEDIA = re.compile(r"^> (!\[图片\]\(<[^>]+>\)|📎 \[[^\]]+\]\(<[^>]+>\))")


def check_file(p: pathlib.Path):
    errs = []
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        errs.append("1: BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ["1: not UTF-8"]
    lines = [ln.rstrip("\r") for ln in text.split("\n")]

    # rule 2: YAML front matter
    if not lines or lines[0] != "---":
        errs.append("2: no front matter")
    else:
        try:
            end = lines.index("---", 1)
        except ValueError:
            end = -1
        if end < 0:
            errs.append("2: unterminated front matter")
        else:
            fm = "\n".join(lines[1:end])
            for key in ("platform:", "conversation:"):
                if key not in fm:
                    errs.append(f"2: missing {key}")
            lines = lines[end + 1:]

    dates, heads, bodies, tables = [], 0, 0, 0
    for ln in lines:
        m = DATE.match(ln)
        if m:
            dates.append(m.group(1)); continue
        if HEAD.match(ln):
            heads += 1; continue
        if ln.startswith("> "):
            bodies += 1; continue
        if ln.startswith("|"):
            tables += 1
    if tables:
        errs.append(f"8: {tables} table line(s)")
    if len(set(dates)) != len(dates):
        errs.append("3: duplicate date heading")
    if dates != sorted(dates):
        errs.append("3: dates not ascending")
    if heads == 0:
        errs.append("4: no message header")
    if heads and bodies == 0:
        errs.append("5: no quoted body")
    return errs


def main(root):
    root = pathlib.Path(root)
    files = sorted(p for p in root.rglob("*.md") if p.name != "index.md")
    bad = 0
    for f in files:
        errs = check_file(f)
        if errs:
            bad += 1
            print(f"FAIL {f.relative_to(root)}: {', '.join(errs)}")
    print(f"\nroot={root} files={len(files)} failed={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
