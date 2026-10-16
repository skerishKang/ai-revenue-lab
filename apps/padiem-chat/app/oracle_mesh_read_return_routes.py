"""#4139 — Oracle management-host MeshCentral read: intent, poll, result.

The Windows Resident trial stays a separate Draft experiment: nothing here
executes on, or requires, the trial PC. This is the product path, and it
executes on the Oracle management host, where the official ``meshctrl.js``
client talks to the local MeshCentral server directly.

Actual call path (no browser carriage of content, no manual copying, no
browser session handed to Oracle):

* Owner intent (browser, owner session + CSRF): ``POST .../mesh-reads/request``
  carries intent only — device, run, root/path, confirmation. The server
  verifies the full existing chain (session, workspace, consent, live broker
  binding, origin run, complete stored correlation, deployment mesh
  ownership) and stages one dispatch row. The browser learns only a
  dispatch id; it never sees content, nonces or secrets.
* Executor poll (Oracle, deployment channel secret): ``POST
  .../mesh-reads/poll`` returns the single oldest claimable dispatch with a
  fresh single-use nonce. The nonce is stored hashed; a database read cannot
  replay an execution.
* Executor submit (Oracle, channel secret + nonce): ``POST
  .../mesh-reads/result`` carries the execution outcome and, on a clean
  exited/0 run, the bytes. The server revalidates everything — secret,
  dispatch state, nonce, expiry, exact correlation against the broker-bound
  row, execution outcome, size, UTF-8, control characters, SHA-256 — and
  appends once through the existing history authority under the standard
  stable message id. A tampered body+hash, a replayed nonce, or a
  cross-command package fails closed; a non-clean execution is delivered to
  the conversation as a truthful bounded failure, never silence.

What these routes are NOT: they enqueue, admit, acknowledge or write nothing
on the broker. The destination conversation is read from the origin run row,
never taken from the caller. The executor identity
(``oracle_management_host``) and the absence of a broker acknowledgment are
reported explicitly: a management-host return never poses as a
device-acknowledged one.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .claw_memory_routes import _resolve_memory_workspace
from .claw_local_task_result_projection import result_message_id
from .control_plane_identity import IdentityBridgeError
from .history import HistoryError, HistoryForbidden, validate_conversation_id

ORACLE_MESH_READ_REQUEST_PATH = "/api/claw/connector/mesh-reads/request"
ORACLE_MESH_READ_POLL_PATH = "/api/claw/connector/mesh-reads/poll"
ORACLE_MESH_READ_RESULT_PATH = "/api/claw/connector/mesh-reads/result"
#: Deployment-owned ownership map, read from Worker env by the worker root.
#: JSON list of {account_ref, device_id, node_ref, root_ref, path_relative,
#: file_path}. Absent or invalid keeps the source unconfigured; the routes
#: stay unmounted.
ORACLE_MESH_OWNERSHIP_MAP_ENV = "ORACLE_MESH_OWNERSHIP_MAP"
#: Which execution lane a TXT request takes:
#:   "off"    — Mesh execution disabled; the request stays on the native lane.
#:   "mesh"   — the request runs on the management host through the Mesh
#:              ownership map, whether or not the PC has a native binding.
#:   "native" — the request always stays on the native device lane.
ORACLE_MESH_EXECUTION_MODE_ENV = "ORACLE_MESH_EXECUTION_MODE"
EXECUTION_MODE_OFF = "off"
EXECUTION_MODE_MESH = "mesh"
EXECUTION_MODE_NATIVE = "native"
_EXECUTION_MODES = (EXECUTION_MODE_OFF, EXECUTION_MODE_MESH, EXECUTION_MODE_NATIVE)
#: Deployment channel secret for the Oracle executor (Worker env on Chat,
#: operator-held file on Oracle). Compared constant-time, never logged.
ORACLE_MESH_CHANNEL_SECRET_ENV = "ORACLE_MESH_CHANNEL_SECRET"
#: Header carrying the channel secret on poll/submit.
ORACLE_MESH_CHANNEL_HEADER = "X-Oracle-Mesh-Secret"
#: How long one dispatch stays claimable/submittable.
_DISPATCH_TTL = timedelta(seconds=600)
_MAX_BODY_BYTES = 8192
_SAFE_REF_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:@+-"
)
_MAX_FILE_TEXT_BYTES = 768
_EXECUTOR = "oracle_management_host"

_REQUEST_KEYS = frozenset({"device_id", "run_id", "root_ref", "path_relative", "confirmed"})
_RESULT_KEYS = frozenset({
    "dispatch_id", "nonce", "termination", "exit_code",
    "content_utf8", "content_sha256", "content_bytes",
})


class UnconfiguredOracleMeshReturnSource:
    """Fail-closed until the Worker root composes the deployment map+secret."""

    configured = False


class OracleMeshReturnSource:
    """Deployment-owned authorization for the Oracle return legs.

    Holds the (account, device, Mesh node, file) ownership map plus the
    channel secret. The map is supplied by the Worker root from deployment
    configuration, never from a request. The broker binding resolve (live,
    account-scoped) still gates every intent; this map only adds the
    Mesh-device ownership the broker never sees.
    """

    configured = True

    def __init__(
        self, mapping: Any, channel_secret: Any, mode: Any = EXECUTION_MODE_OFF
    ) -> None:
        if not isinstance(mapping, (list, tuple)) or not mapping:
            raise TypeError("oracle mesh ownership mapping is required")
        rows = []
        for entry in mapping:
            if not isinstance(entry, dict):
                raise TypeError("oracle mesh ownership row must be a mapping")
            row = {
                name: entry.get(name)
                for name in (
                    "account_ref", "device_id", "node_ref", "root_ref",
                    "path_relative", "file_path",
                )
            }
            for name, value in row.items():
                if (
                    not isinstance(value, str) or not value
                    or len(value) > 1024
                    or any(ch not in _SAFE_REF_CHARS and ch not in "\\/" for ch in value)
                ):
                    raise TypeError(f"oracle mesh ownership {name} invalid")
            if not row["path_relative"].lower().endswith(".txt"):
                raise TypeError("oracle mesh ownership path_relative must be .txt")
            rows.append(row)
        if (
            not isinstance(channel_secret, str)
            or not 16 <= len(channel_secret) <= 256
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in channel_secret)
        ):
            raise TypeError("oracle mesh channel secret invalid")
        self._rows = rows
        self._secret = channel_secret.encode("utf-8")
        self._mode = mode if mode in _EXECUTION_MODES else EXECUTION_MODE_OFF

    @property
    def execution_mode(self) -> str:
        """``off`` | ``mesh`` | ``native`` — which lane a TXT request takes."""
        return self._mode

    def owns(self, *, account_ref: str, path_relative: str) -> bool:
        """Whether this account has a verified Mesh target for that file."""
        return any(
            row["account_ref"] == account_ref
            and row["path_relative"] == path_relative
            for row in self._rows
        )

    def target_for(
        self, *, account_ref: str, path_relative: str,
        device_id: str | None = None,
    ) -> dict[str, Any] | None:
        """The single verified Mesh target for this account's requested file.

        Device and node are always server-derived from the ownership map, so
        an ordinary TXT request never names them. A browser-selected device
        only narrows the choice; it can never introduce one.
        """
        matches = [
            row for row in self._rows
            if row["account_ref"] == account_ref
            and row["path_relative"] == path_relative
            and (device_id is None or row["device_id"] == device_id)
        ]
        return dict(matches[0]) if len(matches) == 1 else None

    def check_channel_secret(self, presented: Any) -> bool:
        """Constant-time proof check for the Oracle executor channel."""
        if not isinstance(presented, str) or not presented:
            return False
        try:
            candidate = presented.encode("utf-8")
        except (UnicodeEncodeError, ValueError):
            return False
        return hmac.compare_digest(candidate, self._secret)


def build_oracle_mesh_return_source(
    mapping: Any, channel_secret: Any = None, mode: Any = EXECUTION_MODE_OFF
) -> OracleMeshReturnSource | None:
    """Worker-root composition only; missing/invalid material is unconfigured."""
    try:
        return OracleMeshReturnSource(mapping, channel_secret, mode)
    except Exception:
        return None


def build_oracle_mesh_return_source_from_env(env: Any) -> OracleMeshReturnSource | None:
    """Read the deployment map, channel secret and execution mode from env."""
    from .worker_config import binding_value

    try:
        raw_map = binding_value(env, ORACLE_MESH_OWNERSHIP_MAP_ENV)
        raw_secret = binding_value(env, ORACLE_MESH_CHANNEL_SECRET_ENV)
        raw_mode = binding_value(env, ORACLE_MESH_EXECUTION_MODE_ENV)
    except Exception:
        return None
    if not isinstance(raw_map, str) or not raw_map.strip():
        return None
    try:
        mapping = json.loads(raw_map)
    except (ValueError, TypeError):
        return None
    mode = raw_mode.strip().lower() if isinstance(raw_mode, str) else EXECUTION_MODE_OFF
    return build_oracle_mesh_return_source(mapping, raw_secret, mode)


async def resolve_oracle_mesh_execution(
    request: Request, *, path_relative: str, selected_device_id: str | None = None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Decide whether one ordinary TXT request runs on the Mesh lane.

    Returns ``(target, None)`` when the request should execute on the
    management host, ``(None, None)`` when it must stay on the native lane, and
    ``(None, response)`` for a refusal that the caller must surface.

    Order matters: the ownership decision comes from the deployment map, so an
    unregistered PC is never filtered out by the native device directory first.
    Consent, consent withdrawal and the OFF switch are still enforced here —
    only the *native binding* requirement is dropped, never the checks.
    """
    source = getattr(request.app.state, "oracle_mesh_return_source", None)
    if getattr(source, "configured", False) is not True:
        return None, None
    mode = source.execution_mode
    if mode == EXECUTION_MODE_OFF:
        return None, None
    if mode == EXECUTION_MODE_NATIVE:
        return None, None

    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return None, denial or _error(401, "canonical_session_required")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return None, _error(503, "oracle_mesh_unconfigured")
    try:
        scope = await identity.resolve_connector_owner_scope(session_id=session.session_id)
    except Exception:
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    if not isinstance(account_ref, str) or not account_ref:
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    if not source.owns(account_ref=account_ref, path_relative=path_relative):
        # This account has no verified Mesh target for the file: the request
        # keeps the native lane rather than silently executing somewhere else.
        return None, None
    target = source.target_for(
        account_ref=account_ref, path_relative=path_relative,
        device_id=selected_device_id,
    )
    if target is None:
        return None, _error(403, "oracle_mesh_ownership_unverified")
    return {
        "device_id": target["device_id"],
        "root_ref": target["root_ref"],
        "path_relative": target["path_relative"],
        "account_ref": account_ref,
    }, None


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


