"""Draft P0 message contract; requires B/C review before freezing v1.

No database, UI, network or model dependencies. All validation failures omit
field values so callers can safely map them to INVALID_INPUT.
"""
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
from typing import Literal
from urllib.parse import quote

from .base import Contract, nonempty, utc as _utc

CONTRACT_VERSION = "0.2.0-draft"


def stable_message_id(
    source_id: str, chat_id: str, *, original_id: str | None = None,
    seq: int | None = None, content: str = "",
) -> str:
    """Source identity must be stable across paths, batches and exporters.

    Without an original ID, seq must be the source's persistent sequence,
    never a row number recomputed for a filtered export.
    """
    nonempty(source_id, chat_id)
    if type(content) is not str:
        raise ValueError("content must be text")
    prefix = f"{quote(source_id, safe='')}:{quote(chat_id, safe='')}:"
    if original_id is not None:
        nonempty(original_id)
        return prefix + "id:" + quote(original_id, safe="")
    if type(seq) is not int or seq < 0:
        raise ValueError("persistent source sequence is required")
    payload = json.dumps([seq, content], ensure_ascii=False, separators=(",", ":"))
    return prefix + "derived:" + sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Message(Contract):
    message_id: str
    source_id: str
    chat_id: str
    chat_type: Literal["group", "private", "unknown"]
    sender_id: str | None
    sender_name: str | None
    timestamp: str | None
    message_type: Literal["text", "image", "file", "system", "recalled", "unknown"]
    content: str = field(repr=False)
    seq: int
    timestamp_status: Literal["known", "unknown"]
    timestamp_precision: Literal["second", "millisecond", "day", "unknown"]
    timestamp_source: str | None
    source_timezone: str | None
    original_timestamp: str | None = field(default=None, repr=False)
    quote_of: str | None = None
    attachment_ref: str | None = field(default=None, repr=False)
    raw_payload: str | None = field(default=None, repr=False)
    parse_status: Literal["parsed", "partial", "unknown"] = "parsed"

    def __post_init__(self) -> None:
        Contract.__post_init__(self)
        if not self.message_id or not self.source_id or not self.chat_id:
            raise ValueError("message, source and chat identifiers are required")
        if type(self.seq) is not int or self.seq < 0:
            raise ValueError("sequence must be a nonnegative integer")
        for value, allowed in (
            (self.chat_type, {"group", "private", "unknown"}),
            (self.message_type, {"text", "image", "file", "system", "recalled", "unknown"}),
            (self.parse_status, {"parsed", "partial", "unknown"}),
            (self.timestamp_status, {"known", "unknown"}),
            (self.timestamp_precision, {"second", "millisecond", "day", "unknown"}),
        ):
            if value not in allowed:
                raise ValueError("unsupported contract enum")
        if self.timestamp_status == "unknown":
            if self.timestamp is not None or self.timestamp_precision != "unknown":
                raise ValueError("unknown time requires null timestamp and unknown precision")
        elif self.timestamp is None or self.timestamp_precision == "unknown":
            raise ValueError("known time requires a timestamp and precision")
        elif self.timestamp_precision == "day":
            try:
                date.fromisoformat(self.timestamp)
            except ValueError:
                raise ValueError("day precision requires an ISO date") from None
            if len(self.timestamp) != 10 or not self.source_timezone:
                raise ValueError("day precision requires ISO date and source timezone")
        else:
            instant = _utc(self.timestamp)
            if self.timestamp_precision == "second" and instant.microsecond:
                raise ValueError("second precision cannot carry fractional seconds")
            if self.timestamp_precision == "millisecond" and instant.microsecond % 1000:
                raise ValueError("millisecond precision cannot carry finer fractions")
        if self.timestamp_status == "known" and not self.timestamp_source:
            raise ValueError("known time requires provenance")

    def matches_time_range(self, start: str | None, end: str | None) -> bool:
        """Exact instants use [start,end); unknown/day times cannot be guessed.

        Date-only filtering needs a separate interval policy reviewed by B/C.
        Unbounded queries keep all messages, including empty/unknown records.
        """
        lower = _utc(start) if start is not None else None
        upper = _utc(end) if end is not None else None
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("time range is reversed")
        if lower is None and upper is None:
            return True
        if self.timestamp is None or self.timestamp_precision in {"day", "unknown"}:
            return False
        instant = _utc(self.timestamp)
        return (lower is None or lower <= instant) and (upper is None or instant < upper)
