"""OCR WeChat image links and inject captions into Markdown (proof of concept).

Usage:
  python examples/wx_ocr_caption.py ~/qqmd/wxout ~/qqmd/wxout_ocr --limit 120

For every `![图片](<../images/x.png>)` it OCRs the image and appends:

  > [图片文字] 课表 2025-2026学年 第8周 ...

Table-heavy screenshots come out fragmented; a VLM caption is better there.
Large images are downscaled; a persistent cache makes runs resumable.
"""

import argparse
import gc
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

Image.MAX_IMAGE_PIXELS = None
LINK = re.compile(r"!\[图片\]\(<([^>]+)>\)")
MAX_PIXELS = 40_000_000
MAX_SIDE = 1600


def load_image(path: Path):
    with Image.open(path) as im:
        w, h = im.size
        if w * h > MAX_PIXELS:
            return None
        im = im.convert("RGB")
        scale = min(1.0, MAX_SIDE / max(w, h))
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        return np.array(im)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=0, help="max NEW images to OCR (0 = all)")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cache_path = out / ".caption_cache.json"
    cache: dict[str, str] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text("utf-8"))

    engine = RapidOCR()
    done = 0

    for md in src.rglob("*.md"):
        text = md.read_text("utf-8")

        def repl(m: re.Match) -> str:
            nonlocal done
            img = (md.parent / m.group(1)).resolve()
            key = str(img)
            if key not in cache:
                if args.limit and done >= args.limit:
                    return m.group(0)
                cap = ""
                try:
                    arr = load_image(img) if img.exists() else None
                    if arr is not None:
                        res, _ = engine(arr)
                        cap = " ".join(x[1] for x in (res or []))
                except Exception:
                    cap = ""
                cache[key] = cap
                done += 1
                if done % 10 == 0:
                    print(f"  ocr {done} (cache {len(cache)})", flush=True)
                gc.collect()
            cap = cache[key].strip()
            return f"{m.group(0)}\n> [图片文字] {cap}" if cap else m.group(0)

        new = LINK.sub(repl, text)
        target = out / md.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new, "utf-8")
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")
        if args.limit and done >= args.limit:
            break

    print(f"DONE new={done} cache={len(cache)} -> {out}", flush=True)


if __name__ == "__main__":
    main()
