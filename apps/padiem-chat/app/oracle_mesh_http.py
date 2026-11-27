"""Oracle Mesh HTTP validation and response helpers."""
from __future__ import annotations

import contextvars
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .oracle_mesh_contract import (
    ORACLE_MESH_CHANNEL_HEADER,
    _MAX_BODY_BYTES,
    _MAX_PATH_VALUE_CHARS,
    _MAX_RESULT_BODY_BYTES,
    _RESULT_KEYS,
    _RESULT_OPTIONAL_KEYS,
    _SAFE_REF_CHARS,
)
from .request_telemetry import emit_stage_event


_NO_STORE = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _response(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(dict(payload), status_code=status, headers=_NO_STORE)


def _error(status: int, code: str, message: str | None = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code}
    if message is not None:
        error["message"] = message
    return _response({"ok": False, "error": error}, status)


#: #6923: the rule the last body reader stopped at, read back by ``_invalid_body``
#: so the journal names it while the public code stays ``oracle_mesh_invalid_body``.
_BODY_REFUSAL: contextvars.ContextVar[str] = contextvars.ContextVar(
    "oracle_mesh_body_refusal", default="")


def _refused(reason: str) -> None:
    """Record the rule a body reader stopped at and answer its ``None``."""
    _BODY_REFUSAL.set(reason)
    return None


def _invalid_body(route: str, reason: str | None = None) -> JSONResponse:
    """#6923: one ``ai_stage`` line per 400 naming the route and the rule.

    11-04 21:44 and 11-05 15:12 KST the executor's result submits were refused
    as ``oracle_mesh_invalid_body`` while the two sides ran different versions,
    and nothing in the journal said which field. The response is unchanged; the
    journal carries the route, the rule label and the request id only — never a
    value from the body.
    """
    label = reason if reason is not None else (_BODY_REFUSAL.get() or "body")
    _BODY_REFUSAL.set("")
    emit_stage_event(stage="mesh." + route + ".validate", outcome="error",
                     duration_ms=0, code=label)
    return _error(400, "oracle_mesh_invalid_body")


def _read_json(raw: bytes, keys: frozenset, limit: int = _MAX_BODY_BYTES,
               optional: frozenset = frozenset()) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return _refused("json_decode")
    if type(value) is not dict:
        return _refused("body_shape")
    names = set(value)
    # Required keys must all be present; optional keys (the desktop screenshot
    # blob, absent on input-only turns) may be present; anything else refuses.
    if not keys <= names <= keys | optional:
        return _refused("keys_missing" if keys - names else "keys_unknown")
    return value


def _text_value(value: Any, limit: int = _MAX_PATH_VALUE_CHARS) -> str | None:
    """A path, a file name or a command: any language, no control characters.

    Windows paths, Korean file names and UTF-8 commands are ordinary input, so
    the ASCII-only reference alphabet does not apply here. The bound is the
    documented maximum path length plus "no control characters"; nothing else
    is restricted.
    """
    if (
        not isinstance(value, str) or not value or len(value) > limit
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        return None
    return value


def _ref(value: Any, limit: int = 1024) -> str | None:
    if (
        not isinstance(value, str) or not value or len(value) > limit
        or any(ch not in _SAFE_REF_CHARS for ch in value)
    ):
        return None
    return value


async def _read_body(
    request: Request, keys: frozenset, limit: int = _MAX_BODY_BYTES,
    optional: frozenset = frozenset(),
) -> dict[str, Any] | None:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _refused("content_type")
    try:
        declared = request.headers.get("content-length")
        if limit is not None and declared is not None and (
                not declared.isdecimal() or int(declared) > limit):
            return _refused("content_length")
        raw = await request.body()
        if limit is not None and len(raw) > limit:
            return _refused("body_too_large")
    except Exception:
        return _refused("body_read")
    return _read_json(raw, keys, limit, optional)


async def _read_result_body(
    request: Request,
) -> tuple[dict[str, Any], bytes | None] | None:
    """Read one result wire: legacy JSON, or the #4379 binary frame.

    The binary frame is ``4-byte big-endian header length + UTF-8 JSON header
    + raw bytes``: a screenshot travels as the bytes it is, never as a base64
    string. The JSON shape stays accepted so an executor that has not been
    restarted keeps its held result deliverable after this deploy. The second
    element is the raw body, or None when the JSON shape was used.
    """
    media_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if media_type != "application/octet-stream":
        wire = await _read_body(
            request, _RESULT_KEYS, limit=_MAX_RESULT_BODY_BYTES,
            optional=_RESULT_OPTIONAL_KEYS,
        )
        return None if wire is None else (wire, None)
    try:
        declared = request.headers.get("content-length")
        if (
            _MAX_RESULT_BODY_BYTES is not None and declared is not None and (
                not declared.isdecimal() or int(declared) > _MAX_RESULT_BODY_BYTES
            )
        ):
            return _refused("content_length")
        raw = await request.body()
    except Exception:
        return _refused("body_read")
    if len(raw) < 6 or (
        _MAX_RESULT_BODY_BYTES is not None and len(raw) > _MAX_RESULT_BODY_BYTES
    ):
        return _refused("frame_size")
    header_size = int.from_bytes(raw[:4], "big")
    # A frame without its own body is not a capture; the note-only shape
    # stays JSON. The declared header size can never exceed the body it sits in.
    if not 0 < header_size or 4 + header_size >= len(raw):
        return _refused("frame_header_size")
    header = _read_json(
        raw[4:4 + header_size], _RESULT_KEYS, limit=_MAX_RESULT_BODY_BYTES,
        optional=_RESULT_OPTIONAL_KEYS,
    )
    if header is None:
        return None
    return header, raw[4 + header_size:]


def _channel_source(request: Request) -> OracleMeshReturnSource | None:
    source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if getattr(source, "configured", False) is not True:
        return None
    return source


def _channel_proof(request: Request, source: OracleMeshReturnSource) -> bool:
    presented = request.headers.get(ORACLE_MESH_CHANNEL_HEADER, "")
    if not isinstance(presented, str) or len(presented) > 512:
        return False
    return source.check_channel_secret(presented)


def _watch_read_proof(request: Request, source: OracleMeshReturnSource) -> bool:
    """The read-only proof: the watch secret or the channel secret, nothing else.

    Same header, same 512-character refusal and the same constant-time comparison as
    the channel proof. Used by lane-status only.
    """
    presented = request.headers.get(ORACLE_MESH_CHANNEL_HEADER, "")
    if not isinstance(presented, str) or len(presented) > 512:
        return False
    return source.check_read_secret(presented)
