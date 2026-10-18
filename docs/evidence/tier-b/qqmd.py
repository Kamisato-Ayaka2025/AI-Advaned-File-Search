#!/usr/bin/env python3
"""qqmd - one command to turn local WeChat/QQ chat databases into Markdown.

Design notes
------------
* Orchestrates the step scripts in this directory as subprocesses, so each step
  stays independently runnable and debuggable.
* Keys live in a temporary directory that is removed before exit; nothing
  secret is written to the output or to the state file.
* Re-running is cheap: image decoding skips files that already exist, and a
  database signature short-circuit skips decrypt+export when nothing changed.

Usage
-----
  python qqmd.py doctor
  python qqmd.py wechat all  --out ./wechat [--work ./qqmd-work] [--force]
  python qqmd.py wechat keys|decrypt|export|images
  python qqmd.py qq export   --nt-db "<...>/nt_db" --out ./qq --my-uin <UIN>
  python qqmd.py validate    ./wechat
"""
from __future__ import annotations

import argparse
import hashlib          # noqa: F401  step scripts run in-process
import hmac            # noqa: F401
import json
import os
import pathlib
import re              # noqa: F401
import sqlite3         # noqa: F401
import struct          # noqa: F401
import collections     # noqa: F401
import datetime        # noqa: F401
import html            # noqa: F401
import shutil          # noqa: F401  (already used, kept for clarity)
import subprocess      # noqa: F401
import tempfile        # noqa: F401
import time            # noqa: F401
import unicodedata     # noqa: F401

import zstandard                                  # noqa: F401
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: F401

try:                                              # Windows-only, absent on WSL
    import ctypes.wintypes  # noqa: F401
except ImportError:
    pass
import shutil
import subprocess
import sys
import tempfile
import time

# When frozen by PyInstaller the step scripts are unpacked next to this module.
HERE = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent))