def _read_json(raw: bytes, keys: frozenset, limit: int = _MAX_BODY_BYTES) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if type(value) is not dict or set(value) != keys:
        return None
    return value


def _ref(value: Any, limit: int = 1024) -> str | None:
    if (
        not isinstance(value, str) or not value or len(value) > limit
        or any(ch not in _SAFE_REF_CHARS for ch in value)
    ):
        return None
    return value


async def _read_body(request: Request, keys: frozenset) -> dict[str, Any] | None:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return None
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or int(declared) > _MAX_BODY_BYTES):
            return None
        raw = await request.body()
        if len(raw) > _MAX_BODY_BYTES:
            return None
    except Exception:
        return None
    return _read_json(raw, keys)


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


async def oracle_mesh_read_request(request: Request) -> JSONResponse:
    """Owner intent: verify everything server-side, stage one dispatch."""
    if _channel_source(request) is None:
        return _error(503, "oracle_mesh_unconfigured")
    wire = await _read_body(request, _REQUEST_KEYS)
    if wire is None:
        return _error(400, "oracle_mesh_invalid_body")
    for key in ("device_id", "run_id", "root_ref", "path_relative"):
        if _ref(wire.get(key)) is None:
            return _error(400, "oracle_mesh_invalid_body")
    if wire.get("confirmed") is not True:
        return _error(400, "oracle_mesh_invalid_body")
    return await dispatch_oracle_mesh_read_intent(request, wire)


