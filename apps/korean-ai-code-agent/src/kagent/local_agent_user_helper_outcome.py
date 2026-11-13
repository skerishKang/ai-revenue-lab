"""Interpret the user helper's final frame after the tagged transport accepts it."""
from __future__ import annotations

import json
import base64
import re
from dataclasses import replace

from .local_agent_user_helper_guards import USER_SESSION_UNAVAILABLE


def parse_user_helper_outcome(raw: bytes) -> OracleMeshExecutionOutcome:
    from .local_agent_oracle_mesh_executor import OracleMeshExecutionOutcome
    import json as _json
    text = raw.decode("utf-8", errors="replace").strip() if isinstance(raw, (bytes, bytearray)) else str(raw).strip()
    if not text:
        return OracleMeshExecutionOutcome(termination="no_reply", exit_code=None, body=b"")
    try:
        obj = _json.loads(text)
    except Exception:
        # pipe-unavailable marker emitted by PS client
        if text.startswith(USER_SESSION_UNAVAILABLE):
            return OracleMeshExecutionOutcome(termination="exited", exit_code=1,
                body=_json.dumps({"ok": False, "error_code": USER_SESSION_UNAVAILABLE, "detail": "helper pipe is not available"}, ensure_ascii=True).encode("utf-8"))
        return OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=raw if isinstance(raw,(bytes,bytearray)) else text.encode("utf-8","replace"))
    if not isinstance(obj, dict):
        return OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=raw if isinstance(raw,(bytes,bytearray)) else text.encode("utf-8","replace"))
    status = obj.get("status")
    if status == "cancelled":
        # The helper ended the child because the owner stopped the dispatch
        # or the SYSTEM client went away. That is a stop, not a silent reply.
        return OracleMeshExecutionOutcome(termination="cancelled", exit_code=None, body=b"")
    if status == "ok":
        stdout = obj.get("stdout_b64")
        try:
            body = __import__("base64").b64decode(stdout) if isinstance(stdout,str) else b""
        except Exception:
            body = b""
        if not body:
            # #7105: a failing stage-2 command often writes only to stderr.
            # An empty body with a non-zero code would read as "no answer".
            stderr = obj.get("stderr_b64")
            try:
                body = __import__("base64").b64decode(stderr) if isinstance(stderr, str) else b""
            except Exception:
                body = b""
        code = obj.get("exit_code")
        if isinstance(code, bool) or not isinstance(code, int): code = 0
        return OracleMeshExecutionOutcome(termination="exited", exit_code=code, body=body)
    err = obj.get("error_code") if isinstance(obj.get("error_code"), str) else "user_helper_refused"
    detail = obj.get("detail") if isinstance(obj.get("detail"), str) else ""
    return OracleMeshExecutionOutcome(termination="exited", exit_code=1,
        body=_json.dumps({"ok": False, "error_code": err, "detail": detail}, ensure_ascii=True).encode("utf-8"))

def session_refused(code: str) -> OracleMeshExecutionOutcome:
    from .local_agent_oracle_mesh_executor import OracleMeshExecutionOutcome
    return OracleMeshExecutionOutcome(
        termination="not_executed", exit_code=1,
        body=json.dumps({"ok": False, "error_code": code}, separators=(",", ":")).encode("utf-8"),
    )