def _init_console() -> None:
    """Windows consoles default to GBK; force UTF-8 so Chinese output is readable."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
STATE_NAME = ".qqmd-state.json"


# ---------------------------------------------------------------- helpers
def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_win_python() -> str:
    """The two process-memory probes need Win32 APIs, so they must run on
    Windows Python even when qqmd itself runs elsewhere (e.g. WSL)."""
    if sys.platform == "win32":
        return sys.executable
    env = os.environ.get("QQMD_WIN_PYTHON")
    if env and pathlib.Path(env).exists():
        return env
    for cand in ("python.exe",
                 r"C:\Users\Public\anaconda3\python.exe",
                 os.path.expanduser("~/anaconda3/python.exe"),
                 "/mnt/c/Users/" + os.environ.get("USER", "") + "/anaconda3/python.exe"):
        got = shutil.which(cand) or (cand if pathlib.Path(cand).exists() else None)
        if got:
            return got
    raise SystemExit("找不到 Windows Python（进程内存探针需要它）。"
                     "用 QQMD_WIN_PYTHON=C:\\path\\to\\python.exe 指定。")


def wsl_to_win(path: str) -> str:
    """Translate /mnt/<drive>/... into <DRIVE>:\\... for Windows Python."""
    p = str(path)
    if sys.platform != "win32" and p.startswith("/mnt/") and len(p) > 6 and p[5].isalpha():
        return p[5].upper() + ":" + p[6:].replace("/", "\\")
    return p


def run_win(script: str, args: list[str], quiet: bool = False) -> None:
    # A frozen build already runs on Windows, so the probe can stay in-process.
    if getattr(sys, "frozen", False):
        run(script, [wsl_to_win(a) for a in args], quiet=quiet)
        return
    run(script, [wsl_to_win(a) for a in args], quiet=quiet, interpreter=find_win_python())


def _run_inproc(script: str, args: list[str]) -> None:
    """Execute a step script inside this process (frozen exe has no interpreter)."""
    import runpy
    old = sys.argv[:]
    sys.argv = [script, *args]
    try:
        runpy.run_path(str(HERE / script), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            raise SystemExit(f"{script} failed (exit {e.code})")
    finally:
        sys.argv = old


def run(script: str, args: list[str], quiet: bool = False,
        interpreter: str | None = None) -> None:
    if getattr(sys, "frozen", False) and interpreter is None:
        log(f"→ {script} {' '.join(args[:4])}{' …' if len(args) > 4 else ''}")
        _run_inproc(script, args)
        return
    cmd = [interpreter or sys.executable, str(HERE / script), *args]
    log(f"→ {script} {' '.join(args[:4])}{' …' if len(args) > 4 else ''}")
    proc = subprocess.run(cmd, capture_output=quiet, text=True)
    if proc.returncode != 0:
        if quiet:
            print(proc.stdout or "")
            print(proc.stderr or "")
        raise SystemExit(f"{script} failed (exit {proc.returncode})")
    if not quiet and proc.stdout:
        for line in proc.stdout.strip().splitlines():
            print("   " + line)


def have_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def find_wechat_accounts(root: pathlib.Path) -> list[pathlib.Path]:
    """Return db_storage directories of all accounts under xwechat_files."""
    return sorted(p for p in root.glob("wxid_*/db_storage") if p.is_dir())


def default_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("USERPROFILE", pathlib.Path.home())) / "Documents" / "xwechat_files"


def wechat_running() -> bool:
    for exe in ("tasklist", "tasklist.exe", "/mnt/c/Windows/System32/tasklist.exe",
                r"C:\Windows\System32\tasklist.exe"):
        try:
            out = subprocess.run([exe, "/FI", "IMAGENAME eq Weixin.exe", "/NH"],
                                 capture_output=True, text=True).stdout
            return "Weixin.exe" in out
        except OSError:
            continue
    return False


def db_signature(db_dir: pathlib.Path) -> str:
    """Cheap signature: names + sizes + mtimes of the message dbs."""
    parts = []
    for p in sorted(db_dir.rglob("*.db")):
        # size only: mtime changes on every WAL write and would defeat skipping
        parts.append(f"{p.name}:{p.stat().st_size}")
    import hashlib
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def load_state(work: pathlib.Path) -> dict:
    p = work / STATE_NAME
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(work: pathlib.Path, state: dict) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / STATE_NAME).write_text(json.dumps(state, ensure_ascii=False, indent=2))


def snapshot(db_dir: pathlib.Path, dst: pathlib.Path) -> int:
    """Copy db + wal + shm so decryption is independent of the live client."""
    if dst.exists():
        shutil.rmtree(dst)
    n = 0
    for src in db_dir.rglob("*"):
        if not src.is_file():
            continue
        if src.suffix not in (".db",) and not src.name.endswith((".db-wal", ".db-shm")):
            continue
        rel = src.relative_to(db_dir)
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        n += 1
    return n


# ---------------------------------------------------------------- doctor
def cmd_doctor(args) -> None:
    ok = True
    log("依赖检查")
    for mod in ("zstandard", "cryptography"):
        good = have_module(mod)
        print(f"   {mod:14s} {'ok' if good else 'MISSING  → pip install ' + mod}")
        ok &= good
    print(f"   {'sqlcipher3':14s} {'ok (原生解密)' if have_module('sqlcipher3') else 'absent → 使用纯 Python 解密'}")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        local = pathlib.Path(sys.executable).parent / "ffmpeg.exe"
        ffmpeg = str(local) if local.exists() else None
    print(f"   {'ffmpeg':14s} {'ok' if ffmpeg else 'MISSING  → 仅影响 WXGF 转码'}")
    running = wechat_running()
    print(f"   {'Weixin.exe':14s} {'running' if running else 'NOT RUNNING → 取密钥需要客户端在运行并已登录'}")

    root = pathlib.Path(args.root) if args.root else default_root()
    print(f"   data root      {root}")
    accounts = find_wechat_accounts(root) if root.exists() else []
    for a in accounts:
        n = len(list(a.rglob("*.db")))
        print(f"   account        {a.parent.name}  ({n} dbs)")
    if not accounts:
        print("   account        none found")
        ok = False
    raise SystemExit(0 if ok else 1)


# ---------------------------------------------------------------- wechat
def wechat_pipeline(args) -> None:
    root = pathlib.Path(args.root) if args.root else default_root()
    accounts = find_wechat_accounts(root)
    if not accounts:
        raise SystemExit(f"no wxid_*/db_storage under {root}")

    if args.account:
        accounts = [a for a in accounts if args.account in a.parent.name] or accounts[:1]
    db_dir = accounts[0]
    wxid = db_dir.parent.name.split("_")[0]
    if not wechat_running():
        raise SystemExit("Weixin.exe 未运行：密钥只在内存中，请先打开并登录微信")

    out = pathlib.Path(args.out).resolve()
    work = pathlib.Path(args.work).resolve() if args.work else out.parent / "qqmd-work"
    # Windows probes cannot write to /tmp, so keep temp on the Windows side.
    if sys.platform == "win32":
        tmp_root = None
    else:
        win_tmp = pathlib.Path("/mnt/c/Users") / os.environ.get("USER", "") / "AppData/Local/Temp"
        tmp_root = str(win_tmp) if win_tmp.exists() else "/mnt/c/Windows/Temp"
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="qqmd_", dir=tmp_root))
    state = load_state(work)
    sig = db_signature(db_dir)
    log(f"账号 {wxid}，{len(list(db_dir.rglob('*.db')))} 个库，输出 {out}")

    try:
        # 1) keys
        keys = tmp / "keys.json"
        run_win("wechat4_extract_keys.py", ["--db-dir", str(db_dir), "--out", str(keys)])

        changed = args.force or state.get("db_signature") != sig or not (out / "index.md").exists()
        if not changed and not args.force:
            log("数据库签名未变化，跳过解密与导出")
        else:
            # 2) snapshot + decrypt
            snap = work / "snapshot"
            log(f"快照 → {snap}")
            n = snapshot(db_dir, snap)
            log(f"   {n} 个文件")
            plain = work / "plain"
            # Prefer the sqlcipher3 binding when present; otherwise use the pure
            # page-level decryptor that ships with the exe.
            decrypter = "wechat4_decrypt.py" if have_module("sqlcipher3") else "wechat4_decrypt_pure.py"
            log(f"   解密器：{decrypter}")
            run(decrypter, ["--db-dir", str(snap), "--keys", str(keys), "--out", str(plain)])

            # 3) media index
            media_index = work / "media-index.jsonl"
            run("wechat_media_index.py", [str(plain), str(db_dir.parent / "msg" / "attach"), str(media_index)])

            # 4) image key (optional)
            imgkey = tmp / "imgkey.txt"
            # The image AES key is cached per session and only after the client
            # actually decrypts an image, so try several samples.
            samples = list((db_dir.parent / "msg" / "attach").rglob("*.dat"))[:2]
            for sample in samples:
                if imgkey.exists():
                    break
                try:
                    run_win("wechat4_find_image_key.py",
                            ["--dat", str(sample), "--out", str(imgkey)], quiet=True)
                except SystemExit:
                    continue
            if not imgkey.exists():
                log("图片密钥未找到：请先在微信里点开 2–3 张图片，再重新运行；"
                    "本次图片将保留占位")

            # 5) decode images (incremental: existing files are skipped by script)
            imgmap = work / "image-map.json"
            if imgkey.exists():
                ff = shutil.which("ffmpeg") or str(
                    pathlib.Path(sys.executable).parent / "ffmpeg.exe")
                run("wechat4_decode_images.py",
                    ["--index", str(media_index), "--out", str(out / "media"),
                     "--map", str(imgmap), "--key", imgkey.read_text().strip(),
                     "--xor-key", hex(args.xor_key), "--ffmpeg", ff])

            # 6) export markdown
            cmd = ["--plain", str(plain), "--out", str(out), "--me", wxid,
                   "--media", str(db_dir.parent / "msg")]
            if imgmap.exists():
                cmd += ["--image-map", str(imgmap)]
            run("wechat4_export_md.py", cmd)

            state["db_signature"] = sig
            state["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_state(work, state)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    run("validate_format.py", [str(out)])
    log(f"完成：{out}")


def cmd_wechat(args) -> None:
    if args.step == "all":
        wechat_pipeline(args)
        return

    root = pathlib.Path(args.root) if args.root else default_root()
    accounts = find_wechat_accounts(root)
    if not accounts:
        raise SystemExit(f"no account under {root}")
    db_dir = accounts[0]
    work = pathlib.Path(args.work).resolve() if args.work else pathlib.Path("./qqmd-work").resolve()
    if args.step == "keys":
        run("wechat4_extract_keys.py", ["--db-dir", str(db_dir), "--out", str(work / "keys.json")])
    elif args.step == "decrypt":
        run("wechat4_decrypt.py", ["--db-dir", str(work / "snapshot"), "--keys", str(work / "keys.json"),
                                   "--out", str(work / "plain")])
    elif args.step == "export":
        run("wechat4_export_md.py", ["--plain", str(work / "plain"), "--out", str(pathlib.Path(args.out))])
    elif args.step == "images":
        run("wechat4_decode_images.py", ["--index", str(work / "media-index.jsonl"),
                                         "--out", str(pathlib.Path(args.out) / "media")])
    else:
        raise SystemExit(f"unknown step {args.step}")


# ---------------------------------------------------------------- qq
def cmd_qq(args) -> None:
    if not os.environ.get("NTQQ_DB_KEY"):
        raise SystemExit("请先设置 NTQQ_DB_KEY（16 字符），取法见 01-qq.md")
    cmd = ["--nt-db", args.nt_db, "--out", args.out]
    if args.my_uin:
        cmd += ["--my-uin", str(args.my_uin)]
    run("ntqq_export_md.py", cmd)
    run("validate_format.py", [args.out])


def cmd_validate(args) -> None:
    run("validate_format.py", [args.path], quiet=False)


# ---------------------------------------------------------------- parser
def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="qqmd", description="QQ/微信聊天记录 → Markdown")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="检查依赖、客户端与账号")
    d.add_argument("--root", help="xwechat_files 目录")
    d.set_defaults(func=cmd_doctor)

    w = sub.add_parser("wechat", help="微信流程")
    w.add_argument("step", choices=["all", "keys", "decrypt", "export", "images"])
    w.add_argument("--out", default="./wechat-markdown")
    w.add_argument("--work", help="中间目录（快照/明文/状态），默认输出同级 qqmd-work")
    w.add_argument("--root", help="xwechat_files 目录")
    w.add_argument("--account", help="账号 wxid 片段")
    w.add_argument("--force", action="store_true", help="忽略状态，强制重跑")
    w.add_argument("--xor-key", type=lambda s: int(s, 0), default=0xAC)
    w.set_defaults(func=cmd_wechat)

    q = sub.add_parser("qq", help="QQ 流程（需 NTQQ_DB_KEY）")
    q.add_argument("step", choices=["export"])
    q.add_argument("--nt-db", required=True)
    q.add_argument("--out", default="./qq-markdown")
    q.add_argument("--my-uin", type=int)
    q.set_defaults(func=cmd_qq)

    v = sub.add_parser("validate", help="校验导出目录")
    v.add_argument("path")
    v.set_defaults(func=cmd_validate)
    return ap


def main() -> None:
    _init_console()
    args = build().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