async def dispatch_oracle_mesh_read_intent(
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

    mesh_source = _channel_source(request)
    if mesh_source is None or mesh_source.execution_mode != EXECUTION_MODE_MESH:
        return _error(503, "oracle_mesh_unconfigured")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None)):
        return _error(503, "oracle_mesh_unconfigured")
    history_store = getattr(request.app.state, "history_store", None)
    if not callable(getattr(history_store, "get_claw_run", None)):
        return _error(503, "oracle_mesh_unconfigured")
    if not callable(getattr(history_store, "get_local_task_correlation", None)):
        return _error(503, "oracle_mesh_unconfigured")
    if not callable(getattr(history_store, "create_oracle_mesh_dispatch", None)):
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

    # #4139 sovereignty authorization. There is no native PC offer on this PC,
    # so no Broker binding and no Broker-minted evidence exist yet. Execution
    # authority is therefore the pair the platform can actually verify:
    #   * the Identity authority's consent for this session/device, which is
    #     what fixes the PADIEM account and connector workspace, and
    #   * the deployment-owned ownership map, which the operator verified
    #     against the real MeshCentral node (account <-> device <-> node <-> file).
    # A Broker binding is still *checked* when one exists, but its absence is
    # not a refusal and nothing is fabricated to stand in for it.
    device_binding_ref = None
    broker_source = getattr(request.app.state, "connector_txt_read_source", None)
    if getattr(broker_source, "configured", False) is True:
        try:
            device = await broker_source.resolve_device_binding(
                account_ref=account_ref, workspace_ref=connector_workspace_ref,
                device_id=wire["device_id"],
            )
        except IdentityBridgeError as exc:
            status = exc.status_code if isinstance(exc.status_code, int) else 503
            if status == 404:
                # No binding for this PC: that is exactly the unregistered case
                # this lane exists for. It is recorded as absent, not refused,
                # and nothing is fabricated to replace it.
                device = None
            elif status == 403:
                return _error(403, "oracle_mesh_device_not_usable")
            else:
                return _error(503, "oracle_mesh_broker_unavailable")
            device = None
        except Exception:
            return _error(503, "oracle_mesh_broker_unavailable")
        if device is not None:
            if (
                not isinstance(device, dict)
                or device.get("device_id") != wire["device_id"]
                or ("account_ref" in device and device["account_ref"] != account_ref)
                or ("workspace_ref" in device and device["workspace_ref"] != connector_workspace_ref)
            ):
                return _error(403, "oracle_mesh_device_not_usable")
            device_binding_ref = device.get("binding_ref")
            if device_binding_ref is not None and (
                not isinstance(device_binding_ref, str) or not device_binding_ref
            ):
                return _error(503, "oracle_mesh_broker_unavailable")

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

    target = _deployment_target_for(
        mesh_source,
        account_ref=account_ref,
        device_id=wire["device_id"],
        root_ref=wire["root_ref"],
        path_relative=wire["path_relative"],
    )
    if target is None:
        return _error(403, "oracle_mesh_ownership_unverified")

    # Correlation: bind the Broker-admitted one when it exists, otherwise mint
    # clearly server-owned refs. ``evidence_ref`` stays None when Broker has
    # admitted nothing — a server execution never borrows a broker evidence.
    try:
        bound = await history_store.get_local_task_correlation(uid, wire["run_id"])
    except Exception:
        bound = None
    broker_admitted = (
        isinstance(bound, dict)
        and all(isinstance(bound.get(name), str) and bound[name] for name in (
            "command_id", "tool_request_ref", "request_id",
            "revision_ref", "request_fingerprint",
        ))
    )
    if broker_admitted:
        cmd_id = bound["command_id"]
        tool_request_ref = bound["tool_request_ref"]
        request_id = bound["request_id"]
        revision_ref = bound["revision_ref"]
        evidence_ref = bound.get("evidence_ref")
        request_fingerprint = bound["request_fingerprint"]
    else:
        suffix = uuid.uuid4().hex
        cmd_id = f"oracle_mesh_cmd_{suffix}"
        tool_request_ref = f"oracle_mesh_tool_{suffix}"
        request_id = f"oracle_mesh_req_{suffix}"
        revision_ref = f"oracle_mesh_rev_{suffix}"
        evidence_ref = None
        request_fingerprint = hashlib.sha256(
            f"{account_ref}|{wire['device_id']}|{wire['root_ref']}|{wire['path_relative']}".encode("utf-8")
        ).hexdigest()

    now = datetime.now(timezone.utc)
    try:
        dispatch = await history_store.create_oracle_mesh_dispatch(
            user_id=uid,
            run_id=wire["run_id"],
            command_id=cmd_id,
            tool_request_ref=tool_request_ref,
            request_id=request_id,
            revision_ref=revision_ref,
            evidence_ref=evidence_ref,
            request_fingerprint=request_fingerprint,
            account_ref=account_ref,
            workspace_ref=connector_workspace_ref,
            device_id=wire["device_id"],
            binding_ref=device_binding_ref,
            node_ref=target["node_ref"],
            root_ref=wire["root_ref"],
            path_relative=wire["path_relative"],
            file_path=target["file_path"],
            expires_at=(now + _DISPATCH_TTL).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        )
    except HistoryForbidden:
        return _error(404, "oracle_mesh_run_unavailable")
    except HistoryError:
        return _error(409, "oracle_mesh_dispatch_refused")
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    return _response({
        "ok": True,
        "dispatch": {
            "dispatch_id": dispatch["dispatch_id"],
            "run_id": wire["run_id"],
            "state": dispatch["state"],
            "expires_at": dispatch["expires_at"],
            "execution": "server_owned",
            "broker_acknowledged": False,
        },
    })