def parse_session_helper_outcome(raw: bytes, material: dict, scope: str | None, request_id: str):
    """Session transport errors cannot persist a request or echoed script.

    Ordinary command parsing keeps its permissive legacy behavior. Sessions
    require a v1 reply before any text enters recovery storage or submission.
    """
    from .local_agent_session_request import session_transport_failure
    refused = session_refused(session_transport_failure(material))
    if raw.strip().startswith(b"user_session_unavailable:"):
        return session_refused("user_session_unavailable")
    try:
        frame = json.loads(raw)
        if not isinstance(frame, dict):
            return refused
        if frame.get("request_id") != request_id:
            return refused
        if frame.get("status") == "cancelled":
            return parse_user_helper_outcome(b'{"status":"cancelled"}')
        if frame.get("status") != "ok":
            code = frame.get("error_code")
            return session_refused(code) if code in {
                "user_session_unavailable", "user_helper_refused", "user_helper_timeout"
            } else refused
        body = base64.b64decode(frame["stdout_b64"], validate=True)
        first, _, output = body.partition(b"\n")
        header = json.loads(first)
        operation = json.loads(base64.b64decode(material["command"], validate=True))
        if (not isinstance(header, dict) or type(header.get("v")) is not int or header["v"] != 1
                or type(header.get("ok")) is not bool or header.get("op") != operation["op"]):
            return refused
        if type(frame.get("exit_code")) is not int or frame["exit_code"] != (0 if header["ok"] else 1):
            return refused
        outcome = parse_user_helper_outcome(raw)
        if scope is not None:
            return scoped_status_outcome(outcome, scope)
        expected = operation.get("session") if operation["op"] != "start" else request_id[4:]
        sid = header.get("session")
        if (sid is not None and (not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid))
                or sid != expected and (header["ok"] or sid is not None)):
            return refused
        codes = {None, "pc_session_not_found", "pc_session_ended", "pc_session_expired",
                 "pc_session_limit", "pc_session_start_failed", "pc_session_bad_request",
                 "pc_session_input_timeout", "pc_session_key_unsupported"}
        if (header.get("code") not in codes or header.get("prompt_kind") not in (None, "secret")
                or header.get("waiting_hint") not in (None, "input")):
            return refused
        if (any(key in header and type(header[key]) is not bool for key in ("alive", "ends_with_newline"))
                or header.get("ended") not in (None, "exited", "stopped", "expired")
                or header.get("exit_code") is not None and type(header["exit_code"]) is not int
                or "backend" in header and header["backend"] not in ("pipe", "conpty")
                or any(key in header and (type(header[key]) is not int or not 0 <= header[key] < 2**63)
                       for key in ("offset", "next_offset", "end_offset", "dropped_bytes", "idle_ms"))):
            return refused
        projected = {key: header[key] for key in (
            "v", "ok", "code", "op", "session", "alive", "ended", "exit_code", "offset",
            "next_offset", "end_offset", "dropped_bytes", "idle_ms", "ends_with_newline", "backend",
            "prompt_kind", "waiting_hint") if key in header}
        return replace(outcome, body=json.dumps(projected, separators=(",", ":")).encode()
                       + b"\n" + output)
    except (ValueError, TypeError, KeyError, AttributeError):
        return refused


def scoped_status_outcome(outcome, scope: str | None):
    """Remove other sessions before a result can enter recovery files or the DB.

    Status v1 enumerates the whole helper. The authenticated server supplies an
    outer scope for the one job its caller owns; that scope never reaches the
    helper. Unknown fields and output lines are not part of a status projection.
    """
    if scope is None:
        return outcome
    try:
        header = json.loads(outcome.body.split(b"\n", 1)[0])
    except (ValueError, TypeError, AttributeError):
        return session_refused("pc_session_bad_request")
    if not isinstance(header, dict):
        return session_refused("pc_session_bad_request")
    if "v" not in header:
        code = header.get("error_code")
        if code in ("user_session_unavailable", "user_helper_refused", "user_helper_timeout"):
            return replace(outcome, body=json.dumps({"ok": False, "error_code": code}).encode())
        return session_refused("pc_session_bad_request")
    if (type(header.get("v")) is not int or header["v"] != 1 or header.get("op") != "status"
            or header.get("ok") is not True or header.get("code") is not None):
        return session_refused("pc_session_bad_request")
    if (type(header.get("limit")) is not int or header["limit"] != 4
            or not isinstance(header.get("features"), list) or not isinstance(header.get("sessions"), list)):
        return session_refused("pc_session_bad_request")
    rows = []
    for row in header["sessions"]:
        if not isinstance(row, dict) or row.get("session") != scope:
            continue
        if (type(row.get("alive")) is not bool or row.get("ended") not in (None, "exited", "stopped", "expired")
                or (row.get("exit_code") is not None and type(row["exit_code"]) is not int)
                or row.get("backend") not in ("pipe", "conpty")
                or any(type(row.get(key)) is not int or row[key] < 0 for key in ("end_offset", "idle_ms"))):
            return session_refused("pc_session_bad_request")
        rows.append({key: row.get(key) for key in
                     ("session", "alive", "ended", "exit_code", "backend", "end_offset", "idle_ms")})
    projected = {"v": 1, "ok": True, "code": None, "op": "status", "limit": 4,
                 "features": [value for value in header["features"]
                              if isinstance(value, str) and value in {"pipe", "conpty", "secret_mask"}],
                 "sessions": rows}
    return replace(outcome, body=json.dumps(projected, separators=(",", ":")).encode() + b"\n")
