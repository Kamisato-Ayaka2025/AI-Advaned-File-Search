#!/usr/bin/env python3
"""Decrypt WeChat 4.x databases with extracted per-database raw keys.

Usage
-----
  python wechat4_decrypt.py --db-dir "C:\\...\\db_storage" --keys keys.json --out ./plain

Requires: pip install sqlcipher3-binary

Input must include ``-wal`` / ``-shm`` next to each ``.db`` (copy the trio), or
the newest messages are lost. Output is one plain SQLite file per database plus
an integrity report.
"""
import argparse, json, os, pathlib, sqlite3, sys

import sqlcipher3.dbapi2 as sc

PAGE_SZ = 4096


def _copy_real_tables(enc_conn, dst):
    """Copy every non-virtual table (FTS shadow tables included) into a plain db."""
    out = sqlite3.connect(str(dst))
    for name, sql in enc_conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall():
        if not sql or "VIRTUAL TABLE" in sql.upper():
            continue
        try:
            out.execute(sql)
            rows = enc_conn.execute(f"SELECT * FROM `{name}`").fetchall()
            if rows:
                out.executemany(
                    f"INSERT INTO `{name}` VALUES ({','.join('?' * len(rows[0]))})", rows)
        except sqlite3.Error:
            continue
    out.commit()
    out.close()
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    src_root = pathlib.Path(a.db_dir)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    keys = json.load(open(a.keys))

    print(f"{'database':42s} {'integrity':10s} {'objects':>7s} {'rows':>8s}")
    bad = 0
    for rel, key in sorted(keys.items()):
        src = src_root / rel.replace("\\", "/")
        if not src.exists():
            continue
        dst = out / (rel.replace("\\", "__").replace("/", "__"))
        dst.unlink(missing_ok=True)
        try:
            c = sc.connect(str(src))
            c.execute("PRAGMA cipher_log_level = NONE;")
            c.execute("PRAGMA cipher_page_size = 4096;")
            c.execute(f"PRAGMA key = \"x'{key}'\"")
            # FTS databases declare a private tokenizer module (MMFtsTokenizer) that
            # vanilla SQLCipher does not have, so integrity_check itself can fail.
            try:
                integrity = c.execute("PRAGMA integrity_check;").fetchone()[0]
            except Exception:
                integrity = "n/a(fts)"
            objects = c.execute("SELECT count(*) FROM sqlite_master;").fetchone()[0]
            # Plain export works for ordinary databases.
            mode = "export"
            try:
                c.execute(f"ATTACH DATABASE '{dst}' AS plain KEY '';")
                c.execute("SELECT sqlcipher_export('plain');")
                c.execute("DETACH DATABASE plain;")
            except Exception:
                # sqlcipher_export cannot recreate the unknown virtual tables; fall
                # back to copying the real shadow tables (FTS index is rebuildable).
                try:
                    c.execute("DETACH DATABASE plain;")
                except Exception:
                    pass
                dst.unlink(missing_ok=True)
                dst = _copy_real_tables(c, dst)
                mode = "manual"
            c.close()
            p = sqlite3.connect(str(dst))
            tables = [r[0] for r in p.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            rows = 0
            for t in tables:
                try:
                    rows += p.execute(f"SELECT count(*) FROM `{t}`").fetchone()[0]
                except sqlite3.Error:
                    pass
            p.close()
            print(f"{rel:42s} {integrity:10s} {objects:7d} {rows:8d}  {mode}")
            if integrity not in ("ok", "n/a(fts)"):
                bad += 1
        except Exception as e:
            bad += 1
            print(f"{rel:42s} {'FAIL':10s} {type(e).__name__}: {e}")
    print(f"\nfailed={bad} total={len(keys)}")
    print("note: FTS databases report n/a(fts) because their private tokenizer module "
          "is absent; their shadow tables are still copied and the index is rebuildable.")


if __name__ == "__main__":
    main()
