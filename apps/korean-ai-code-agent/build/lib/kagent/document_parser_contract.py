"""#2824-S3A: bounded wire contract for the isolated document parser boundary.

The isolated parser is two processes, so every value that crosses between them
needs exactly one owner. This module is that owner: the request envelope, the
child report, the bounded reason-code vocabulary and the byte/character
ceilings all live here and are *derived* from the existing Core document bounds
rather than guessed into existence.

Authority boundaries
--------------------
- ``CORE != PROCESS_AUTHORITY``. The ceilings below are read from
  ``padiem_ai_core.document_normalization``; nothing here can widen them, and
  no Core source changes for isolation.
- ``CHILD != UNBOUNDED_CONSUMER``. Every decode is length-bounded and returns
  ``None`` (a bounded refusal) instead of raising on attacker-shaped input.
- ``MODEL != FILE_FORMAT_IMPLEMENTATION``. Nothing here classifies content; the
  pre-parser gate keeps that authority and the Core parser keeps the parse.
- This module holds **no** process, network, provider or filesystem authority,
  which is what lets the child entrypoint import it without gaining any way to
  start a process.

Vocabulary
----------
``ParserOutcome`` values are ``completed``, ``rejected``, ``timed_out`` and
``failed``. ``rejected`` means the child ran and the Core parser refused the
document with a bounded reason code; ``failed`` means the boundary could not
produce a trustworthy result at all (child crash, malformed or oversized
report, a child that outlived the kill). A timeout is reported only as
``timed_out`` and never re-labelled as a failure or a cancellation.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any

from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_DOCUMENT_CHARS,
    MAX_DOCUMENT_NAME_CHARS,
)

__all__ = [
    "CHILD_MODULE_NAME",
    "ENVELOPE_KEYS",
    "MAX_CHILD_ENVELOPE_BYTES",
    "MAX_CHILD_ERROR_BYTES",
    "MAX_CHILD_OUTPUT_BYTES",
    "MAX_MEDIA_TYPE_CHARS",
    "PARSER_INPUT_REASON_CODE",
    "PARSER_ISOLATION_FAILURE_REASON_CODE",
    "PARSER_TIMEOUT_REASON_CODE",
    "REPORT_REJECTION_KEYS",
    "REPORT_SUCCESS_KEYS",
    "ParserEnvelope",
    "ParserReport",
    "decode_envelope",
    "decode_report",
    "encode_envelope",
    "encode_report",
    "is_bounded_reason_code",
]

#: The one reviewed child module the parent is allowed to start. The parent
#: never builds a command from caller input, so this constant is the whole
#: executable authority of the boundary.
CHILD_MODULE_NAME = "kagent.document_parser_child"

# ---------------------------------------------------------------------------
# Bounded reason vocabulary
# ---------------------------------------------------------------------------

#: Hard timeout. Reported only for a child that had to be terminated.
PARSER_TIMEOUT_REASON_CODE = "document_parse_timeout"

#: The boundary itself could not produce a trustworthy result.
PARSER_ISOLATION_FAILURE_REASON_CODE = "document_parse_isolated_failure"

#: The caller handed the boundary input outside the existing Core byte bound.
#: Defence in depth: the #2824 gate normally refuses this first, so reaching
#: this code means the caller bypassed the gate or the bound drifted.
PARSER_INPUT_REASON_CODE = "document_parse_input_rejected"

#: A reason code is a bounded enumeration, never free text. This is the
#: structural guard that keeps a payload, a host path, an exception message or a
#: traceback out of the public note: none of them can match this grammar.
_BOUNDED_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def is_bounded_reason_code(value: Any) -> bool:
    """Whether ``value`` is a bounded reason identifier and not free text."""

    return isinstance(value, str) and _BOUNDED_REASON_RE.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# Ceilings
# ---------------------------------------------------------------------------

#: A media type is a bounded token, not a free-form string.
MAX_MEDIA_TYPE_CHARS = 128

#: Parent -> child. The envelope carries the payload base64-encoded, so the
#: ceiling is the Core binary bound expanded by the base64 ratio plus a small
#: fixed frame.
MAX_CHILD_ENVELOPE_BYTES = ((MAX_BINARY_DOCUMENT_BYTES + 2) // 3) * 4 + 4096

#: Child -> parent. The only successful payload is the Core-bounded extracted
#: text; JSON escaping can expand a single character to six bytes, so the byte
#: ceiling is derived from the Core character ceiling rather than guessed.
MAX_CHILD_OUTPUT_BYTES = (MAX_DOCUMENT_CHARS * 6) + 4096

#: Child stderr is drained to keep the pipe from filling, and is never surfaced.
MAX_CHILD_ERROR_BYTES = 8192

# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------

ENVELOPE_KEYS = frozenset({"name", "media_type", "base64"})
REPORT_SUCCESS_KEYS = frozenset({"ok", "text"})
REPORT_REJECTION_KEYS = frozenset({"ok", "code"})


@dataclass(frozen=True, slots=True)
class ParserEnvelope:
    """One bounded parent -> child parse request."""

    name: str
    media_type: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class ParserReport:
    """One bounded child -> parent parse report.

    A successful report carries text and no code; a refusal carries a bounded
    code and no text. The two shapes cannot be mixed, so a caller can never read
    a partial success or an unbounded error string.
    """

    ok: bool
    text: str | None = None
    code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise ValueError("report ok must be a boolean")
        if self.ok:
            if not isinstance(self.text, str) or self.code is not None:
                raise ValueError("a successful report carries text only")
            if len(self.text) > MAX_DOCUMENT_CHARS:
                raise ValueError("report text exceeds the Core character bound")
        else:
            if is_bounded_reason_code(self.code) is False or self.text is not None:
                raise ValueError("a refusal report carries a bounded code only")


def encode_envelope(*, name: Any, media_type: Any, payload: Any) -> bytes:
    """Encode one request envelope. Raises on programmer misuse only."""

    if not isinstance(name, str) or not name:
        raise ValueError("envelope name must be a non-empty string")
    if len(name) > MAX_DOCUMENT_NAME_CHARS:
        raise ValueError("envelope name exceeds the Core name bound")
    if not isinstance(media_type, str) or not media_type:
        raise ValueError("envelope media_type must be a non-empty string")
    if len(media_type) > MAX_MEDIA_TYPE_CHARS:
        raise ValueError("envelope media_type exceeds the bounded token length")
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError("envelope payload must be bytes")
    body = bytes(payload)
    if len(body) > MAX_BINARY_DOCUMENT_BYTES:
        raise ValueError("envelope payload exceeds the Core binary bound")
    frame = {
        "name": name,
        "media_type": media_type,
        "base64": base64.b64encode(body).decode("ascii"),
    }
    encoded = json.dumps(frame, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_CHILD_ENVELOPE_BYTES:
        raise ValueError("envelope exceeds the bounded wire ceiling")
    return encoded


def decode_envelope(raw: Any) -> ParserEnvelope | None:
    """Decode one request envelope, or return ``None`` for a bounded refusal.

    Never raises for attacker-shaped input: bad UTF-8, bad JSON, a wrong shape,
    an oversized field or a malformed base64 body all return ``None``. Semantic
    document identity stays Core's authority — this only enforces the wire
    shape and the existing Core bounds.
    """

    if not isinstance(raw, (bytes, bytearray)):
        return None
    data = bytes(raw)
    if not data or len(data) > MAX_CHILD_ENVELOPE_BYTES:
        return None
    try:
        frame = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(frame, dict) or set(frame) != ENVELOPE_KEYS:
        return None
    name = frame["name"]
    media_type = frame["media_type"]
    encoded = frame["base64"]
    if not isinstance(name, str) or not isinstance(media_type, str):
        return None
    if not isinstance(encoded, str):
        return None
    if not name or len(name) > MAX_DOCUMENT_NAME_CHARS:
        return None
    if not media_type or len(media_type) > MAX_MEDIA_TYPE_CHARS:
        return None
    if len(encoded) > ((MAX_BINARY_DOCUMENT_BYTES + 2) // 3) * 4:
        return None
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not payload or len(payload) > MAX_BINARY_DOCUMENT_BYTES:
        return None
    return ParserEnvelope(name=name, media_type=media_type, payload=payload)


def encode_report(report: ParserReport) -> bytes:
    """Encode one child report. Raises on programmer misuse only."""

    if not isinstance(report, ParserReport):
        raise ValueError("report must be a ParserReport")
    if report.ok:
        frame: dict[str, Any] = {"ok": True, "text": report.text}
    else:
        frame = {"ok": False, "code": report.code}
    return json.dumps(frame, ensure_ascii=False, sort_keys=True).encode("utf-8")


def decode_report(raw: Any) -> ParserReport | None:
    """Decode one child report, or return ``None`` for a bounded refusal.

    A report is trusted only when it is a JSON object with exactly one of the two
    bounded shapes and a reason code that matches the bounded grammar. Anything
    else — a traceback string, a partial write, an extra key, oversized text —
    is refused here so it can never be projected as a parse outcome.
    """

    if not isinstance(raw, (bytes, bytearray)):
        return None
    data = bytes(raw)
    if not data:
        return None
    try:
        frame = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(frame, dict) or not isinstance(frame.get("ok"), bool):
        return None
    if frame["ok"] is True:
        if set(frame) != REPORT_SUCCESS_KEYS:
            return None
        text = frame["text"]
        if not isinstance(text, str) or len(text) > MAX_DOCUMENT_CHARS:
            return None
        return ParserReport(ok=True, text=text)
    if set(frame) != REPORT_REJECTION_KEYS or not is_bounded_reason_code(frame["code"]):
        return None
    return ParserReport(ok=False, code=frame["code"])
