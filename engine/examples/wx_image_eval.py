"""Isolation test: terms that exist ONLY in image captions.

Compares the pre-OCR WeChat DB (no captions) with the post-OCR DB.
Uses lexical-only retrieval so the result measures caption coverage, not
embedding quality.
"""

import re
import sqlite3

SRC = r"\\wsl.localhost\Ubuntu\home\user\AI-Advaned-File-Search\src"
import sys

if SRC not in sys.path:
    sys.path.insert(0, SRC)

from aimem import db  # noqa: E402
from aimem.search.pipeline import search  # noqa: E402

PRE = r"C:\Users\user\aimem-test\wx_bge.db"
POST = r"C:\Users\user\aimem-test\wx_ocr.db"
CAPTION = "[图片文字]"


def main() -> None:
    post = db.connect(POST)
    pre = db.connect(PRE)

    # non-image text corpus (pre DB has no captions at all)
    normal = "\n".join(
        r[0] or "" for r in pre.execute("select text from units where source='wechat'")
    )

    captions = [
        r[0]
        for r in post.execute(
            "select text from units where source='wechat' and text like ?",
            (f"%{CAPTION}%",),
        )
    ]
    print(f"image messages with captions: {len(captions)}")

    # candidate terms: 4-6 Chinese chars, unique-ish, absent from normal text
    freq: dict[str, int] = {}
    for text in captions:
        cap = text.split(CAPTION, 1)[1]
        for term in re.findall(r"[\u4e00-\u9fff]{4,6}", cap):
            freq[term] = freq.get(term, 0) + 1
    candidates = [
        t
        for t, n in freq.items()
        if n <= 2 and t not in normal and len(t) >= 4
    ]
    # prefer "meaningful" terms
    hints = ("课表", "证明", "报告", "申请", "奖学金", "排班", "通知", "名单", "作业", "实验")
    candidates.sort(key=lambda t: (not any(h in t for h in hints), -len(t)))
    picked = candidates[:12]

    print(f"image-only candidate terms: {len(candidates)}, testing {len(picked)}\n")
    hit_post = hit_pre = 0
    for term in picked:
        rp = search(post, None, None, term, limit=10, use_semantic=False)
        rr = search(pre, None, None, term, limit=10, use_semantic=False)
        ok_p = any(CAPTION in (r.unit.text or "") and term in (r.unit.text or "") for r in rp)
        ok_r = any(CAPTION in (r.unit.text or "") and term in (r.unit.text or "") for r in rr)
        hit_post += ok_p
        hit_pre += ok_r
        print(f"{'HIT ' if ok_p else 'miss'} pre={'HIT' if ok_r else 'miss'}  {term}")

    n = max(1, len(picked))
    print(f"\npost-OCR image hit rate: {hit_post}/{len(picked)} = {hit_post/n:.0%}")
    print(f"pre-OCR  image hit rate: {hit_pre}/{len(picked)} = {hit_pre/n:.0%}")


if __name__ == "__main__":
    main()
