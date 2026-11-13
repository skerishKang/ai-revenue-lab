"""Build the fixed session v1 helper document without persisting input values."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re

_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_PREFIX = re.compile(r"[0-9a-f]{8}\Z")
_KEYS = {"enter", "ctrl_c", "ctrl_d", "ctrl_z", "tab", "esc", "up", "down"}
_FIELDS = {
    "start": {"shell", "command", "terminal", "cols", "rows", "keep_minutes", "input_encoding", "wait_ms"},
    "input": {"session", "enter", "key", "secret", "offset", "length", "wait_ms"},
    "read": {"session", "offset", "length", "wait_ms"},
    "stop": {"session", "offset", "length"},
    "status": set(),
}


class SessionRequestRefused(ValueError):
    def __init__(self, code: str = "pc_session_bad_request") -> None:
        super().__init__(code)
        self.code = code


def session_material(command_text: str | None) -> dict | None:
    try:
        value = json.loads(command_text or "")
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) and value.get("shell") == "session" else None


def session_operation(material: dict) -> dict:
    try:
        encoded = material["command"]
        if not isinstance(encoded, str):
            raise ValueError
        value = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except (KeyError, ValueError, TypeError, UnicodeError) as exc:
        raise SessionRequestRefused() from exc
    if not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1:
        raise SessionRequestRefused()
    op = value.get("op")
    if not isinstance(op, str) or op not in _FIELDS or set(value) - (_FIELDS[op] | {"v", "op"}):
        raise SessionRequestRefused()
    return value


def _integer(value: object, low: int, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def usable_input_text(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 4000 or "\x00" in value or "\r" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def prepare_session_command(
    material: dict, *, dispatch_id: str, text: str | None, background: bool,
) -> str:
    """Return a completed base64 helper document; the queued material stays intact.

    Only the queue marker is durable. A one-shot value is checked against that
    marker here, immediately before framing, and is never copied into a dispatch.
    """
    if (not isinstance(dispatch_id, str) or not dispatch_id.startswith("dsp_")
            or _SESSION.fullmatch(dispatch_id[4:]) is None):
        raise SessionRequestRefused()
    if (set(material) - {"shell", "command", "cwd", "timeout_seconds", "distro", "session_input", "session_scope"}
            or type(material.get("timeout_seconds")) is not int
            or material["timeout_seconds"] != 0 or material.get("distro") is not None):
        raise SessionRequestRefused()
    operation = session_operation(material)
    op = operation["op"]
    scope = material.get("session_scope")
    if op == "status":
        if not isinstance(scope, str) or _SESSION.fullmatch(scope) is None:
            raise SessionRequestRefused()
    elif scope is not None:
        raise SessionRequestRefused()
    if op != "start" and material.get("cwd") is not None:
        raise SessionRequestRefused()
    if op in {"input", "read", "stop"}:
        session = operation.get("session")
        if not isinstance(session, str) or _SESSION.fullmatch(session) is None:
            raise SessionRequestRefused()
    for key, low, high in (("wait_ms", 0, 10000), ("length", 1, 65536), ("offset", 0, None),
                           ("cols", 20, 500), ("rows", 5, 200), ("keep_minutes", 1, 480)):
        if key in operation and not _integer(operation[key], low, high):
            raise SessionRequestRefused()
    for key in ("terminal", "enter", "secret"):
        if key in operation and type(operation[key]) is not bool:
            raise SessionRequestRefused()
    if op == "start":
        if (operation.get("shell", "powershell") not in ("powershell", "cmd", "bash")
                or not isinstance(operation.get("command", ""), str)
                or operation.get("input_encoding", "utf-8") not in ("utf-8", "cp949")):
            raise SessionRequestRefused()
    marker = material.get("session_input")
    if op != "input":
        if marker is not None or text is not None:
            raise SessionRequestRefused()
    else:
        # Background job receipts serialize their dispatch. Inputs must never
        # enter that path, even if a malformed server projection asks for it.
        if background:
            raise SessionRequestRefused("pc_session_input_uncertain")
        key = operation.get("key")
        if key is not None and (not isinstance(key, str) or key not in _KEYS):
            raise SessionRequestRefused()
        if marker is None:
            if text is not None or key is None:
                raise SessionRequestRefused("pc_session_input_uncertain")
        else:
            if not usable_input_text(text) or not isinstance(marker, dict):
                raise SessionRequestRefused("pc_session_input_uncertain")
            raw = text.encode("utf-8")
            secret = operation.get("secret", False)
            expected = {"ref", "chars", "bytes"} | (set() if secret else {"sha256_prefix"})
            ref = marker.get("ref")
            if (set(marker) != expected or not isinstance(ref, str) or _SESSION.fullmatch(ref) is None
                    or not _integer(marker.get("chars"), 1, 4000) or marker["chars"] != len(text)
                    or not _integer(marker.get("bytes"), 1, 16000) or marker["bytes"] != len(raw)):
                raise SessionRequestRefused("pc_session_input_uncertain")
            if not secret:
                prefix = marker.get("sha256_prefix")
                if (not isinstance(prefix, str) or _PREFIX.fullmatch(prefix) is None
                        or prefix != hashlib.sha256(raw).hexdigest()[:8]):
                    raise SessionRequestRefused("pc_session_input_uncertain")
            operation["text_b64"] = base64.b64encode(raw).decode("ascii")
    try:
        encoded = base64.b64encode(json.dumps(operation, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
    except (ValueError, UnicodeError) as exc:
        raise SessionRequestRefused() from exc
    if len(encoded) > 50000:
        raise SessionRequestRefused()
    return encoded


def session_enabled(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get("PADIEM_MCP_PC_SESSION_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}


def background_session_error(dispatch) -> str | None:
    """Reject one-shot input before the background manager can serialize it."""
    material = session_material(dispatch.command_text)
    if dispatch.session_input_text is not None or (material is not None and "session_input" in material):
        return "pc_session_input_uncertain"
    if material is not None:
        try:
            if session_operation(material)["op"] == "input":
                return "pc_session_input_uncertain"
        except SessionRequestRefused:
            return "pc_session_bad_request"
    return None


def session_transport_failure(material: dict) -> str:
    if material.get("shell") == "session":
        try:
            # This is the completed frame, whose input now has text_b64.
            operation = json.loads(base64.b64decode(material.get("command", ""), validate=True))
            if isinstance(operation, dict) and operation.get("op") == "input":
                return "pc_session_input_uncertain"
        except (ValueError, TypeError):
            pass
    return "user_session_unavailable"