def _deployment_target_for(
    source: OracleMeshReturnSource, *, account_ref: str, device_id: str,
    root_ref: str, path_relative: str,
) -> dict[str, Any] | None:
    """The single deployment row owning this (account, device, file).

    The Mesh node is server-derived from the deployment map: the browser
    names the logical file (root/path) but never the node or the Windows
    path. Exactly one row must own the file for this account+device.
    """
    matches = [
        row for row in source._rows
        if row["account_ref"] == account_ref
        and row["device_id"] == device_id
        and row["root_ref"] == root_ref
        and row["path_relative"] == path_relative
    ]
    return dict(matches[0]) if len(matches) == 1 else None


async def oracle_mesh_read_poll(request: Request) -> JSONResponse:
    """Executor poll: channel-secret proof, one claimed dispatch, one nonce."""
    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected")
    history_store = getattr(request.app.state, "history_store", None)
    if not callable(getattr(history_store, "oldest_pending_oracle_mesh_dispatch", None)):
        return _error(503, "oracle_mesh_unconfigured")
    if not callable(getattr(history_store, "claim_oracle_mesh_dispatch", None)):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        pending = await history_store.oldest_pending_oracle_mesh_dispatch()
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if pending is None:
        return _response({"ok": True, "dispatch": None})
    nonce = secrets.token_hex(16)
    nonce_sha256 = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    try:
        claimed = await history_store.claim_oracle_mesh_dispatch(
            dispatch_id=pending["dispatch_id"], nonce_sha256=nonce_sha256,
        )
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if claimed is not True:
        return _response({"ok": True, "dispatch": None})
    return _response({
        "ok": True,
        "dispatch": {
            "dispatch_id": pending["dispatch_id"],
            "nonce": nonce,
            "expires_at": pending["expires_at"],
            "node_ref": pending["node_ref"],
            "file_path": pending["file_path"],
            "account_ref": pending["account_ref"],
            "device_id": pending["device_id"],
            "binding_ref": pending["binding_ref"],
            "root_ref": pending["root_ref"],
            "path_relative": pending["path_relative"],
            "command_id": pending["command_id"],
            "run_id": pending["run_id"],
            "tool_request_ref": pending["tool_request_ref"],
            "request_id": pending["request_id"],
            "revision_ref": pending["revision_ref"],
            "evidence_ref": pending["evidence_ref"],
            "request_fingerprint": pending["request_fingerprint"],
        },
    })


