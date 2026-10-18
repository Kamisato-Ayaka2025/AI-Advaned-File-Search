#!/usr/bin/env python3
"""
NTQQ (QQ 9.9.x) encrypted chat DB -> Markdown exporter.

Input : encrypted nt_db directory (nt_msg.db / profile_info.db / group_info.db)
        plus the 16-char database key.
Output: one Markdown file per conversation + index.md

Requires: pip install sqlcipher3-binary

Usage:
  export NTQQ_DB_KEY='<16-char-key>'
  python3 ntqq_export_md.py --nt-db "/path/to/nt_qq/nt_db" --out ./out

The DB layout is: 1024-byte NTQQ header + SQLCipher pages (page_size=4096,
PBKDF2-HMAC-SHA512 with 4000 iterations, HMAC-SHA1).
"""
import argparse
import datetime
import html
import json
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import tempfile
import unicodedata
from collections import defaultdict

import sqlcipher3.dbapi2 as sc

TZ = datetime.timezone(datetime.timedelta(hours=8))
HEADER = 1024
PAGE = 4096

# SQLCipher parameters, tried in order (HMAC algo changed across QQ releases)
CIPHER_CONFIGS = [
    (4000, "HMAC_SHA1", "PBKDF2_HMAC_SHA512"),
    (4000, "HMAC_SHA512", "PBKDF2_HMAC_SHA512"),
    (64000, "HMAC_SHA512", "PBKDF2_HMAC_SHA512"),
]


