#!/usr/bin/env python3
"""Read-only probe: find the WeChat 4.x V2 image AES key in Weixin.exe memory.

Usage:
  python wechat4_find_image_key.py --dat "<path to any Img/*.dat>" --out imgkey.txt

Validates each alnum candidate by decrypting a known .dat AES segment and
checking the plaintext for a known image magic.
"""
import argparse, ctypes, ctypes.wintypes as wt, hashlib, json, re, struct, sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SIG = b"\x07\x08V2\x08\x07"
MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"wxgf", b"wxam")

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


def unpad(b):
    n = b[-1] if b else 0
    return b[:-n] if 0 < n <= 16 and b[-n:] == bytes([n]) * n else b


def aes_head(key, data):
    aes_size, xor_size = struct.unpack_from("<LL", data, 6)
    aligned = aes_size + (16 - aes_size % 16)
    if 15 + aligned > len(data):
        return None
    try:
        c = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        return unpad(c.update(data[15:15 + aligned]) + c.finalize())
    except Exception:
        return None


def pid_of():
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
    ap.add_argument("--dat", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = open(a.dat, "rb").read()
    if data[:6] != SIG:
        sys.exit("not a V2 dat file")
    pid = pid_of()
    h = k32.OpenProcess(0x0010 | 0x0400, False, pid)

    def read(addr, n):
        b = ctypes.create_string_buffer(n); br = ctypes.c_size_t(0)
        return b.raw[:br.value] if k32.ReadProcessMemory(
            h, ctypes.c_void_p(addr), b, n, ctypes.byref(br)) and br.value else None

    rx = re.compile(rb"(?<![A-Za-z0-9])([A-Za-z0-9]{16}|[A-Za-z0-9]{32})(?![A-Za-z0-9])")
    seen = set(); tried = 0
    addr = 0; mbi = MBI()
    while addr < 0x7FFFFFFFFFFF:
        if k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
            break
        if mbi.State == 0x1000 and mbi.Protect in {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80} \
           and 0 < mbi.RegionSize < 500 * 1024 * 1024:
            d = read(mbi.BaseAddress, mbi.RegionSize)
            if d:
                for m in rx.finditer(d):
                    cand = m.group(1)
                    if cand in seen:
                        continue
                    seen.add(cand)
                    key = cand[:16] if len(cand) >= 16 else cand
                    plain = aes_head(key, data)
                    if plain and any(plain.startswith(x) for x in MAGICS):
                        open(a.out, "w").write(key.decode())
                        print(f"[FOUND] key_len={len(key)} tried={tried} candidates={len(seen)}")
                        return
                    tried += 1
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    print(f"[MISS] candidates={len(seen)} tried={tried}")


if __name__ == "__main__":
    main()
