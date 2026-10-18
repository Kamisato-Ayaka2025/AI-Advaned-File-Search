#!/usr/bin/env python3
"""Build a message -> media-file index for WeChat 4.x (read-only, no decoding).

Evidence model:
  verified_path : hardlink.db row matched the message md5 AND the file exists
  path_missing  : hardlink row matched but the file is gone
  unlinked      : no hardlink row for this md5
"""
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys

import zstandard as zstd

PLAIN = pathlib.Path(sys.argv[1])
ATTACH = pathlib.Path(sys.argv[2])
OUT = pathlib.Path(sys.argv[3])
z = zstd.ZstdDecompressor()


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def load_dirs(db):
    return {r[0]: r[1] for r in db.execute("SELECT rowid, username FROM dir2id")}


def main():
    hl = sqlite3.connect(str(PLAIN / "hardlink__hardlink.db"))
    dirs = load_dirs(hl)
    images = {}
    for m, fname, d1, d2, typ in hl.execute(
            "SELECT md5, file_name, dir1, dir2, type FROM image_hardlink_info_v4"):
        images[m] = (fname, dirs.get(d1, ""), dirs.get(d2, ""), typ)

    ses = sqlite3.connect(str(PLAIN / "session__session.db"))
    user_by_hash = {md5(u): u for (u,) in ses.execute("SELECT username FROM SessionTable") if u}
    ses.close()

    rows = []
    stats = {"verified_path": 0, "path_missing": 0, "unlinked": 0}
    for shard in ("message__message_0.db", "message__message_1.db"):
        p = PLAIN / shard
        if not p.exists():
            continue
        db = sqlite3.connect(str(p))
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
        for t in tables:
            convo = user_by_hash.get(t[4:], t[4:])
            for lid, sid, mc in db.execute(
                    f"SELECT local_id, server_id, message_content FROM `{t}` "
                    f"WHERE (local_type & 4294967295)=3"):
                if not mc:
                    continue
                try:
                    raw = z.decompress(bytes(mc), max_output_size=1 << 22).decode("utf-8", "ignore")
                except Exception:
                    continue
                mm = re.search(r'md5="([0-9a-f]+)"', raw)
                if not mm:
                    continue
                key = mm.group(1)
                rec = {
                    "platform": "wechat",
                    "conversation_id": convo,
                    "message_id": str(lid),
                    "server_id": str(sid),
                    "media_type": "image",
                    "variant": "cached",
                    "evidence": "hardlink_db",
                    "md5": key,
                    "source_path": None,
                    "output_path": None,
                    "match_status": "unlinked",
                    "decode_status": "pending",
                }
                if key in images:
                    fname, d1, d2, _typ = images[key]
                    path = ATTACH / d1 / d2 / "Img" / fname
                    if path.exists():
                        rec["source_path"] = str(path)
                        rec["match_status"] = "verified_path"
                    else:
                        rec["source_path"] = str(path)
                        rec["match_status"] = "path_missing"
                stats[rec["match_status"]] += 1
                rows.append(rec)
        db.close()

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    print(f"records={len(rows)} " + " ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
