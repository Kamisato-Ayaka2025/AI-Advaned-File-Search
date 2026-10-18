#!/usr/bin/env python3
"""Decode WeChat 4.x V2 .dat images and emit a message-md5 -> image map.

V2 layout: [6B sig][4B aes_size LE][4B xor_size LE][1B pad][AES-ECB][raw][XOR]
The AES key is a 16-byte ASCII string cached in Weixin.exe memory; it is NOT
the aeskey carried by the image message.
"""
import argparse, json, pathlib, struct, subprocess, sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SIG = b"\x07\x08V2\x08\x07"


def unpad(b):
    n = b[-1] if b else 0
    return b[:-n] if 0 < n <= 16 and b[-n:] == bytes([n]) * n else b


def decrypt(data, key, xor_key):
    if data[:6] != SIG:
        return None
    aes_size, xor_size = struct.unpack_from("<LL", data, 6)
    aligned = aes_size + (16 - aes_size % 16)
    if 15 + aligned > len(data):
        return None
    c = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    head = unpad(c.update(data[15:15 + aligned]) + c.finalize())
    off = 15 + aligned
    raw_end = len(data) - xor_size
    raw = data[off:raw_end] if off < raw_end else b""
    return head + raw + bytes(b ^ xor_key for b in data[raw_end:])


def kind(b):
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:4] == b"GIF8":
        return "gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    if b[:4] == b"wxgf":
        return "wxgf"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="wechat-media-index.jsonl")
    ap.add_argument("--out", required=True, help="image output directory")
    ap.add_argument("--map", required=True, help="output md5 -> relpath json")
    ap.add_argument("--key", required=True, help="16-byte image AES key")
    ap.add_argument("--xor-key", default=0xAC, type=lambda s: int(s, 0))
    ap.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg binary for WXGF (HEVC) frames")
    a = ap.parse_args()

    key = a.key.encode()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    mapping, stats = {}, {}
    for line in open(a.index, encoding="utf-8"):
        r = json.loads(line)
        if r["match_status"] != "verified_path":
            continue
        md5 = r["md5"]
        if md5 in mapping:
            continue
        cached = next(out.glob(f"{md5}.*"), None)
        if cached and cached.is_file():
            mapping[md5] = str(cached.resolve())
            stats["cached"] = stats.get("cached", 0) + 1
            continue
        try:
            data = pathlib.Path(r["source_path"]).read_bytes()
        except OSError:
            continue
        plain = decrypt(data, key, a.xor_key)
        ext = kind(plain) if plain else None
        stats[ext or "fail"] = stats.get(ext or "fail", 0) + 1
        if ext in ("jpg", "png", "gif", "webp"):
            p = out / f"{md5}.{ext}"
            p.write_bytes(plain)
            mapping[md5] = str(p.resolve())
        elif ext == "wxgf":
            i = plain.find(b"\x00\x00\x00\x01")
            if i < 0:
                stats["wxgf_no_startcode"] = stats.get("wxgf_no_startcode", 0) + 1
                continue
            tmp = out / f".{md5}.h265"
            tmp.write_bytes(plain[i:])
            png = out / f"{md5}.png"
            r = subprocess.run([a.ffmpeg, "-y", "-loglevel", "error", "-f", "hevc",
                                "-i", str(tmp), "-frames:v", "1", str(png)],
                               capture_output=True)
            tmp.unlink(missing_ok=True)
            if r.returncode == 0 and png.exists():
                mapping[md5] = str(png.resolve())
                stats["wxgf_ok"] = stats.get("wxgf_ok", 0) + 1
            else:
                stats["wxgf_fail"] = stats.get("wxgf_fail", 0) + 1
    json.dump(mapping, open(a.map, "w"), ensure_ascii=False)
    print(f"decoded={len(mapping)} " + " ".join(f"{k}={v}" for k, v in sorted(stats.items())))


if __name__ == "__main__":
    main()
