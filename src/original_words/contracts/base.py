"""Strict, dependency-free DTO validation and JSON boundary helpers."""
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
import json
import math
import types
from typing import Literal, Union, get_args, get_origin, get_type_hints


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def nonempty(*values: str) -> None:
    require(all(isinstance(v, str) and bool(v.strip()) for v in values),
            "required identifier or text is empty")


def natural(value: int) -> None:
    require(type(value) is int and value >= 0, "expected nonnegative integer")


def unique(values: tuple[str, ...]) -> None:
    require(len(set(values)) == len(values), "duplicate identifier")
    for value in values:
        nonempty(value)


def utc(value: str) -> datetime:
    require(isinstance(value, str), "invalid UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError("invalid UTC timestamp") from None
    require("T" in value and parsed.tzinfo is not None
            and parsed.utcoffset() == timezone.utc.utcoffset(parsed),
            "timestamp must be an ISO UTC instant")
    return parsed


def time_range(start: str | None, end: str | None) -> None:
    lower = utc(start) if start is not None else None
    upper = utc(end) if end is not None else None
    require(lower is None or upper is None or lower <= upper, "time range is reversed")


def _check(value, annotation) -> None:
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for option in args:
            try:
                _check(value, option)
                return
            except ValueError:
                pass
        raise ValueError("invalid union field")
    if origin is Literal:
        require(any(type(value) is type(a) and value == a for a in args),
                "unsupported contract enum")
    elif origin is tuple:
        require(type(value) is tuple, "contract collections must be immutable tuples")
        for item in value:
            _check(item, args[0])
    elif annotation is float:
        try:
            finite = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            finite = False
        require(finite, "expected finite number")
    elif annotation in (str, int, bool, type(None)):
        require(type(value) is annotation, "invalid scalar field type")
    else:
        require(type(value) is annotation, "invalid nested contract type")


class Contract:
    """Immutable dataclasses call this before checking semantic invariants."""

    __slots__ = ()

    def __post_init__(self) -> None:
        for name, annotation in get_type_hints(type(self)).items():
            _check(getattr(self, name), annotation)


def _decode(annotation, value, depth=0):
    require(depth <= 32, "contract nesting limit exceeded")
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for option in args:
            try:
                return _decode(option, value, depth + 1)
            except (ValueError, TypeError):
                pass
        raise ValueError("invalid union field")
    if origin is tuple:
        require(type(value) is list, "expected JSON array")
        return tuple(_decode(args[0], item, depth + 1) for item in value)
    if is_dataclass(annotation):
        require(type(value) is dict, "expected JSON object")
        hints = get_type_hints(annotation)
        require(set(value) <= set(hints), "unknown contract field")
        try:
            return annotation(**{k: _decode(hints[k], v, depth + 1) for k, v in value.items()})
        except TypeError:
            raise ValueError("missing or invalid contract field") from None
    _check(value, annotation)
    return value


def load_json(payload: str):
    """Bounded strict JSON shared by DTO decoding and exact outbound previews."""
    require(type(payload) is str, "expected JSON text")
    try:
        size = len(payload.encode("utf-8"))
    except UnicodeError:
        raise ValueError("invalid JSON text encoding") from None
    require(size <= 1_048_576, "contract JSON exceeds input limit")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON constant")

    try:
        return json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError):
        raise ValueError("invalid contract JSON") from None


def from_json(contract_type, payload: str):
    """Reject unknown fields, duplicate keys, wrong types and oversized input."""
    require(isinstance(contract_type, type) and issubclass(contract_type, Contract)
            and is_dataclass(contract_type), "expected contract dataclass")
    return _decode(contract_type, load_json(payload))


def to_json(value: Contract) -> str:
    require(isinstance(value, Contract) and is_dataclass(value), "expected contract instance")

    def encode(item):
        if is_dataclass(item):
            return {f.name: encode(getattr(item, f.name)) for f in fields(item)}
        if isinstance(item, tuple):
            return [encode(v) for v in item]
        return item

    return json.dumps(encode(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)