# ---------------------------------------------------------------- protobuf
def read_varint(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        if not x & 0x80:
            return r, i
        s += 7


def parse(buf):
    """Minimal generic protobuf decoder -> [(field, wire, value)]."""
    i, n, out = 0, len(buf), []
    while i < n:
        key, i = read_varint(buf, i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = read_varint(buf, i)
        elif w == 2:
            ln, i = read_varint(buf, i)
            v = buf[i:i + ln]
            i += ln
        elif w == 5:
            v = buf[i:i + 4]
            i += 4
        elif w == 1:
            v = buf[i:i + 8]
            i += 8
        else:
            raise ValueError("bad wire type %d" % w)
        out.append((f, w, v))
    return out


# ---------------------------------------------------------------- decrypt
def decrypt(src: pathlib.Path, tmp: pathlib.Path, key: str) -> pathlib.Path:
    """Strip the 1024-byte header (+ copy WAL/SHM) and export a plain SQLite file."""
    if not src.exists():
        raise FileNotFoundError(src)
    raw = src.read_bytes()
    if raw[:16] != b"SQLite header 3\x00":
        raise ValueError(f"{src.name}: unexpected magic {raw[:16]!r}")
    if (len(raw) - HEADER) % PAGE:
        raise ValueError(f"{src.name}: size not aligned to 4096-byte pages")

    clear = tmp / (src.stem + "_clear.db")
    clear.write_bytes(raw[HEADER:])
    for ext in ("-wal", "-shm"):
        s = pathlib.Path(str(src) + ext)
        if s.exists():
            shutil.copy(s, str(clear) + ext)

    plain = tmp / (src.stem + "_plain.db")
    if plain.exists():
        plain.unlink()

    last = None
    for it, hmac, kdf in CIPHER_CONFIGS:
        try:
            c = sc.connect(str(clear))
            c.execute("PRAGMA cipher_page_size = 4096;")
            c.execute("PRAGMA key = '%s';" % key.replace("'", "''"))
            c.execute(f"PRAGMA kdf_iter = {it};")
            c.execute(f"PRAGMA cipher_hmac_algorithm = {hmac};")
            c.execute(f"PRAGMA cipher_kdf_algorithm = {kdf};")
            c.execute("SELECT count(*) FROM sqlite_master;").fetchone()
            c.execute(f"ATTACH DATABASE '{plain}' AS plaintext KEY '';")
            c.execute("SELECT sqlcipher_export('plaintext');")
            c.execute("DETACH DATABASE plaintext;")
            c.close()
            return plain
        except Exception as e:  # wrong params -> try next combination
            last = e
    raise RuntimeError(f"{src.name}: decrypt failed ({last})")


# ---------------------------------------------------------------- helpers
def msg_time(ts):
    if not ts or ts <= 946684800 or ts > 4102444800:
        return None
    try:
        return datetime.datetime.fromtimestamp(ts, TZ)
    except (OverflowError, OSError):
        return None


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def safe(s):
    s = unicodedata.normalize("NFKC", s or "").strip()
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", s)[:40] or "unnamed"


def txt(v):
    return v.decode("utf-8", "ignore") if isinstance(v, bytes) else ("" if v is None else str(v))


def one(e, k):
    v = e.get(k)
    return (v[0] if v else None) if isinstance(v, list) else v


# ---------------------------------------------------------------- element
def split_message(blob):
    """[40800] -> (meta, elements); each element is {type, field: [values]}."""
    inner = next((v for f, w, v in parse(bytes(blob)) if f == 40800 and w == 2), None)
    if inner is None:
        return {}, []
    meta, elems, cur = {}, [], None
    for f, w, v in parse(inner):
        if f == 45002:
            cur = {"type": v}
            elems.append(cur)
        elif cur is not None:
            cur.setdefault(f, []).append(v)
        else:
            meta[f] = v
    return meta, elems


def render(e, pic_index):
    t = e["type"]
    if t == 1:
        return txt(one(e, 45101)).strip()
    if t == 2:
        name = txt(one(e, 45402))
        for k in (45406, 45408):
            v = one(e, k)
            if isinstance(v, bytes) and v.hex() in pic_index:
                return f"![图片](<{pic_index[v.hex()]}>)"
        return f"![图片]（未缓存：{name or 'image'}）"
    if t == 3:
        name = txt(one(e, 45402)) or "文件"
        path = txt(one(e, 45403)).replace("::NTOSFull::", "").strip()
        return f"📎 [{name}](<{path}>)" if path else f"📎 文件：{name}"
    if t == 5:
        return "🎬 视频：" + (txt(one(e, 45422)) or txt(one(e, 45402)) or "video")
    if t == 6:
        return "表情 " + txt(one(e, 47602)) if one(e, 47602) else "表情"
    if t == 7:
        blob = one(e, 47423)
        quoted = ""
        if isinstance(blob, bytes):
            quoted = next((txt(v) for f, w, v in parse(blob) if f == 9 and w == 2), "")
        return f"> 引用：{strip_tags(quoted)[:120]}" if quoted else "> 引用消息"
    if t == 8:
        return "— " + (strip_tags(txt(one(e, 48214))) or "系统提示")
    if t == 10:
        try:
            d = json.loads(txt(one(e, 47901)))
            for v in d.get("meta", {}).values():
                if isinstance(v, dict) and (v.get("title") or v.get("desc")):
                    return "🔗 " + (v.get("title") or v.get("desc"))
        except Exception:
            pass
        return "🔗 卡片消息"
    if t == 11:
        name = txt(one(e, 80900)).strip("[]")
        return "表情 " + name if name else "商城表情"
    if t == 16:
        x = txt(one(e, 48602))
        m = re.search(r"<title[^>]*>(.*?)</title>", x, re.S)
        return "🔗 " + (strip_tags(m.group(1)) if m else "分享消息")
    return f"[未识别元素 {t}]"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nt-db", required=True, help=".../nt_qq/nt_db directory")
    ap.add_argument("--out", required=True, help="output directory for Markdown")
    ap.add_argument("--my-uin", type=int, help="own QQ number (for '我' label)")
    ap.add_argument("--pic-root", help="optional .../nt_data/Pic for local image cache")
    args = ap.parse_args()

    key = os.environ.get("NTQQ_DB_KEY", "")
    if len(key) != 16:
        sys.exit("set NTQQ_DB_KEY to the 16-character database key")

    nt_db = pathlib.Path(args.nt_db)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ntqq_"))

    print("[1/4] decrypting ...")
    msg_db = decrypt(nt_db / "nt_msg.db", tmp, key)
    prof_db = decrypt(nt_db / "profile_info.db", tmp, key)
    grp_db = decrypt(nt_db / "group_info.db", tmp, key)

    pic_index = {}
    if args.pic_root:
        root = pathlib.Path(args.pic_root)
        for f in root.rglob("*"):
            if f.is_file():
                pic_index[f.stem.lower()] = os.path.relpath(f, out).replace(os.sep, "/")

    print("[2/4] loading names ...")
    prof = sqlite3.connect(str(prof_db))
    nick_by_uid, nick_by_uin = {}, {}
    for uid, uin, nick in prof.execute("SELECT [1000],[1002],[20002] FROM profile_info_v6"):
        if uid and uid != "u_invalid_______________":
            nick_by_uid[uid] = nick or ""
        if uin:
            nick_by_uin[int(uin)] = nick or ""

    grp = sqlite3.connect(str(grp_db))
    group_name = {c: (n or "") for c, n in grp.execute("SELECT [60001],[60007] FROM group_list")}
    member = {(c, u): ((card or ""), (nick or "")) for c, u, card, nick in grp.execute(
        "SELECT [60001],[1000],[64003],[20002] FROM group_member3")}

    db = sqlite3.connect(str(msg_db))
    uid2uin = {u: int(i) for u, i in db.execute(
        "SELECT [48902],[1002] FROM nt_uid_mapping_table") if u and i}
    my_uid = next((u for u, i in uid2uin.items() if i == args.my_uin),
                  "u_invalid_______________")

    print("[3/4] parsing messages ...")
    convs = defaultdict(lambda: {"msgs": [], "kind": "", "name": "", "id": None})
    for table, kind in (("c2c_msg_table", "private"), ("group_msg_table", "group")):
        q = f"""SELECT [40020],[40021],[40033],[40050],[40058],[40090],[40093],
                       [40800],[40003],[40001] FROM {table}"""
        for suid, peer, suin, ts, day_ts, gname, sname, blob, mtype, mid in db.execute(q):
            dt = msg_time(ts) or msg_time(day_ts)
            code = int(peer) if str(peer).isdigit() else 0
            if kind == "group":
                cid = f"g{code}"
                name = group_name.get(code) or (gname or "").strip()
            else:
                cid = f"u{peer}"
                name = nick_by_uid.get(peer) or str(uid2uin.get(peer, peer))
            if str(peer) in ("0", "None", ""):
                name = "系统消息"

            c = convs[cid]
            c["kind"], c["id"] = kind, peer
            if name and len(name) > len(c["name"]):
                c["name"] = name

            _, elems = split_message(blob) if blob else ({}, [])
            body = "\n".join(x for x in (render(e, pic_index) for e in elems) if x)
            if not body:
                body = f"*[系统消息／已撤回，本地无正文；type={mtype}]*"

            if kind == "group":
                card, nick = member.get((code, suid), ("", ""))
                who = card or nick or (sname or "").strip() or nick_by_uid.get(suid, "") \
                    or (str(suin) if suin else "") or "系统"
            elif suid == my_uid or suin == args.my_uin:
                who = "我"
            else:
                who = nick_by_uid.get(suid) or nick_by_uin.get(suin, "") \
                    or (str(suin) if suin else "") or suid or "系统"
            c["msgs"].append((dt, who, body, mid or 0))

    # messages without a timestamp inherit the nearest neighbour's time
    for c in convs.values():
        ms = sorted(c["msgs"], key=lambda m: m[3])
        last = None
        for i, m in enumerate(ms):
            if m[0] is None:
                nxt = next((x[0] for x in ms[i + 1:] if x[0]), None)
                ms[i] = ((last or nxt),) + m[1:]
            else:
                last = m[0]
        ms = sorted((m for m in ms if m[0]), key=lambda m: m[0])
        c["msgs"] = [(m[0], m[1], m[2]) for m in ms]

    print("[4/4] writing markdown ...")
    for sub in ("private", "group"):
        (out / sub).mkdir(exist_ok=True)
    rows = []
    for cid, c in sorted(convs.items(), key=lambda kv: -len(kv[1]["msgs"])):
        sub = "group" if c["kind"] == "group" else "private"
        p = out / sub / f"{safe(c['name'])}_{safe(str(c['id']))}.md"
        lines = ["---", "platform: qq",
                 f"kind: {'group' if c['kind'] == 'group' else 'private'}",
                 f"conversation: {json.dumps(c['name'] or str(c['id']), ensure_ascii=False)}",
                 f"conversation_id: {json.dumps(str(c['id']), ensure_ascii=False)}",
                 "---",
                 f"# {c['name'] or c['id']}", "",
                 f"- 类型：{'群聊' if c['kind'] == 'group' else '私聊'}",
                 f"- 会话 ID：`{c['id']}`",
                 f"- 消息数：{len(c['msgs'])}",
                 f"- 时间范围：{c['msgs'][0][0]:%Y-%m-%d %H:%M} ~ {c['msgs'][-1][0]:%Y-%m-%d %H:%M}",
                 ""]
        day = None
        for dt, who, body in c["msgs"]:
            if dt.strftime("%Y-%m-%d") != day:
                day = dt.strftime("%Y-%m-%d")
                lines += [f"## {day}", ""]
            lines += [f"**{dt:%H:%M:%S} · {who}**", ""]
            lines += ["> " + ln if not ln.startswith(">") else ln
                      for ln in body.split("\n")]
            lines.append("")
        p.write_text("\n".join(lines), encoding="utf-8")
        rows.append((c, p))

    idx = ["# QQ 聊天记录导出", "",
           f"- 会话数：{len(rows)}", f"- 消息总数：{sum(len(c['msgs']) for c, _ in rows)}",
           "", "| 会话 | 类型 | 消息数 | 文件 |", "| --- | --- | ---: | --- |"]
    for c, p in rows:
        rel = p.relative_to(out).as_posix()
        idx.append(f"| {c['name'] or c['id']} | "
                   f"{'群聊' if c['kind'] == 'group' else '私聊'} | {len(c['msgs'])} | [{rel}]({rel}) |")
    (out / "index.md").write_text("\n".join(idx), encoding="utf-8")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"done: {len(rows)} conversations, "
          f"{sum(len(c['msgs']) for c, _ in rows)} messages -> {out}")


if __name__ == "__main__":
    main()
