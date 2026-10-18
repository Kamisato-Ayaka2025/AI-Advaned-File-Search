#!/usr/bin/env python3
"""WeChat 4.x decrypted DBs -> Markdown (per conversation + index + combined)."""
import sqlite3, hashlib, html, json, os, re, sys, datetime, pathlib, unicodedata
import zstandard as zstd

import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument("--plain", required=True, help="directory produced by wechat4_decrypt.py")
_ap.add_argument("--out", required=True, help="output directory for Markdown")
_ap.add_argument("--me", default="", help="own wxid, rendered as '我'")
_args = _ap.parse_args()
SRC = pathlib.Path(_args.plain)
OUT = pathlib.Path(_args.out)
ME = _args.me
TZ = datetime.timezone(datetime.timedelta(hours=8))
z = zstd.ZstdDecompressor()
MAX = 1 << 22


# ---------------- helpers ----------------
def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def attr(xml, name):
    m = re.search(rf'{name}="([^"]*)"', xml or "")
    return html.unescape(m.group(1)) if m else ""


def tag(xml, name):
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", xml or "", re.S)
    return html.unescape(m.group(1)) if m else ""


def safe(s):
    s = unicodedata.normalize("NFKC", s or "").strip()
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", s)[:40] or "unnamed"


def read_pb(buf):
    """minimal protobuf reader -> [(field, value)]"""
    i, n, out = 0, len(buf), []
    def varint(i):
        r = s = 0
        while True:
            b = buf[i]; i += 1
            r |= (b & 0x7F) << s
            if not b & 0x80:
                return r, i
            s += 7
    while i < n:
        key, i = varint(i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = varint(i)
        elif w == 2:
            ln, i = varint(i)
            v = buf[i:i + ln]; i += ln
        elif w == 5:
            v = buf[i:i + 4]; i += 4
        elif w == 1:
            v = buf[i:i + 8]; i += 8
        else:
            break
        out.append((f, v))
    return out


# ---------------- names ----------------
def load_names():
    contact = sqlite3.connect(str(SRC / "contact__contact.db"))
    names = {}
    for u, nick, remark, alias in contact.execute(
            "SELECT username, nick_name, remark, alias FROM contact"):
        names[u] = (remark or nick or alias or u).strip()
    groups = {}
    for rid, u, owner, buf in contact.execute("SELECT id, username, owner, ext_buffer FROM chat_room"):
        groups[u] = {}
        if buf:
            try:
                for f, v in read_pb(bytes(buf)):
                    if f == 1 and isinstance(v, bytes):
                        sub = dict(read_pb(v))
                        uid = sub.get(1); disp = sub.get(2)
                        if isinstance(uid, bytes):
                            uid = uid.decode("utf-8", "ignore")
                        if isinstance(disp, bytes):
                            disp = disp.decode("utf-8", "ignore")
                        if uid and disp:
                            groups[u][uid] = disp
            except Exception:
                pass
    contact.close()
    return names, groups


def load_conversations():
    s = sqlite3.connect(str(SRC / "session__session.db"))
    users = [r[0] for r in s.execute("SELECT username FROM SessionTable") if r[0]]
    s.close()
    return {md5(u): u for u in users}


def load_senders(db):
    try:
        return {rowid: u for rowid, u in db.execute("SELECT rowid, user_name FROM Name2Id")}
    except sqlite3.Error:
        return {}


# ---------------- content ----------------
def decode_content(raw):
    if raw is None:
        return ""
    data = bytes(raw) if isinstance(raw, (bytes, bytearray)) else str(raw).encode()
    if data[:4] == b"\x28\xb5\x2f\xfd":
        try:
            data = z.decompress(data, max_output_size=MAX)
        except Exception:
            return "[解压失败]"
    return data.decode("utf-8", "replace")


APP_ICONS = {5: "🔗", 6: "📎", 19: "📦", 57: "💬", 62: "👉", 2000: "💸", 2001: "🧧"}


def render(base, text, app_subtype):
    t = text.strip()
    if base == 1:
        return t
    if base == 3:
        return "🖼 图片"
    if base == 34:
        ms = attr(t, "voicelength") or "0"
        try:
            sec = int(ms) / 1000
        except ValueError:
            sec = 0
        return f"🎤 语音 {sec:.0f}s" if sec else "🎤 语音"
    if base == 42:
        nick = attr(t, "nickname")
        return f"👤 名片：{nick}" if nick else "👤 名片"
    if base == 43:
        return "🎬 视频"
    if base == 47:
        return "😀 表情"
    if base == 48:
        poi = attr(t, "poiname"); label = attr(t, "label")
        return f"📍 位置：{poi or label}"
    if base == 49:
        title = strip_tags(tag(t, "title"))
        des = strip_tags(tag(t, "des"))
        sub = app_subtype or 0
        icon = APP_ICONS.get(sub, "🔗")
        label = title or des or "应用消息"
        if des and des != title and len(des) < 60:
            label += f"（{des}）"
        return f"{icon} {label}"
    if base == 50:
        m = re.search(r"<!\[CDATA\[(.*?)\]\]>", t, re.S)
        return "☎️ " + (strip_tags(m.group(1)) if m else "通话")
    if base == 10000:
        content = strip_tags(tag(t, "content")) or strip_tags(t)
        return f"— {content}"
    return f"[类型 {base}]"


def sender_name(uid, convo, names, groups):
    if not uid:
        return "未知"
    if ME and uid == ME:
        return "我"
    if convo.endswith("@chatroom"):
        disp = groups.get(convo, {}).get(uid)
        if disp:
            return disp
    return names.get(uid, uid)


# ---------------- main ----------------
def main():
    names, groups = load_names()
    convos = load_conversations()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chat").mkdir(exist_ok=True)

    buckets = {}
    for shard in ("message__message_0.db", "message__message_1.db"):
        p = SRC / shard
        if not p.exists():
            continue
        db = sqlite3.connect(str(p))
        senders = load_senders(db)
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
        for t in tables:
            user = convos.get(t[4:])
            if not user:
                continue
            rows = db.execute(
                f"SELECT local_type, create_time, sort_seq, real_sender_id, "
                f"message_content FROM `{t}`").fetchall()
            if not rows:
                continue
            b = buckets.setdefault(user, [])
            for lt, ct, seq, sid, mc in rows:
                base = int(lt) & 0xFFFFFFFF
                sub = int(lt) >> 32
                text = decode_content(mc)
                uid = senders.get(sid, "")
                m = re.match(r"^(wxid_[0-9A-Za-z]+|[0-9]+@chatroom):\s*", text)
                if m:
                    uid = uid or m.group(1)
                    text = text[m.end():]
                b.append((int(seq or 0), int(ct or 0), sender_name(uid, user, names, groups),
                          render(base, text, sub)))
        db.close()

    # de-dup by (seq, sender, text) then sort
    convs = []
    for user, msgs in buckets.items():
        seen = set(); uniq = []
        for m in sorted(msgs, key=lambda x: (x[0], x[1])):
            k = (m[0], m[1], m[2], m[3])
            if k in seen:
                continue
            seen.add(k); uniq.append(m)
        convs.append((user, uniq))
    convs.sort(key=lambda kv: -len(kv[1]))

    print(f"{'conversation':40s} {'msgs':>7s}")
    index = []
    for user, msgs in convs:
        if user.endswith("@chatroom"):
            title = names.get(user, user) or user
            kind = "群聊"
        else:
            title = names.get(user, user) or user
            kind = "私聊"
        fname = f"{safe(title)}_{safe(user)}.md"
        lines = [f"# {title}", "", f"- 类型：{kind}", f"- 会话 ID：`{user}`",
                 f"- 消息数：{len(msgs)}",
                 f"- 时间范围：{datetime.datetime.fromtimestamp(msgs[0][1], TZ):%Y-%m-%d %H:%M}"
                 f" ~ {datetime.datetime.fromtimestamp(msgs[-1][1], TZ):%Y-%m-%d %H:%M}", ""]
        day = None
        for seq, ct, who, body in msgs:
            dt = datetime.datetime.fromtimestamp(ct, TZ)
            if dt.strftime("%Y-%m-%d") != day:
                day = dt.strftime("%Y-%m-%d")
                lines += [f"## {day}", ""]
            lines += [f"**{dt:%H:%M:%S} · {who}**", ""]
            lines += ["> " + ln if not ln.startswith(">") else ln for ln in body.split("\n")]
            lines.append("")
        (OUT / "chat" / fname).write_text("\n".join(lines), encoding="utf-8")
        index.append((title, kind, len(msgs), f"chat/{fname}"))
        print(f"{title[:38]:40s} {len(msgs):7d}")

    total = sum(i[2] for i in index)
    idx = ["# 微信聊天记录导出", "", f"- 会话数：{len(index)}", f"- 消息总数：{total}",
           f"- 导出时间：{datetime.datetime.now(TZ):%Y-%m-%d %H:%M}", "",
           "| 会话 | 类型 | 消息数 | 文件 |", "| --- | --- | ---: | --- |"]
    for title, kind, n, rel in index:
        idx.append(f"| {title} | {kind} | {n} | [{rel}]({rel}) |")
    (OUT / "index.md").write_text("\n".join(idx), encoding="utf-8")

    with (OUT / "ALL.md").open("w", encoding="utf-8") as f:
        f.write(f"# 微信聊天记录全量导出\n\n会话：{len(index)}　消息：{total}\n")
        for title, kind, n, rel in index:
            text = (OUT / rel).read_text(encoding="utf-8")
            f.write("\n---\n\n" + text)

    print(f"\nsessions={len(index)} messages={total} -> {OUT}")


if __name__ == "__main__":
    main()
