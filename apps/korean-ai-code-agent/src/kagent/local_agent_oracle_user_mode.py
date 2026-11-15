"""User-session command execution and named-job cleanup for the mesh executor.

The executor keeps result interpretation and public method names; this module owns the
PowerShell client preparation and invocation without importing executor classes.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from . import local_agent_mesh_command_phases as phases
from .local_agent_user_helper_guards import USER_SESSION_UNAVAILABLE
from .local_agent_session_request import (
    SessionRequestRefused,
    prepare_session_command,
    session_transport_failure,
)


@dataclass(frozen=True, slots=True)
class UserModeRun:
    material: dict
    shell_name: str
    status_scope: str | None
    request_id: str
    termination: str
    output: bytes
    phase: Callable[[str], None]


def run_user_mode_command(
    executor, dispatch, *, additional_cancel_probe, outcome_type, channel_refused,
) -> UserModeRun | Any:
    """Prepare and run one user-mode client, returning data or an early outcome."""
    self = executor
    if self._command_port is None:
        raise channel_refused("command execution is not configured")
    import json as _json
    node_ref = dispatch.node_ref
    raw = getattr(dispatch, "command_text", "") or ""
    try:
        mat = _json.loads(raw)
        if not isinstance(mat, dict):
            raise ValueError("not object")
    except Exception:
        return outcome_type(
            termination="not_executed", exit_code=None,
            body=_json.dumps({"ok": False, "error_code": USER_SESSION_UNAVAILABLE,
                              "detail": "user mode request unavailable"},
                             ensure_ascii=True).encode("utf-8"),
        )
    status_scope = mat.get("session_scope") if mat.get("shell") == "session" else None
    if mat.get("shell") == "session":
        if not getattr(self, "_session_enabled", False):
            return self._session_refused("pc_session_unsupported")
        try:
            command = prepare_session_command(
                mat, dispatch_id=dispatch.dispatch_id,
                text=dispatch.session_input_text, background=dispatch.background,
            )
        except SessionRequestRefused as exc:
            return self._session_refused(exc.code)
        mat = {key: value for key, value in mat.items()
               if key not in {"session_input", "session_scope"}}
        mat["command"] = command
    req_id = f"req_{dispatch.dispatch_id.replace('dsp_', '')[:32].ljust(32, '0')}"
    shell_name = mat.get("shell") if isinstance(mat.get("shell"), str) else "whoami"
    cmd = mat.get("command") if isinstance(mat.get("command"), str) else ""
    cwd = mat.get("cwd") if isinstance(mat.get("cwd"), str) else None
    distro = mat.get("distro") if isinstance(mat.get("distro"), str) else None
    timeout_s = mat.get("timeout_seconds")
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool):
        timeout_s = 30
    try:
        ps = self.build_user_helper_pipe_client_ps(
            request_id=req_id, shell=shell_name, command=cmd, cwd=cwd,
            timeout_seconds=timeout_s, distro=distro,
            cancel_poll_url=getattr(dispatch, "cancel_poll_url", None),
            cancel_token=getattr(dispatch, "cancel_token", None),
            dispatch_id=getattr(dispatch, "dispatch_id", None),
        )
    except Exception:
        return outcome_type(
            termination="not_executed", exit_code=None,
            body=_json.dumps({"ok": False, "error_code": USER_SESSION_UNAVAILABLE,
                              "detail": "user mode client unavailable"},
                             ensure_ascii=True).encode("utf-8"),
        )

    owner_cancel = self._cancel_probe(dispatch)

    def cancelled():
        return ((callable(additional_cancel_probe) and additional_cancel_probe())
                or owner_cancel())

    started = time.monotonic()
    self._trace_command(dispatch, phases.START, started)

    def phase(phase_name: str) -> None:
        self._trace_command(dispatch, phase_name, started)

    try:
        observed = self._command_port.run_command(
            node_ref=node_ref, command=ps, timeout_seconds=None,
            cancel_probe=cancelled, phase_observer=phase,
            dispatch_id=getattr(dispatch, "dispatch_id", None),
            deliver_as_file=True,
        )
    except Exception:
        self._trace_command(dispatch, phases.ERROR, started, error_type="port_failed")
        return outcome_type(
            termination="exited", exit_code=1,
            body=_json.dumps({"ok": False, "error_code": session_transport_failure(mat),
                              "detail": "helper pipe is not available"},
                             ensure_ascii=True).encode("utf-8"),
        )
    term = getattr(observed, "termination", "no_reply")
    out = getattr(observed, "output", b"") or b""
    if not isinstance(out, (bytes, bytearray)):
        out = str(out).encode("utf-8", "replace")
    self._trace_command(
        dispatch, phases.RESULT, started, termination=term, output_bytes=len(bytes(out)),
    )
    return UserModeRun(
        material=mat, shell_name=shell_name, status_scope=status_scope,
        request_id=req_id, termination=term, output=bytes(out), phase=phase,
    )


def end_user_mode_job(
    executor, dispatch, phase: Callable[[str], None],
) -> bool:
    """End the stopped user-mode dispatch's named job, best effort and never raised."""
    self = executor
    dispatch_id = getattr(dispatch, "dispatch_id", None)
    node_ref = getattr(dispatch, "node_ref", None)
    if not dispatch_id or not node_ref or self._command_port is None:
        return False
    ender = getattr(self._command_port, "end_dispatch_job", None)
    if not callable(ender):
        return False
    try:
        return bool(ender(
            node_ref=node_ref, dispatch_id=dispatch_id, phase_observer=phase,
        ))
    except Exception:
        return False