def _verified_result_text(dispatch: dict[str, Any], wire: dict[str, Any]) -> str | None:
    """Revalidate a submission against the claimed dispatch; return the text."""
    text = wire["content_utf8"]
    if not isinstance(text, str):
        return None
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if (
        len(raw) > _MAX_FILE_TEXT_BYTES
        or wire["content_bytes"] != len(raw)
        or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text)
        or not isinstance(wire["content_sha256"], str)
        or wire["content_sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        return None
    return text


async def oracle_mesh_read_result(request: Request) -> JSONResponse:
    """Executor submit: secret + single-use nonce, verified, appended once."""
    wire = await _read_body(request, _RESULT_KEYS)
    if wire is None:
        return _error(400, "oracle_mesh_invalid_body")
    if _ref(wire.get("dispatch_id"), 128) is None:
        return _error(400, "oracle_mesh_invalid_body")
    if _ref(wire.get("nonce"), 128) is None:
        return _error(400, "oracle_mesh_invalid_body")
    if wire.get("termination") not in ("exited", "cancelled", "timed_out"):
        return _error(400, "oracle_mesh_invalid_body")
    if isinstance(wire.get("exit_code"), bool) or not isinstance(wire.get("exit_code"), int):
        return _error(400, "oracle_mesh_invalid_body")

    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected")
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("consume_oracle_mesh_dispatch", "finish_oracle_mesh_dispatch",
                   "mark_oracle_mesh_store_failed",
                   "record_oracle_mesh_first_result",
                   "get_claw_run", "append_local_task_result"):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured")

    try:
        dispatch = await history_store.consume_oracle_mesh_dispatch(
            dispatch_id=wire["dispatch_id"], nonce=wire["nonce"],
        )
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if dispatch is None:
        # Unknown, expired, already-consumed or nonce-mismatched dispatch. A
        # concurrent second submit of the same result loses the atomic update
        # here and is refused, rather than looking like the accepted request.
        return _error(409, "oracle_mesh_dispatch_rejected")
    claim = dispatch.get("claim")
    if claim not in ("first", "retry"):
        return _error(503, "oracle_mesh_dispatch_unavailable")

    outcome = "done"
    content = ""
    summary = ""
    status = ""
    result_digest = wire["content_sha256"] if wire["content_bytes"] else ""
    result_size = wire["content_bytes"]
    if wire["termination"] == "exited" and wire["exit_code"] == 0:
        verified_text = _verified_result_text(dispatch, wire)
        if verified_text is None:
            # A clean execution claim with tampered body+hash is refused, and
            # the consumed dispatch still closes as failed: the bytes are
            # untrusted and must never reach a conversation.
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "로컬 러너 작업 결과를 검증하지 못했습니다. "
                f"명령: {dispatch['command_id']}, 사유: 결과 무결성 불일치."
            )
        else:
            content = "PC 파일 읽기 결과:\n" + (verified_text if verified_text else "(빈 파일)")
            summary = "exited/0"
            status = "completed"
    elif wire["termination"] == "cancelled":
        summary = "cancelled"
        status = "cancelled"
        outcome = "failed"
        content = (
            "로컬 러너 작업이 취소되었습니다. "
            f"명령: {dispatch['command_id']}."
        )
    else:
        summary = "timed_out" if wire["termination"] == "timed_out" else "failed"
        status = summary
        outcome = "failed"
        content = (
            "로컬 러너 작업이 실패했습니다. "
            f"명령: {dispatch['command_id']}, 상태: {wire['termination']}, "
            f"종료 코드: {wire['exit_code']}."
        )
    if len(content) > 1_000:
        return _error(400, "oracle_mesh_content_unverified")

    # Pin the first accepted result. A resend after a transient store failure
    # must be the identical bytes: the executor holds them and never re-reads
    # the PC file, and a differing resend is refused rather than appended.
    try:
        same_result = await history_store.record_oracle_mesh_first_result(
            dispatch_id=wire["dispatch_id"],
            content_sha256=result_digest,
            content_bytes=result_size,
        )
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if same_result is not True:
        # Park the claim again: a rejected resend must not burn the retry the
        # executor still legitimately owns for its identical bytes.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
        return _error(409, "oracle_mesh_result_fingerprint_mismatch")

    run_row = None
    try:
        run_row = await history_store.get_claw_run(
            dispatch["user_id"], dispatch["run_id"],
        )
    except Exception:
        run_row = None
    conversation_id = (
        validate_conversation_id((run_row or {}).get("conversation_id"))
        if isinstance(run_row, dict) else None
    )
    if not conversation_id:
        try:
            await history_store.finish_oracle_mesh_dispatch(
                dispatch_id=wire["dispatch_id"], outcome="failed",
            )
        except Exception:
            pass
        return _error(404, "oracle_mesh_run_unavailable")

    message_id = result_message_id(
        conversation_id=conversation_id,
        command_id=dispatch["command_id"],
        revision_ref=dispatch["revision_ref"],
    )
    try:
        appended = await history_store.append_local_task_result(
            user_id=dispatch["user_id"],
            run_id=dispatch["run_id"],
            message_id=message_id,
            summary=summary,
            content=content,
            status=status,
        )
    except HistoryForbidden:
        # Ownership refusal is final: retrying cannot change it.
        try:
            await history_store.finish_oracle_mesh_dispatch(
                dispatch_id=wire["dispatch_id"], outcome="failed",
            )
        except Exception:
            pass
        return _error(403, "oracle_mesh_conversation_forbidden")
    except Exception:
        # Transient conversation-store failure. The verified result is parked
        # (claim and expiry intact) so the executor can resend the SAME result
        # — the PC file is not read again, and the stable message id keeps the
        # eventual append exactly-once.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
        return _error(503, "oracle_mesh_append_unavailable")
    try:
        await history_store.finish_oracle_mesh_dispatch(
            dispatch_id=wire["dispatch_id"], outcome=outcome,
        )
    except Exception:
        pass
    return _response({
        "ok": True,
        "runId": dispatch["run_id"],
        "commandId": dispatch["command_id"],
        "appended": bool(appended),
        "status": status,
        "claim": claim,
        "executor": _EXECUTOR,
        "brokerAcknowledged": False,
    })
