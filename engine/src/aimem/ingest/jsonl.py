from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..models import Unit, stable_id
from ..paths import ext_of
from ..text import date_label


@dataclass
class Message:
    platform: str
    conversation: str
    sender: str
    ts: float
    text: str
    attachments: list[str] = field(default_factory=list)
    source_id: str = ""


def _first(rec: dict, keys: Iterable[str], default: Any = "") -> Any:
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return default


def parse_ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value or "").strip()
    if not s:
        return 0.0
    if s.isdigit():
        return float(s)
    s2 = s.replace("Z", "+00:00").replace("/", "-")
    try:
        return dt.datetime.fromisoformat(s2).timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(s2[: len(fmt) + 2], fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def normalize_record(rec: dict) -> Message:
    platform = str(_first(rec, ("platform", "source", "app"), "jsonl")).lower()
    conversation = str(_first(rec, ("conversation", "chat", "group", "room"), "未命名会话"))
    sender = str(_first(rec, ("sender", "from", "author", "name"), "未知"))
    text = str(_first(rec, ("text", "content", "message", "body"), ""))
    ts = parse_ts(_first(rec, ("timestamp", "time", "ts", "date"), ""))
    raw_att = _first(rec, ("attachments", "files", "attachment"), [])
    if isinstance(raw_att, str):
        attachments = [raw_att] if raw_att else []
    elif isinstance(raw_att, list):
        attachments = [str(a) for a in raw_att]
    else:
        attachments = []
    source_id = str(_first(rec, ("source_id", "id", "msg_id", "message_id"), ""))
    if not source_id:
        source_id = stable_id(platform, conversation, str(ts), sender, text[:80])
    return Message(
        platform=platform,
        conversation=conversation,
        sender=sender,
        ts=ts,
        text=text,
        attachments=attachments,
        source_id=source_id,
    )


def load_jsonl(path: str | Path) -> list[Message]:
    msgs: list[Message] = []
    for line in Path(path).read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            msgs.append(normalize_record(rec))
    return msgs


def build_units(messages: list[Message], *, window: int = 2, max_context_chars: int = 300) -> list[Unit]:
    """Build message units; embeddings carry a +/-window context, display text does not.

    This is the cheap version of `segment -> message`: a short message is embedded
    together with its neighbours, but the result card still shows the message.
    """
    groups: dict[tuple[str, str], list[Message]] = {}
    for m in messages:
        groups.setdefault((m.platform, m.conversation), []).append(m)

    units: list[Unit] = []
    for (platform, conversation), group in groups.items():
        group.sort(key=lambda m: m.ts)
        for i, m in enumerate(group):
            lo = max(0, i - window)
            hi = min(len(group), i + window + 1)
            ctx = " / ".join(x.text for x in group[lo:hi] if x.text)[:max_context_chars]
            attach = " ".join(m.attachments)
            units.append(
                Unit(
                    id=stable_id("msg", platform, conversation, m.source_id),
                    source=platform,
                    kind="message",
                    title=f"{m.sender} · {conversation}",
                    text=f"{m.text} {attach}".strip(),
                    embed_text=(
                        f"{conversation} | {m.sender} | {date_label(m.ts)} | {ctx}"
                    ).strip(),
                    ts=m.ts,
                    scope=conversation,
                    acl=json.dumps([conversation], ensure_ascii=False),
                    aliases=" ".join(ext_of(a) for a in m.attachments if ext_of(a)),
                    meta={
                        "sender": m.sender,
                        "conversation": conversation,
                        "attachments": m.attachments,
                        "source_id": m.source_id,
                    },
                )
            )
    return units
