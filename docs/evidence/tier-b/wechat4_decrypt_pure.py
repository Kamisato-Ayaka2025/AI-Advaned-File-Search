#!/usr/bin/env python3
"""Decrypt WeChat 4.x databases without the sqlcipher3 binding.

SQLCipher4 page layout (page_size 4096, reserve 80):

    page 1 : [16B salt][encrypted 4000B][IV 16B][HMAC 64B]
    page n : [encrypted 4016B]        [IV 16B][HMAC 64B]

Plaintext page 1 starts with "SQLite format 3\\0"; the reserve area is padding.
Writing plaintext + 80 zero bytes per page yields a normal SQLite file whose
header still declares an 80-byte reserve, which SQLite accepts.

This exists so the exporter can ship on Windows, where no sqlcipher3 wheel is
published. It does not merge -wal: run it on a checkpointed snapshot.
"""
import argparse
import hashlib
import hmac
import json
import pathlib
import struct
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PAGE, RESERVE = 4096, 80


def verify(key: bytes, page1: bytes) -> bool:
    mac_salt = bytes(b ^ 0x3A for b in page1[:16])
    mac_key = hashlib.pbkdf2_hmac("sha512", key, mac_salt, 2, dklen=32)
    h = hmac.new(mac_key, page1[16:PAGE - RESERVE + 16], hashlib.sha512)
    h.update(struct.pack("<I", 1))
    return h.digest() == page1[PAGE - 64:PAGE]


def _page_plain(page: bytes, key: bytes, pgno: int) -> bytes:
    iv = page[PAGE - RESERVE:PAGE - RESERVE + 16]
    if pgno == 1:
        ct = page[16:PAGE - RESERVE]
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        pt = b"SQLite format 3\x00" + dec.update(ct) + dec.finalize()
    else:
        ct = page[:PAGE - RESERVE]
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        pt = dec.update(ct) + dec.finalize()
    return pt + b"\x00" * RESERVE


def _wal_pages(src: pathlib.Path, key: bytes) -> dict[int, bytes]:
    """Decrypt committed WAL frames: {pgno: plaintext page}."""
    wal = pathlib.Path(str(src) + "-wal")
    if not wal.exists():
        return {}
    data = wal.read_bytes()
    if len(data) < 32:
        return {}
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic not in (0x377F0682, 0x377F0683):
        return {}
    if struct.unpack_from(">I", data, 8)[0] != PAGE:
        return {}
    salt = data[16:24]
    pages: dict[int, bytes] = {}
    off = 32
    while off + 24 + PAGE <= len(data):
        hdr = data[off:off + 24]
        pgno = struct.unpack_from(">I", hdr, 0)[0]
        if hdr[8:16] != salt:
            break                      # frame belongs to an older WAL generation
        page = data[off + 24:off + 24 + PAGE]
        if pgno > 0:
            pages[pgno] = _page_plain(page, key, pgno)
        off += 24 + PAGE
    return pages


def decrypt_db(src: pathlib.Path, dst: pathlib.Path, key: bytes) -> tuple[int, int]:
    data = src.read_bytes()
    if len(data) % PAGE:
        raise ValueError(f"{src.name}: size not page aligned")
    n = len(data) // PAGE
    frames = _wal_pages(src, key)
    pages = {}
    for i in range(n):
        pages[i + 1] = _page_plain(data[i * PAGE:(i + 1) * PAGE], key, i + 1)
    # WAL pages override the main file, mirroring what SQLite itself would read.
    pages.update(frames)
    total = max(pages) if pages else 0
    out = bytearray()
    for pgno in range(1, total + 1):
        out += pages.get(pgno, b"\x00" * PAGE)
    dst.write_bytes(out)
    return n, len(frames)


def wal_frames(src: pathlib.Path) -> int:
    """Number of committed frames in the -wal file (0 when absent)."""
    wal = pathlib.Path(str(src) + "-wal")
    if not wal.exists():
        return 0
    size = wal.stat().st_size
    return max(0, (size - 32) // (24 + PAGE))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    src_root = pathlib.Path(a.db_dir)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys = json.load(open(a.keys, encoding="utf-8"))

    ok = fail = 0
    for rel, key_hex in sorted(keys.items()):
        src = src_root / rel.replace("\\", "/")
        if not src.exists():
            continue
        key = bytes.fromhex(key_hex)
        page1 = src.read_bytes()[:PAGE]
        if not verify(key, page1):
            print(f"{rel:42s} key check FAILED")
            fail += 1
            continue
        dst = out / rel.replace("\\", "__").replace("/", "__")
        pages, merged = decrypt_db(src, dst, key)
        note = f"  +{merged} WAL pages" if merged else ""
        print(f"{rel:42s} ok  pages={pages}{note}")
        ok += 1
    print(f"\nok={ok} failed={fail} -> {out}")


if __name__ == "__main__":
    main()
