#!/usr/bin/env python3
"""WeChat 4.x per-database key extraction (read-only, Windows).

Mechanism
---------
WCDB caches each database's 32-byte raw key inside a runtime object reached from
the bytes "com.Tencent.WCDB.Config.Cipher". The cached data block is XOR-masked
with a 24-byte mask, and only after unmasking does it contain the text
``x'<64 hex>...'``. So the key exists neither as a plain 32-byte buffer nor as a
readable hex string in memory -- a value scan cannot find it, a structure walk
can.

Usage
-----
  python wechat4_extract_keys.py --db-dir "C:\\...\\wxid_xxx\\db_storage" --out keys.json

Writes keys to --out only; never prints them. Delete the file when done.
Read-only: uses ReadProcessMemory, never writes to the client process.
"""
import argparse, ctypes, ctypes.wintypes as wt, hashlib, hmac, json, os, re, struct, sys

NEEDLE = b"com.Tencent.WCDB.Config.Cipher"
MASK = bytes.fromhex("d2c7442458020000004889442450488b450048844c2448488944254048584c24")
HEX_RE = re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")
PAGE_SZ, RESERVE_SZ = 4096, 80

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
                ("AllocationProtect", wt.DWORD), ("_p1", wt.DWORD),
                ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD), ("_p2", wt.DWORD)]


def verify(enc_key, page1):
    """SQLCipher 4 page-1 HMAC check. Positive-controlled: see the evidence doc."""
    if len(page1) < PAGE_SZ:
        return False
    mac_salt = bytes(b ^ 0x3A for b in page1[:16])
    mac_key = hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)
    h = hmac.new(mac_key, page1[16:PAGE_SZ - RESERVE_SZ + 16], hashlib.sha512)
    h.update(struct.pack("<I", 1))
    return h.digest() == page1[PAGE_SZ - 64:PAGE_SZ]


def find_pid():
    import subprocess
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True)
    best = (0, 0)
    for line in r.stdout.strip().splitlines():
        p = line.strip('"').split('","')
        if len(p) >= 5:
            try:
                pid = int(p[1]); mem = int(p[4].replace(",", "").replace(" K", "").strip() or 0)
            except ValueError:
                continue
            if mem > best[1]:
                best = (pid, mem)
    return best[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    pid = find_pid()
    if not pid:
        sys.exit("Weixin.exe not running")
    h = k32.OpenProcess(0x0010 | 0x0400, False, pid)

    def read(addr, n):
        b = ctypes.create_string_buffer(n); br = ctypes.c_size_t(0)
        return b.raw[:br.value] if k32.ReadProcessMemory(
            h, ctypes.c_void_p(addr), b, n, ctypes.byref(br)) and br.value else None

    regions, addr, mbi = [], 0, MBI()
    while addr < 0x7FFFFFFFFFFF:
        if k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
            break
        if mbi.State == 0x1000 and mbi.Protect in {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80} \
           and 0 < mbi.RegionSize < 500 * 1024 * 1024:
            d = read(mbi.BaseAddress, mbi.RegionSize)
            if d:
                regions.append((mbi.BaseAddress, d))
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    print(f"[SCAN] regions={len(regions)} bytes={sum(len(d) for _, d in regions)/1e6:.0f}MB")

    def find_bytes(needle):
        out = []
        for base, data in regions:
            s = 0
            while True:
                i = data.find(needle, s)
                if i < 0:
                    break
                out.append(base + i); s = i + 1
        return out

    needles = find_bytes(NEEDLE)
    print(f"[SCAN] needles={len(needles)}")
    cands = set(); nodes = blobs = literals = 0
    for addr_n in needles:
        pair = struct.pack("<Q", addr_n) + struct.pack("<Q", len(NEEDLE))
        for q in find_bytes(pair):
            node = read(q - 0x10, 0x50)
            if not node or len(node) < 0x40:
                continue
            if struct.unpack_from("<Q", node, 0x18)[0] != len(NEEDLE):
                continue
            nodes += 1
            cfg = struct.unpack_from("<Q", node, 0x28)[0]
            if not (0x10000 <= cfg < 0x800000000000):
                continue
            obj = read(cfg + 0x88, 0x28)
            if not obj or len(obj) < 0x18:
                continue
            p = struct.unpack_from("<Q", obj, 0x8)[0]
            n = struct.unpack_from("<Q", obj, 0x10)[0]
            if not (0 < n <= 1024 and 0x10000 <= p < 0x800000000000):
                continue
            blob = read(p, int(n))
            if not blob or len(blob) != n:
                continue
            blobs += 1
            dec = bytes(v ^ MASK[i % len(MASK)] for i, v in enumerate(blob))
            for m in HEX_RE.finditer(dec):
                literals += 1
                run = m.group(1).decode().lower()
                for s in range(0, max(1, len(run) - 63), 32):
                    if s + 64 <= len(run):
                        cands.add(bytes.fromhex(run[s:s + 64]))
    print(f"[SCAN] nodes={nodes} blobs={blobs} literals={literals} candidates={len(cands)}")

    keys, total = {}, 0
    for root, _, files in os.walk(a.db_dir):
        for f in files:
            if not f.endswith(".db"):
                continue
            path = os.path.join(root, f)
            if os.path.getsize(path) < PAGE_SZ:
                continue
            total += 1
            p1 = open(path, "rb").read(PAGE_SZ)
            for c in cands:
                if len(c) == 32 and verify(c, p1):
                    keys[os.path.relpath(path, a.db_dir)] = c.hex()
                    break
    json.dump(keys, open(a.out, "w"))
    print(f"[VERIFY] verified={len(keys)}/{total} -> {a.out}")
    if total and not keys:
        print("[HINT] 0 keys: check that the account directory belongs to the account "
              "currently logged in; WeChat rewrites every .db on upgrade, so choosing a "
              "directory by modification time picks the wrong account.")


if __name__ == "__main__":
    main()
