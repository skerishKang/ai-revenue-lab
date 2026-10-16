"""#4139 — Oracle management-host MeshCentral read return (no page, one POST route).

The Windows Resident trial stays a separate Draft experiment: nothing here
executes on, or requires, the trial PC. This route returns an Oracle
management-host execution — the official ``meshctrl.js`` client against the
local MeshCentral server — to the original Claw conversation that requested it.

Order per request (each step server-derived, fail closed):

1. verified owner session (B54 canonical session + CSRF),
2. memory workspace for the owner,
3. active enrollment consent for (session, device) via Identity,
4. owner-scoped device binding via the Broker directory (account/workspace
   from consent, never the browser; revoked/expired refused),
5. existing stored conversation run via history (owner + workspace match),
6. existing stored command correlation for the run, complete with the
   broker-minted evidence (a pre-write row still waiting on admission stays
   pending here; the projection fills it once),
7. deployment mesh-ownership match: (consent account, wire device, wire
   Mesh node) must equal exactly one deployment-owned row,
8. result-package verification: exact correlation equality with the stored
   row, clean exited/0 execution, bounded UTF-8 text with matching SHA-256,
9. one idempotent append through the existing history authority, under the
   same stable message id the device-acknowledged projection uses.

What this route is NOT: it enqueues nothing, admits nothing, acknowledges
nothing, and writes no broker state. The destination conversation is read
from the origin run row, never taken from the caller. The executor identity
(``oracle_management_host``) and the absence of a broker acknowledgment are
reported explicitly: a management-host return never poses as a
device-acknowledged one.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .claw_memory_routes import _resolve_memory_workspace
from .claw_local_task_result_projection import result_message_id
from .control_plane_identity import IdentityBridgeError
from .history import HistoryError, HistoryForbidden, validate_conversation_id

ORACLE_MESH_READ_RETURN_PATH = "/api/claw/connector/mesh-reads/return"
#: Deployment-owned ownership map, read from Worker env by the worker root.
#: JSON list of {account_ref, device_id, node_ref}. Absent or invalid keeps
#: the source unconfigured; the route stays unmounted.
ORACLE_MESH_OWNERSHIP_MAP_ENV = "ORACLE_MESH_OWNERSHIP_MAP"
_MAX_BODY_BYTES = 8192
_BODY_KEYS = frozenset({
    "device_id", "command_id", "run_id", "tool_request_ref", "request_id",
    "revision_ref", "evidence_ref", "request_fingerprint", "termination",
    "exit_code", "node_ref", "content_utf8", "content_sha256", "content_bytes",
})
_SAFE_REF_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:@+-"
)
_MAX_FILE_TEXT_BYTES = 768
_EXECUTOR = "oracle_management_host"


class UnconfiguredOracleMeshReturnSource:
    """Fail-closed until the Worker root composes the deployment map."""

    configured = False


class OracleMeshReturnSource:
    """Deployment-owned (account, device, Mesh node) authorization rows.

    The map is supplied by the Worker root from deployment configuration, never
    from a request. Each row pins which PADIEM account may return reads for
    which canonical device binding through which MeshCentral node. The broker
    binding resolve (live, account-scoped) still gates every request; this map
    only adds the Mesh-device ownership the broker never sees.
    """

    configured = True

    def __init__(self, mapping: Any) -> None:
        if not isinstance(mapping, (list, tuple)) or not mapping:
            raise TypeError("oracle mesh ownership mapping is required")
        rows = []
        for entry in mapping:
            if not isinstance(entry, dict):
                raise TypeError("oracle mesh ownership row must be a mapping")
            row = {
                name: entry.get(name)
                for name in ("account_ref", "device_id", "node_ref")
            }
            for name, value in row.items():
                if (
                    not isinstance(value, str) or not value
                    or len(value) > 256
                    or any(ch not in _SAFE_REF_CHARS for ch in value)
                ):
                    raise TypeError(f"oracle mesh ownership {name} invalid")
            rows.append(row)
        self._rows = rows

    def authorize(
        self, *, account_ref: str, device_id: str, node_ref: str,
    ) -> bool:
        """Exactly one deployment row must own this (account, device, node)."""
        return sum(
            1
            for row in self._rows
            if row["account_ref"] == account_ref
            and row["device_id"] == device_id
            and row["node_ref"] == node_ref
        ) == 1


def build_oracle_mesh_return_source(mapping: Any) -> OracleMeshReturnSource | None:
    """Worker-root composition only; missing/invalid mapping is unconfigured."""
    try:
        return OracleMeshReturnSource(mapping)
    except Exception:
        return None


def build_oracle_mesh_return_source_from_env(env: Any) -> OracleMeshReturnSource | None:
    """Read the deployment ownership map from Worker env. Fail-closed None."""
    from .worker_config import binding_value

    try:
        raw = binding_value(env, ORACLE_MESH_OWNERSHIP_MAP_ENV)
    except Exception:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        mapping = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return build_oracle_mesh_return_source(mapping)


_NO_STORE = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _response(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(dict(payload), status_code=status, headers=_NO_STORE)


def _error(status: int, code: str) -> JSONResponse:
    return _response({"ok": False, "error": {"code": code}}, status)


def _read_body(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if type(value) is not dict or set(value) != _BODY_KEYS:
        return None
    for key in (
        "device_id", "command_id", "run_id", "tool_request_ref", "request_id",
        "revision_ref", "evidence_ref", "node_ref", "content_sha256",
    ):
        item = value.get(key)
        if (
            not isinstance(item, str) or not item or len(item) > 1024
            or any(ch not in _SAFE_REF_CHARS for ch in item)
        ):
            return None
    fingerprint = value.get("request_fingerprint")
    if (
        not isinstance(fingerprint, str) or len(fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in fingerprint)
    ):
        return None
    if value.get("termination") != "exited" or value.get("exit_code") != 0:
        return None
    text = value.get("content_utf8")
    if not isinstance(text, str):
        return None
    byte_count = value.get("content_bytes")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int):
        return None
    return value


def _verified_text(value: dict[str, Any]) -> str | None:
    """Apply the projection's own content gate; None when the package lies."""
    text = value["content_utf8"]
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if (
        len(raw) > _MAX_FILE_TEXT_BYTES
        or value["content_bytes"] != len(raw)
        or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text)
        or value["content_sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        return None
    return text


async def oracle_mesh_read_return(request: Request) -> JSONResponse:
    """Owner-carried Oracle result: verify everything server-side, append once."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "oracle_mesh_unsupported_media_type")
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or int(declared) > _MAX_BODY_BYTES):
            return _error(413, "oracle_mesh_request_too_large")
        raw = await request.body()
        if len(raw) > _MAX_BODY_BYTES:
            return _error(413, "oracle_mesh_request_too_large")
    except Exception:
        return _error(400, "oracle_mesh_invalid_body")
    wire = _read_body(raw)
    if wire is None:
        return _error(400, "oracle_mesh_invalid_body")

    return await dispatch_oracle_mesh_read_return(request, wire)


async def dispatch_oracle_mesh_read_return(
    request: Request, wire: dict[str, Any]
) -> JSONResponse:
    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return denial if denial is not None else _error(401, "canonical_session_required")
    uid = current_user_id(request)
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        return _error(503, "oracle_mesh_workspace_unavailable")
    if not workspace_id:
        return _error(503, "oracle_mesh_workspace_unavailable")

    mesh_source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if getattr(mesh_source, "configured", False) is not True:
        return _error(503, "oracle_mesh_unconfigured")
    broker_source = getattr(request.app.state, "connector_txt_read_source", None)
    if getattr(broker_source, "configured", False) is not True:
        return _error(503, "oracle_mesh_unconfigured")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None)):
        return _error(503, "oracle_mesh_unconfigured")
    history_store = getattr(request.app.state, "history_store", None)
    if not callable(getattr(history_store, "get_claw_run", None)):
        return _error(503, "oracle_mesh_unconfigured")
    if not callable(getattr(history_store, "get_local_task_correlation", None)):
        return _error(503, "oracle_mesh_unconfigured")

    try:
        consent = await identity.resolve_connector_enrollment_consent_for_device(
            session_id=session.session_id, device_id=wire["device_id"],
        )
    except Exception:
        return _error(403, "oracle_mesh_consent_required")
    if (
        not isinstance(consent, dict)
        or consent.get("device_id") != wire["device_id"]
        or not isinstance(consent.get("account_ref"), str)
        or not consent["account_ref"]
        or not isinstance(consent.get("workspace_ref"), str)
        or not consent["workspace_ref"]
        or consent.get("withdrawn_at") is not None
    ):
        return _error(403, "oracle_mesh_consent_required")
    account_ref = consent["account_ref"]
    connector_workspace_ref = consent["workspace_ref"]

    try:
        device = await broker_source.resolve_device_binding(
            account_ref=account_ref, workspace_ref=connector_workspace_ref,
            device_id=wire["device_id"],
        )
    except IdentityBridgeError as exc:
        status = exc.status_code if isinstance(exc.status_code, int) else 503
        if status == 404:
            return _error(404, "oracle_mesh_device_unbound")
        if status == 403:
            return _error(403, "oracle_mesh_device_not_usable")
        return _error(503, "oracle_mesh_broker_unavailable")
    except Exception:
        return _error(503, "oracle_mesh_broker_unavailable")
    if (
        not isinstance(device, dict)
        or device.get("device_id") != wire["device_id"]
        or ("account_ref" in device and device["account_ref"] != account_ref)
        or ("workspace_ref" in device and device["workspace_ref"] != connector_workspace_ref)
    ):
        return _error(403, "oracle_mesh_device_not_usable")

    if not mesh_source.authorize(
        account_ref=account_ref,
        device_id=wire["device_id"],
        node_ref=wire["node_ref"],
    ):
        return _error(403, "oracle_mesh_ownership_unverified")

    try:
        run_row = await history_store.get_claw_run(uid, wire["run_id"])
    except Exception:
        return _error(503, "oracle_mesh_run_unavailable")
    if (
        not isinstance(run_row, dict)
        or run_row.get("run_id") != wire["run_id"]
        or run_row.get("workspace_id") != workspace_id
        or not isinstance(run_row.get("conversation_id"), str)
        or not run_row["conversation_id"]
    ):
        return _error(404, "oracle_mesh_run_unavailable")
    conversation_id = validate_conversation_id(run_row["conversation_id"])
    if not conversation_id:
        return _error(404, "oracle_mesh_run_unavailable")

    try:
        bound = await history_store.get_local_task_correlation(uid, wire["run_id"])
    except Exception:
        return _error(503, "oracle_mesh_correlation_unavailable")
    if (
        not isinstance(bound, dict)
        or any(not isinstance(bound.get(name), str) or not bound[name] for name in (
            "command_id", "tool_request_ref", "request_id", "revision_ref",
            "evidence_ref", "request_fingerprint",
        ))
    ):
        # No fully-admitted command is bound to this run yet: the Oracle
        # return is valid only for broker-admitted commands, never ahead of
        # admission. The trigger-time pre-write (evidence unknown) stays
        # pending until the projection fills it once.
        return _error(409, "oracle_mesh_correlation_unbound")
    for name in (
        "command_id", "run_id", "tool_request_ref", "request_id",
        "revision_ref", "evidence_ref", "request_fingerprint",
    ):
        expected = bound[name] if name != "run_id" else wire["run_id"]
        if wire[name] != expected:
            return _error(409, "oracle_mesh_correlation_mismatch")

    verified_text = _verified_text(wire)
    if verified_text is None:
        return _error(400, "oracle_mesh_content_unverified")

    message_id = result_message_id(
        conversation_id=conversation_id,
        command_id=wire["command_id"],
        revision_ref=wire["revision_ref"],
    )
    content = "PC 파일 읽기 결과:\n" + (verified_text if verified_text else "(빈 파일)")
    if len(content) > 1_000:
        return _error(400, "oracle_mesh_content_unverified")
    try:
        appended = await history_store.append_local_task_result(
            user_id=uid,
            run_id=wire["run_id"],
            message_id=message_id,
            summary="exited/0",
            content=content,
            status="completed",
        )
    except HistoryError as exc:
        if isinstance(exc, HistoryForbidden):
            return _error(403, "oracle_mesh_conversation_forbidden")
        return _error(503, "oracle_mesh_append_unavailable")
    except Exception:
        return _error(503, "oracle_mesh_append_unavailable")
    return _response({
        "ok": True,
        "runId": wire["run_id"],
        "commandId": wire["command_id"],
        "appended": bool(appended),
        "status": "completed",
        "executor": _EXECUTOR,
        "brokerAcknowledged": False,
    })
