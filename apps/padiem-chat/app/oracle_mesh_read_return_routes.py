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

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .claw_memory_routes import _resolve_memory_workspace
from .claw_local_task_result_projection import result_message_id
from .control_plane_identity import IdentityBridgeError
from .history import (
    HistoryError,
    HistoryForbidden,
    MAX_HISTORY_MESSAGE_CHARS,
    validate_conversation_id,
)
from .request_telemetry import emit_stage_event

ORACLE_MESH_READ_REQUEST_PATH = "/api/claw/connector/mesh-reads/request"
ORACLE_MESH_READ_POLL_PATH = "/api/claw/connector/mesh-reads/poll"
ORACLE_MESH_READ_RESULT_PATH = "/api/claw/connector/mesh-reads/result"
#: Owner-scoped read of one stored over-budget command original. The dispatch
#: id is the only browser-supplied value; the object key, the conversation and
#: the message id are all re-derived server-side, so no browser-chosen object
#: path or foreign-account result is addressable here.
ORACLE_MESH_READ_ORIGINAL_PATH = "/api/claw/connector/mesh-results/{dispatch_id}"
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
#: #4139 wire envelope for one body on this connector, in both directions: the
#: same 6 MB the Claw request route already accepts for one user message
#: (``claw_general_routes.MAX_CLAW_GENERAL_BODY_BYTES``). The former 8 KiB and
#: 768 B trial caps could not carry a normal document or a Windows-bounded path.
_MAX_RESULT_BODY_BYTES = 6_000_000
_MAX_BODY_BYTES = _MAX_RESULT_BODY_BYTES
#: One stored conversation message. Reuses the existing product bound
#: (``history.MAX_HISTORY_MESSAGE_CHARS``); a larger output is split across
#: several messages, never truncated.
_MAX_COMMAND_MESSAGE_CHARS = MAX_HISTORY_MESSAGE_CHARS
#: Resource guard, not a data limit: how many message rows one run may create.
#: Above it the verified original goes to the private store and the
#: conversation carries one preview plus the owner-scoped retrieval reference,
#: so the bytes are never lost — only the row count is bounded.
_MAX_COMMAND_MESSAGE_PARTS = 256
#: A Windows path is ordinary input: Korean, spaces and any printable character
#: are allowed. The ceiling is the documented extended-length path maximum
#: (32,767 characters, Microsoft "Maximum Path Length Limitation"); the former
#: 1,024-character trial bound rejected a legal long path. Only control
#: characters are refused.
_MAX_PATH_VALUE_CHARS = 32_767
_SAFE_REF_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:@+-"
)
#: #4139 read lane envelope, shared with the command lane and the executor.
_MAX_FILE_TEXT_BYTES = _MAX_RESULT_BODY_BYTES
_EXECUTOR = "oracle_management_host"
#: #4139 terminal lane. A command dispatch has no file, so the 047 file
#: columns carry these fixed, self-describing sentinels instead of a bogus
#: Windows path; a read-lane use of a command row therefore fails loudly.
_COMMAND_ROOT_REF = "mesh_terminal"
_COMMAND_PATH_RELATIVE = "command"
_COMMAND_FILE_SENTINEL = "command"
#: How a command result is labelled in the conversation. The execution
#: method is recorded verbatim because MeshCentral runs it through the
#: device shell (PowerShell here), not through this server.
_COMMAND_SHELL_LABEL = "PowerShell (MeshCentral runcommand --reply)"
#: The result message echoes the command that ran. When that echo cannot fit
#: beside at least one output character, it is marked instead of pushing the
#: output out of the message: the full command stays in the user's own turn and
#: in the dispatch row, so the mark discloses nothing but a display bound.
_COMMAND_ECHO_MARK = "…(전체 명령은 보낸 메시지와 dispatch에 보존)"
_COMMAND_ECHO_PREFIX = "명령: "

_REQUEST_KEYS = frozenset({"device_id", "run_id", "root_ref", "path_relative", "confirmed"})
_RESULT_KEYS = frozenset({
    "dispatch_id", "nonce", "termination", "exit_code",
    "content_utf8", "content_sha256", "content_bytes",
})
#: The screenshot blob rides beside the note on capture turns only; input
#: turns carry no blob keys at all. Optional, never required, never trusted
#: without the digest check below.
_RESULT_BLOB_KEYS = frozenset({
    "content_blob_base64", "content_blob_sha256", "content_blob_bytes",
    "content_blob_media_type",
})
#: #4139 desktop lane. A desktop dispatch carries its op in the command_text
#: field (``desktop:<op>`` plus an optional argument line) with the same file
#: sentinels as a command dispatch, so neither lane can retarget the read
#: lane's file authority.
_DESKTOP_COMMAND_PREFIX = "desktop:"
_DESKTOP_OPS = ("capture", "type", "keys", "click")
_DESKTOP_SHELL_LABEL = "COM1 데스크톱 릴레이 (MeshCentral meshrelay p=2 + MSC)"
#: The only screenshot media type the executor produces. The browser renders
#: it; anything else is refused, never stored or served as an image.
_DESKTOP_SCREENSHOT_MEDIA_TYPE = "image/jpeg"
_DESKTOP_SCREENSHOT_MAGIC = b"\xff\xd8\xff"
#: Server-shaped screenshot reference marker. The conversation carries this
#: exact line and the frontend renderer fetches only this same-origin path,
#: so no browser-chosen URL can ever become an image in the conversation.
_DESKTOP_ORIGINAL_MARKER_PREFIX = "화면 캡처 원문: GET /api/claw/connector/mesh-results/"

#: Canonical fingerprint of zero bytes. Earlier executors pin an empty
#: string for an empty read, but the pin column requires a value; the
#: result route normalizes that exact legacy shape below instead of
#: stranding every resend on 409.
_EMPTY_RESULT_SHA256 = hashlib.sha256(b"").hexdigest()


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
                    "path_relative", "file_path", "command_exec",
                )
            }
            # #4139 terminal lane: command execution is a SEPARATE deployment
            # grant. A row that authorizes a TXT read never authorizes running a
            # command unless the operator marked it explicitly.
            command_exec = row.pop("command_exec")
            if command_exec is None:
                command_exec = False
            if not isinstance(command_exec, bool):
                raise TypeError("oracle mesh ownership command_exec must be boolean")
            row["command_exec"] = command_exec
            for name, value in row.items():
                if name == "command_exec":
                    continue
                if name in ("path_relative", "file_path"):
                    # A path is not a reference: Korean names are valid input.
                    if _text_value(value) is None:
                        raise TypeError(
                            "oracle mesh ownership " + name + " must be bounded text"
                        )
                    continue
                if value is None:
                    # Only ``device_id`` is an optional pin: when it is absent
                    # the Mesh node itself is the canonical device identity.
                    # ``account_ref`` is mandatory — a row without the verified
                    # PADIEM account never authorizes anybody, and an omitted
                    # account is never treated as permission for all accounts.
                    if name != "device_id":
                        raise TypeError(f"oracle mesh ownership {name} invalid")
                    continue
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

    def classify(self, *, account_ref: str, path_relative: str) -> str:
        """``none`` | ``owned`` | ``foreign`` for one authenticated account.

        ``none``  — the deployment maps no Mesh target for this file at all;
                    the caller keeps the native lane.
        ``owned`` — exactly one row pins this verified account for this file.
                    Only the exact correspondence of verified account and
                    real Mesh node authorizes execution.
        ``foreign`` — the file is mapped, but only to other pinned accounts:
                    a hard ownership refusal, never a fallback.
        """
        rows_for_path = [
            row for row in self._rows if row["path_relative"] == path_relative
        ]
        if not rows_for_path:
            return "none"
        for row in rows_for_path:
            if row["account_ref"] == account_ref:
                return "owned"
        return "foreign"

    def target_for(
        self, *, account_ref: str, path_relative: str,
        device_id: str | None = None,
    ) -> dict[str, Any] | None:
        """The single verified Mesh target for this account's requested file.

        Device and node are always server-derived from the ownership map, so
        an ordinary TXT request never names them. A browser-selected device
        only narrows the choice; it can never introduce one. A row without a
        device pin contributes its Mesh node as the canonical device identity.
        """
        matches = [
            row for row in self._rows
            if row["path_relative"] == path_relative
            and row["account_ref"] == account_ref
            and (device_id is None or row.get("device_id") == device_id or row.get("device_id") is None)
        ]
        return dict(matches[0]) if len(matches) == 1 else None

    def command_target(
        self, *, account_ref: str, device_id: str | None = None,
    ) -> dict[str, Any] | None:
        """The single command-capable Mesh target for this verified account.

        #4139 terminal lane. A command has no file, so the row is selected by
        the account (and the optional device pin) alone — and only when the
        operator explicitly marked that row ``command_exec``. A TXT read grant
        is therefore never a command grant, and two competing rows stay a
        refusal rather than an arbitrary pick.
        """
        matches = [
            row for row in self._rows
            if row["command_exec"] is True
            and row["account_ref"] == account_ref
            and (
                device_id is None
                or row.get("device_id") == device_id
                or row.get("device_id") is None
                or row["node_ref"] == device_id
            )
        ]
        return dict(matches[0]) if len(matches) == 1 else None

    def device_hint_for(
        self, *, account_ref: str, path_relative: str,
        selected_device_id: str | None = None,
    ) -> str:
        """The server-derived device identity for consent lookups.

        The canonical device for an unpinned row is its Mesh node; a pinned
        row keeps its pin. A browser selection never widens this.
        """
        target = self.target_for(
            account_ref=account_ref, path_relative=path_relative,
            device_id=selected_device_id,
        )
        if target is not None:
            return target.get("device_id") or target["node_ref"]
        rows_for_path = [
            row for row in self._rows if row["path_relative"] == path_relative
        ]
        if rows_for_path:
            return rows_for_path[0].get("device_id") or rows_for_path[0]["node_ref"]
        return selected_device_id or ""

    def check_channel_secret(self, presented: Any) -> bool:
        """Constant-time proof check for the Oracle executor channel."""
        if not isinstance(presented, str) or not presented:
            return False
        try:
            candidate = presented.encode("utf-8")
        except (UnicodeEncodeError, ValueError):
            return False
        return hmac.compare_digest(candidate, self._secret)


async def _resolve_oracle_store_text(raw: Any) -> Any:
    """Plain strings pass through; Secrets Store bindings resolve via async .get()."""
    if isinstance(raw, str):
        return raw
    getter = getattr(raw, "get", None)
    if not callable(getter):
        return None
    resolved = getter()
    if hasattr(resolved, "__await__"):
        resolved = await resolved
    return resolved


def build_oracle_mesh_return_source(
    mapping: Any, channel_secret: Any = None, mode: Any = EXECUTION_MODE_OFF
) -> OracleMeshReturnSource | None:
    """Worker-root composition only; missing/invalid material is unconfigured."""
    try:
        return OracleMeshReturnSource(mapping, channel_secret, mode)
    except Exception:
        return None


async def build_oracle_mesh_return_source_from_env(env: Any) -> OracleMeshReturnSource | None:
    """Read the deployment map, channel secret and execution mode from env.

    The channel secret is a Secrets Store binding, not a plain string: like
    every other deployment secret in this Worker it is resolved through the
    binding's async ``.get()`` and never read as a raw env value. A store
    object that cannot be read keeps the source unconfigured, so the routes
    stay unmounted instead of running with a broken proof.
    """
    from .worker_config import binding_value

    try:
        raw_map = await _resolve_oracle_store_text(binding_value(env, ORACLE_MESH_OWNERSHIP_MAP_ENV))
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
    if not isinstance(raw_secret, str):
        getter = getattr(raw_secret, "get", None)
        if not callable(getter):
            return None
        try:
            resolved = getter()
            if hasattr(resolved, "__await__"):
                resolved = await resolved
        except Exception:
            return None
        raw_secret = resolved
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
    except Exception as exc:
        # #4139: this is the only place the canonical owner-scope refusal is
        # observed. The public projection is one fixed code, so the Identity
        # code is retained on the existing bounded stage-telemetry channel
        # (code + stage + request-scoped id only; build_stage_event sanitizes
        # the value and never carries a message).
        emit_stage_event(
            stage="mesh.owner_scope", outcome="error", duration_ms=0,
            code=getattr(exc, "code", None),
        )
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    if not isinstance(account_ref, str) or not account_ref:
        return None, _error(503, "oracle_mesh_device_directory_unavailable")
    disposition = source.classify(account_ref=account_ref, path_relative=path_relative)
    if disposition == "none":
        # The deployment maps no Mesh target for this file: the request keeps
        # the native lane rather than silently executing somewhere else.
        return None, None
    if disposition == "foreign":
        # The file IS mapped, but only to other accounts. That is a hard
        # ownership refusal, never a lane fallback.
        return None, _error(403, "oracle_mesh_ownership_unverified")
    # Consent withdrawal is enforced HERE, before a run is staged: an owner
    # who withdrew the connector consent must be refused up front. Absence of
    # a consent record is not a precondition on this lane (no native
    # enrollment is required); a backend failure still fails closed.
    if callable(getattr(identity, "resolve_connector_enrollment_consent_for_device", None)):
        try:
            consent = await identity.resolve_connector_enrollment_consent_for_device(
                session_id=session.session_id,
                device_id=source.device_hint_for(
                    account_ref=account_ref, path_relative=path_relative,
                    selected_device_id=selected_device_id,
                ),
            )
        except IdentityBridgeError as exc:
            if getattr(exc, "code", None) != "enrollment_consent_required":
                return None, _error(503, "oracle_mesh_unconfigured")
        except Exception:
            return None, _error(503, "oracle_mesh_unconfigured")
        else:
            if isinstance(consent, dict) and consent.get("withdrawn_at") is not None:
                return None, _error(403, "oracle_mesh_consent_required")
    target = source.target_for(
        account_ref=account_ref, path_relative=path_relative,
        device_id=selected_device_id,
    )
    if target is None:
        return None, _error(403, "oracle_mesh_ownership_unverified")
    return {
        "device_id": target.get("device_id") or target["node_ref"],
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


def _read_json(raw: bytes, keys: frozenset, limit: int = _MAX_BODY_BYTES,
               optional: frozenset = frozenset()) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if type(value) is not dict:
        return None
    names = set(value)
    # Required keys must all be present; optional keys (the desktop screenshot
    # blob, absent on input-only turns) may be present; anything else refuses.
    if not keys <= names <= keys | optional:
        return None
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
        return None
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or int(declared) > limit):
            return None
        raw = await request.body()
        if len(raw) > limit:
            return None
    except Exception:
        return None
    return _read_json(raw, keys, limit, optional)


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
    for key in ("device_id", "run_id", "root_ref"):
        if _ref(wire.get(key)) is None:
            return _error(400, "oracle_mesh_invalid_body")
    if _text_value(wire.get("path_relative")) is None:
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
    except IdentityBridgeError as exc:
        if getattr(exc, "code", None) == "enrollment_consent_required":
            # Mesh mode deliberately does not require a native enrollment
            # consent to exist: the authenticated session scope below is the
            # account authority. A backend failure is still a failure.
            consent = None
        else:
            return _error(503, "oracle_mesh_unconfigured")
    except Exception:
        return _error(503, "oracle_mesh_unconfigured")
    if consent is not None and (
        not isinstance(consent, dict)
        or consent.get("device_id") != wire["device_id"]
        or consent.get("withdrawn_at") is not None
    ):
        # An existing consent that was withdrawn (or names another device) is
        # a hard refusal: withdrawal is still enforced.
        return _error(403, "oracle_mesh_consent_required")

    # The authenticated Identity session scope supplies the canonical account
    # and connector workspace. When a live consent exists it must agree with
    # that same scope; agreement is checked, never assumed.
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        scope = await identity.resolve_connector_owner_scope(
            session_id=session.session_id,
        )
    except Exception:
        return _error(503, "oracle_mesh_device_directory_unavailable")
    if (
        not isinstance(scope, dict)
        or not isinstance(scope.get("account_ref"), str) or not scope["account_ref"]
        or not isinstance(scope.get("workspace_ref"), str) or not scope["workspace_ref"]
    ):
        return _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope["account_ref"]
    connector_workspace_ref = scope["workspace_ref"]
    if consent is not None and (
        consent.get("account_ref") != account_ref
        or consent.get("workspace_ref") != connector_workspace_ref
    ):
        return _error(403, "oracle_mesh_consent_required")

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


async def dispatch_oracle_mesh_command_intent(
    request: Request, *, command: str, wire: dict[str, Any],
) -> JSONResponse:
    """Owner intent for ONE terminal command on the pinned management PC.

    #4139 terminal lane. Every authority check of the read lane is reused
    (verified owner session, canonical account scope, origin run, deployment
    ownership), and the command travels inside the dispatch itself. Two things
    are deliberately different:

    * the deployment row must be explicitly marked ``command_exec`` -- a TXT
      read grant is never a command grant;
    * no file/root/path is accepted from the browser, so this route cannot
      retarget the read lane's file authority.
    """
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
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("get_claw_run", "get_local_task_correlation", "create_oracle_mesh_dispatch"):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured")
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return _error(503, "oracle_mesh_unconfigured")

    selected = wire.get("device_id")
    if selected is not None and (not isinstance(selected, str) or not selected):
        return _error(422, "oracle_mesh_device_invalid")
    if not isinstance(command, str) or not command.strip():
        return _error(422, "oracle_mesh_command_invalid")

    try:
        scope = await identity.resolve_connector_owner_scope(session_id=session.session_id)
    except Exception as exc:
        emit_stage_event(
            stage="mesh.command_owner_scope", outcome="error", duration_ms=0,
            code=getattr(exc, "code", None),
        )
        return _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    connector_workspace_ref = scope.get("workspace_ref") if isinstance(scope, dict) else None
    if (
        not isinstance(account_ref, str) or not account_ref
        or not isinstance(connector_workspace_ref, str) or not connector_workspace_ref
    ):
        return _error(503, "oracle_mesh_device_directory_unavailable")

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

    target = mesh_source.command_target(account_ref=account_ref, device_id=selected)
    if target is None:
        return _error(403, "oracle_mesh_command_unverified")

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
        cmd_id = "oracle_mesh_cmd_" + suffix
        tool_request_ref = "oracle_mesh_tool_" + suffix
        request_id = "oracle_mesh_req_" + suffix
        revision_ref = "oracle_mesh_rev_" + suffix
        evidence_ref = None
        # The command is part of the correlation: a different command for the
        # same run is a different request, never a silent retarget.
        request_fingerprint = hashlib.sha256(
            (account_ref + "|" + target["node_ref"] + "|" + command).encode("utf-8")
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
            device_id=target.get("device_id") or target["node_ref"],
            binding_ref=None,
            node_ref=target["node_ref"],
            root_ref=_COMMAND_ROOT_REF,
            path_relative=_COMMAND_PATH_RELATIVE,
            file_path=_COMMAND_FILE_SENTINEL,
            expires_at=(now + _DISPATCH_TTL).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            kind="command",
            command_text=command,
        )
    except HistoryForbidden:
        return _error(404, "oracle_mesh_run_unavailable")
    except HistoryError as exc:
        if str(exc) == "oracle mesh dispatch row exceeds the storage row bound":
            # The command text is a bound parameter, so the limit that binds it
            # is D1's documented 2,000,000-byte row ceiling, checked on the row
            # it is written into. Named here so a huge command reads as too
            # large rather than as a refused dispatch.
            return _error(413, "oracle_mesh_dispatch_too_large")
        if str(exc) == "oracle mesh command execution is uncertain":
            # #4139: the command may already have run. A second execution is
            # never attempted; the state is reported as uncertain instead.
            return _error(409, "oracle_mesh_command_uncertain")
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
            "kind": "command",
            "execution": "server_owned",
            "broker_acknowledged": False,
        },
    })


def _parse_desktop_op_text(value: Any) -> tuple[str, str | None] | None:
    """Split one ``desktop:`` op body into (op, arg), or None when malformed.

    #4139 desktop lane. This mirrors the executor's grammar so a malformed
    op is refused here with 422 instead of burning a PC turn; the executor
    still re-verifies before the PC acts and never trusts this check.
    """
    if not isinstance(value, str):
        return None
    if not value.startswith(_DESKTOP_COMMAND_PREFIX):
        return None
    rest = value[len(_DESKTOP_COMMAND_PREFIX):]
    if "\x00" in rest or "\r" in rest:
        return None
    head, _, tail = rest.partition("\n")
    op = head.strip().lower()
    if op not in _DESKTOP_OPS:
        return None
    if op == "capture":
        if tail.strip():
            return None
        return op, None
    arg = tail.strip(" \t\n")
    if not arg:
        return None
    if op == "type":
        if any(ord(ch) < 32 and ch not in "\t\n" for ch in arg) or "\x7f" in arg:
            return None
        return op, arg
    if op == "keys":
        if arg.strip().lower() not in (
            "enter", "esc", "tab", "backspace", "delete",
            "ctrl+s", "ctrl+c", "ctrl+v", "ctrl+a", "alt+f4", "win+r", "win",
        ):
            return None
        return op, arg.strip().lower()
    match = re.fullmatch(r"(\d{1,5}),(\d{1,5})", arg)
    if match is None:
        return None
    if int(match.group(1)) > 65535 or int(match.group(2)) > 65535:
        return None
    return op, f"{int(match.group(1))},{int(match.group(2))}"


async def dispatch_oracle_mesh_desktop_intent(
    request: Request, *, desktop_op: str, wire: dict[str, Any],
    trusted_owner: tuple[Any, str, str] | None = None,
) -> JSONResponse:
    """Owner intent for ONE desktop observation or input on the pinned PC.

    #4139 desktop lane. Every authority check of the command lane is reused
    (verified owner session, canonical account scope, origin run, deployment
    ownership through the SAME ``command_exec`` grant — a desktop input
    drives the pinned PC exactly like a command does, so a TXT read grant is
    never enough), and the op travels inside the dispatch itself. Two things
    are deliberately different:

    * no file/root/path is accepted from the browser, so this route cannot
      retarget the read lane's file authority;
    * the op grammar is closed (capture/type/keys/click): anything else is
      refused here, and the executor re-verifies before the PC acts.
    """
    if trusted_owner is None:
        session, denial = await _verified_owner_request(request)
        if denial is not None or session is None:
            return denial if denial is not None else _error(401, "canonical_session_required")
        uid = current_user_id(request)
        try:
            workspace_id = await _resolve_memory_workspace(request, uid)
        except Exception:
            return _error(503, "oracle_mesh_workspace_unavailable")
    else:
        session, uid, workspace_id = trusted_owner
        if not uid or not workspace_id or not getattr(session, "tenant_id", None):
            return _error(401, "canonical_session_required")
    if not workspace_id:
        return _error(503, "oracle_mesh_workspace_unavailable")

    mesh_source = _channel_source(request)
    if mesh_source is None or mesh_source.execution_mode != EXECUTION_MODE_MESH:
        return _error(503, "oracle_mesh_unconfigured")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("get_claw_run", "get_local_task_correlation", "create_oracle_mesh_dispatch"):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured")
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return _error(503, "oracle_mesh_unconfigured")

    selected = wire.get("device_id")
    if selected is not None and (not isinstance(selected, str) or not selected):
        return _error(422, "oracle_mesh_device_invalid")
    parsed = _parse_desktop_op_text(desktop_op)
    if parsed is None:
        return _error(422, "oracle_mesh_desktop_op_invalid")
    op, arg = parsed
    canonical_op = "desktop:" + op + ("" if arg is None else "\n" + arg)

    try:
        scope = await identity.resolve_connector_owner_scope(session_id=session.session_id)
    except Exception as exc:
        emit_stage_event(
            stage="mesh.desktop_owner_scope", outcome="error", duration_ms=0,
            code=getattr(exc, "code", None),
        )
        return _error(503, "oracle_mesh_device_directory_unavailable")
    account_ref = scope.get("account_ref") if isinstance(scope, dict) else None
    connector_workspace_ref = scope.get("workspace_ref") if isinstance(scope, dict) else None
    if (
        not isinstance(account_ref, str) or not account_ref
        or not isinstance(connector_workspace_ref, str) or not connector_workspace_ref
    ):
        return _error(503, "oracle_mesh_device_directory_unavailable")

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

    target = mesh_source.command_target(account_ref=account_ref, device_id=selected)
    if target is None:
        return _error(403, "oracle_mesh_command_unverified")

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
        cmd_id = "oracle_mesh_cmd_" + suffix
        tool_request_ref = "oracle_mesh_tool_" + suffix
        request_id = "oracle_mesh_req_" + suffix
        revision_ref = "oracle_mesh_rev_" + suffix
        evidence_ref = None
        # The op is part of the correlation: a different op for the same run
        # is a different request, never a silent retarget.
        request_fingerprint = hashlib.sha256(
            (account_ref + "|" + target["node_ref"] + "|" + canonical_op).encode("utf-8")
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
            device_id=target.get("device_id") or target["node_ref"],
            binding_ref=None,
            node_ref=target["node_ref"],
            root_ref=_COMMAND_ROOT_REF,
            path_relative=_COMMAND_PATH_RELATIVE,
            file_path=_COMMAND_FILE_SENTINEL,
            expires_at=(now + _DISPATCH_TTL).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            kind="desktop",
            command_text=canonical_op,
        )
    except HistoryForbidden:
        return _error(404, "oracle_mesh_run_unavailable")
    except HistoryError as exc:
        if str(exc) == "oracle mesh dispatch row exceeds the storage row bound":
            return _error(413, "oracle_mesh_dispatch_too_large")
        if str(exc) == "oracle mesh command execution is uncertain":
            # A desktop input may already have mutated the PC. A second
            # execution is never attempted; the state is reported instead.
            return _error(409, "oracle_mesh_command_uncertain")
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
            "kind": "desktop",
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
    path. Exactly one row must pin this verified account for this file; the
    device pin stays optional and an unpinned row contributes its Mesh node
    as the canonical device identity (the resolver already substituted it on
    the wire).
    """
    matches = [
        row for row in source._rows
        if row["account_ref"] == account_ref
        and (row.get("device_id") is None
             or row["device_id"] == device_id
             or row["node_ref"] == device_id)
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
            "kind": pending.get("kind") or "read",
            "command_text": pending.get("command_text"),
        },
    })


def _verified_desktop_note(wire: dict[str, Any]) -> str | None:
    """Revalidate a desktop observation note: short text, no control bytes."""
    note = wire.get("content_utf8")
    if not isinstance(note, str):
        return None
    try:
        note.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in note) or "\x7f" in note:
        return None
    return note


def _verified_desktop_blob(
    wire: dict[str, Any], max_bytes: int = _MAX_RESULT_BODY_BYTES,
) -> bytes | bytearray | None:
    """Revalidate a desktop screenshot blob, or ``b""`` when absent.

    Returns None for a malformed blob. Absence (act ops) is ``b""``, never
    an error: only a half-present blob is untrusted.
    """
    media = wire.get("content_blob_media_type")
    encoded = wire.get("content_blob_base64")
    digest = wire.get("content_blob_sha256")
    size = wire.get("content_blob_bytes")
    if media is None and encoded is None and digest is None and size is None:
        return b""
    if media != _DESKTOP_SCREENSHOT_MEDIA_TYPE:
        return None
    if not isinstance(encoded, str) or not encoded:
        return None
    if not isinstance(digest, str) or not digest:
        return None
    if isinstance(size, bool) or not isinstance(size, int):
        return None
    if size <= 0 or size > max_bytes:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        return None
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        return None
    if not raw.startswith(_DESKTOP_SCREENSHOT_MAGIC):
        return None
    return raw


_DESKTOP_OP_LABELS = {
    "capture": "화면 캡처",
    "type": "문자 입력",
    "keys": "키 입력",
    "click": "마우스 클릭",
}


def _desktop_op_description(op: str, arg: str | None) -> str:
    label = _DESKTOP_OP_LABELS.get(op, op)
    if op == "keys" and arg:
        return f"키 입력 ({arg})"
    if op == "click" and arg:
        return f"마우스 클릭 ({arg})"
    return label


def _desktop_head(dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None) -> list[str]:
    """The fixed head of one desktop message: what ran, how, what is known."""
    lines = [
        "COM1 데스크톱 " + _DESKTOP_OP_LABELS.get(op, op),
        "동작: " + _desktop_op_description(op, arg),
        "실행 방식: " + _DESKTOP_SHELL_LABEL,
    ]
    termination = wire["termination"]
    if termination == "captured":
        lines.append("종료 상태: 화면 관측 완료")
    elif termination == "acted":
        lines.append("종료 상태: 입력 전달 완료 (릴레이 연결·화면 확인 후 전송)")
    elif termination == "desktop_unavailable":
        lines.append("종료 상태: 데스크톱 응답 없음 (세션이 연결되지 않았거나 화면이 완성되지 않음)")
    elif termination == "timed_out":
        lines.append("종료 상태: 대기 시간 초과 (PC 입력의 도달을 확인하지 못함)")
    elif termination == "not_executed":
        lines.append("종료 상태: 실행되지 않음 (실행 경계에서 거부됨)")
    elif termination == "output_too_large":
        lines.append("종료 상태: 화면이 전송 한도를 초과")
    else:
        lines.append("종료 상태: " + str(termination))
    return lines


def _desktop_capture_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str, digest: str,
) -> str:
    """One conversation message for one real screen capture.

    The message carries the observation and the owner-scoped retrieval
    reference in a server-shaped marker line; the browser renders the image
    from that same-origin path. The bytes live in the private original
    store, pinned by the dispatch row.
    """
    lines = _desktop_head(dispatch, wire, op, arg)
    lines.append("관측: " + note)
    lines.append("SHA-256: " + digest)
    lines.append(
        _DESKTOP_ORIGINAL_MARKER_PREFIX + str(dispatch["dispatch_id"])
    )
    return "\n".join(lines)


def _desktop_act_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str,
) -> str:
    """One conversation message for one delivered desktop input."""
    lines = _desktop_head(dispatch, wire, op, arg)
    lines.append("관측: " + note)
    return "\n".join(lines)


def _desktop_failed_content(
    dispatch: dict[str, Any], wire: dict[str, Any], op: str, arg: str | None,
    note: str,
) -> str:
    """A desktop turn that observed no success stays an explicit notice."""
    lines = _desktop_head(dispatch, wire, op, arg)
    if note:
        lines.append("관측: " + note)
    if wire["termination"] == "output_too_large":
        lines.append(
            "화면 본문은 전송 한도를 초과하여 전달되지 않았습니다. "
            "원문이 서버에 보관되지 않았으므로 다시 조회할 수 없습니다. "
            "한 번에 관측하는 화면 범위를 좁혀 다시 실행하십시오."
        )
    else:
        lines.append(
            "PC 화면·입력에 도달하지 못했습니다. "
            "같은 입력을 반복하기 전에 화면 캡처로 현재 상태를 확인하십시오."
        )
    return "\n".join(lines)


def _verified_result_text(
    dispatch: dict[str, Any], wire: dict[str, Any],
    max_bytes: int = _MAX_FILE_TEXT_BYTES,
) -> str | None:
    """Revalidate a submission against the claimed dispatch; return the text."""
    text = wire["content_utf8"]
    if not isinstance(text, str):
        return None
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if (
        len(raw) > max_bytes
        or wire["content_bytes"] != len(raw)
        or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text)
        or not isinstance(wire["content_sha256"], str)
        or wire["content_sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        return None
    return text


def _command_header(dispatch: dict[str, Any], wire: dict[str, Any]) -> list[str]:
    """The fixed head of one command message: what ran, how, and what is known.

    A wait timeout is never reported as a terminated process, and an unobserved
    exit code stays "확인되지 않음" instead of 0.
    """
    lines = [
        "COM1 명령 실행 결과",
        "명령: " + str(dispatch.get("command_text") or ""),
        "실행 방식: " + _COMMAND_SHELL_LABEL,
        "출력: stdout+stderr 병합",
    ]
    termination = wire["termination"]
    if termination == "timed_out":
        lines.append("종료 상태: 대기 시간 초과 (PC 프로세스가 계속 실행 중일 수 있음)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "cancelled":
        lines.append("종료 상태: 취소됨 (PC 종료 코드 확인 불가)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "no_reply":
        lines.append("종료 상태: 콘솔 응답 없음")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "not_executed":
        # The command never reached the PC: the execution boundary refused it
        # (an argv element over the host limit, a bad node reference). Reporting
        # that as "콘솔 응답 없음" would blame a console that was never asked.
        lines.append("종료 상태: 실행되지 않음 (실행 경계에서 거부됨)")
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "no_exit_code":
        # The console answered and the shell reached the statement this lane
        # appends, but PowerShell only records $LASTEXITCODE for a native program
        # or script, so a cmdlet-only pipeline reports no number. The output is
        # delivered whole and the code stays "확인되지 않음" — never 0.
        lines.append(
            "종료 상태: 콘솔 응답 완료 (cmdlet 전용 파이프라인이라 종료 코드가 보고되지 않음)"
        )
        lines.append("종료 코드: 확인되지 않음")
    elif termination == "output_too_large":
        lines.append("종료 상태: 출력이 전송 한도를 초과")
        lines.append(
            "종료 코드: " + (
                str(wire["exit_code"])
                if isinstance(wire["exit_code"], int)
                else "확인되지 않음"
            )
        )
    else:
        lines.append("종료 상태: " + str(termination))
        lines.append(
            "종료 코드: " + (
                str(wire["exit_code"])
                if isinstance(wire["exit_code"], int)
                else "확인되지 않음"
            )
        )
    return lines


def _command_result_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """One conversation message for one real command execution.

    The output is delimited by explicit markers so its own leading/trailing
    whitespace and newlines survive the shared history projection unchanged:
    the markers, not the output, are the message edges.
    """
    lines = _command_header(dispatch, wire)
    lines.append("--- 출력 시작 ---")
    lines.append(output)
    lines.append("--- 출력 끝 ---")
    return "\n".join(lines)


def _command_output_withheld_content(
    dispatch: dict[str, Any], wire: dict[str, Any],
) -> str:
    """An execution whose output never crossed the wire.

    The executor withheld the body at the wire envelope, so there is no
    stored original to point at: the message says exactly that instead of
    claiming the dispatch row holds a body it does not. Only the observed
    termination and exit code are delivered.
    """
    lines = _command_header(dispatch, wire)
    lines.append(
        "출력 본문은 전송 한도를 초과하여 전달되지 않았습니다. "
        "원문이 서버에 보관되지 않았으므로 다시 조회할 수 없습니다. "
        "출력 범위를 좁힌 명령으로 다시 실행하십시오."
    )
    return "\n".join(lines)


def _command_original_stored_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """One notice for an output larger than the conversation budget.

    The full output passed verification (bytes and digest are pinned on the
    dispatch row) and the private original store accepted it before this
    message was built, so "stored" is only claimed after the put succeeds.
    The conversation carries a head preview sized to this message's own frame —
    a preview taken from another shape could overflow the shared per-message
    limit and strand the result — and the whole original is fetched through the
    owner-scoped retrieval reference below.
    """
    head = _command_head(dispatch, wire)
    opening = head + [
        "출력 " + str(wire["content_bytes"]) + "바이트 전체는 비공개 원문 저장소에 "
        "보관되었습니다. 아래는 앞부분 미리보기입니다.",
        "--- 출력 미리보기 시작 ---",
    ]
    closing = [
        "--- 출력 미리보기 끝 ---",
        "SHA-256: " + str(wire["content_sha256"]),
        "원문 전체 조회: GET "
        + "/api/claw/connector/mesh-results/" + str(dispatch["dispatch_id"]),
    ]
    room = (
        _MAX_COMMAND_MESSAGE_CHARS
        - sum(len(line) for line in opening + closing)
        - (len(opening) + len(closing))
    )
    return "\n".join(opening + [output[:max(room, 0)]] + closing)


def _command_part_messages(head: list[str], parts: list[str]) -> list[str]:
    """Wrap each output part in the shared frame, in order.

    ``"".join(parts)`` is the output verbatim, so the conversation carries every
    byte across its messages; the frame lines are display furniture and the
    pinned digest belongs to the unwrapped body.
    """
    total = str(len(parts))
    messages = []
    for index, part in enumerate(parts):
        lines = list(head)
        lines.append("--- 출력 " + str(index + 1) + "/" + total + " 시작 ---")
        lines.append(part)
        lines.append("--- 출력 끝 ---")
        messages.append("\n".join(lines))
    return messages


def _file_read_part_messages(parts: list[str]) -> list[str]:
    total = str(len(parts))
    messages = []
    for index, part in enumerate(parts):
        lines = ["PC 파일 읽기 결과"]
        lines.append("--- 출력 " + str(index + 1) + "/" + total + " 시작 ---")
        lines.append(part)
        lines.append("--- 출력 끝 ---")
        messages.append("\n".join(lines))
    return messages


def _file_read_stored_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output: str,
) -> str:
    """Read-lane twin of the stored-original notice, sized to its own frame."""
    opening = [
        "PC 파일 읽기 결과",
        "출력 " + str(wire["content_bytes"]) + "바이트 전체는 비공개 원문 저장소에 "
        "보관되었습니다. 아래는 앞부분 미리보기입니다.",
        "--- 출력 미리보기 시작 ---",
    ]
    closing = [
        "--- 출력 미리보기 끝 ---",
        "SHA-256: " + str(wire["content_sha256"]),
        "원문 전체 조회: GET "
        + "/api/claw/connector/mesh-results/" + str(dispatch["dispatch_id"]),
    ]
    room = (
        _MAX_COMMAND_MESSAGE_CHARS
        - sum(len(line) for line in opening + closing)
        - (len(opening) + len(closing))
    )
    return "\n".join(opening + [output[:max(room, 0)]] + closing)


def _command_markers() -> tuple[str, str]:
    """The widest part-marker pair one message can carry.

    The digit count comes from the part guard, so the widest index/total pair
    the caller can ever print is already paid for.
    """
    digits = len(str(_MAX_COMMAND_MESSAGE_PARTS + 1))
    return (
        "--- 출력 " + "9" * digits + "/" + "9" * digits + " 시작 ---",
        "--- 출력 끝 ---",
    )


def _command_part_budget(head: list[str]) -> int:
    """How many characters one output part may use in this message shape.

    Derived, never estimated: the shared per-message bound minus the message
    head minus the marker frame around the part.
    """
    start, end = _command_markers()
    return _MAX_COMMAND_MESSAGE_CHARS - len("\n".join(head)) - len(start) - len(end) - 3


def _command_head(dispatch: dict[str, Any], wire: dict[str, Any]) -> list[str]:
    """The message head, fitted so an output part always has room.

    A command can now be as long as its dispatch row allows, and the head
    echoes it. Left unbounded, every part of a large output would overflow the
    shared per-message limit and the whole result would strand on a storage
    refusal. The echo is a label and the output is the payload, so when the head
    does not fit the label keeps at most half of what the fixed header lines and
    the marker frame leave over; the full command stays in the user's own turn
    and in the dispatch row, and the mark says so.
    """
    head = _command_header(dispatch, wire)
    if _command_part_budget(head) >= 1:
        return head
    index = next(
        (position for position, line in enumerate(head)
         if line.startswith(_COMMAND_ECHO_PREFIX)),
        None,
    )
    if index is None:
        return head
    start, end = _command_markers()
    others = len("\n".join(
        line for position, line in enumerate(head) if position != index
    ))
    room = max(
        0,
        (
            _MAX_COMMAND_MESSAGE_CHARS
            - others
            - len(start)
            - len(end)
            - 4
            - len(_COMMAND_ECHO_MARK)
        ) // 2,
    )
    bounded = list(head)
    bounded[index] = bounded[index][:room] + _COMMAND_ECHO_MARK
    if _command_part_budget(bounded) >= 1:
        return bounded
    # No label fits beside the output at all: drop it rather than let the
    # message carry no result. The dispatch row still holds the whole command.
    del bounded[index]
    return bounded


def _command_output_parts(output: str, limit: int) -> list[str]:
    """Partition one output so that ``"".join(parts)`` is the output verbatim.

    #4139: the former splitter kept the pending part as a joined string, so an
    empty line was indistinguishable from "nothing buffered" and every line
    boundary it crossed was swallowed — ``"\\n" + "a"*7401`` came back 7401
    characters. Each terminator now travels with its own line
    (``splitlines(keepends=True)``), so blank lines, consecutive newlines, CRLF
    and one long line reassemble byte for byte. A line longer than the limit is
    sliced, never cut, and no part is ever dropped.
    """
    if limit < 1:
        # Fail fast instead of looping: a head that leaves no room is a caller
        # bug, and slicing against a zero or negative bound would never finish.
        raise ValueError("output part limit must be at least one character")
    if len(output) <= limit:
        return [output]
    parts: list[str] = []
    buffer = ""
    for line in output.splitlines(keepends=True):
        while len(line) > limit:
            room = limit - len(buffer)
            if room > 0:
                buffer += line[:room]
                line = line[room:]
            parts.append(buffer)
            buffer = ""
        if len(buffer) + len(line) > limit:
            parts.append(buffer)
            buffer = line
        else:
            buffer += line
    if buffer:
        parts.append(buffer)
    return parts


async def oracle_mesh_read_result(request: Request) -> JSONResponse:
    """Executor submit: secret + single-use nonce, verified, appended once."""
    wire = await _read_body(request, _RESULT_KEYS, limit=_MAX_RESULT_BODY_BYTES,
                            optional=_RESULT_BLOB_KEYS)
    if wire is None:
        return _error(400, "oracle_mesh_invalid_body")
    if _ref(wire.get("dispatch_id"), 128) is None:
        return _error(400, "oracle_mesh_invalid_body")
    if _ref(wire.get("nonce"), 128) is None:
        return _error(400, "oracle_mesh_invalid_body")
    if wire.get("termination") not in (
        "exited", "cancelled", "timed_out", "no_reply", "no_exit_code",
        "not_executed", "output_too_large",
        "captured", "acted", "desktop_unavailable",
    ):
        return _error(400, "oracle_mesh_invalid_body")
    # #4139: a wait timeout and a console that never answered have NO observed
    # exit code. That is carried as null, never invented as 0; only a real
    # "exited" run must report an integer. A desktop turn never reports one
    # at all — there is no console sentinel on that lane.
    if wire.get("exit_code") is None:
        # ``no_exit_code`` keeps the code unobserved: PowerShell records
        # $LASTEXITCODE only for a native program or script, so a cmdlet-only
        # pipeline answers completely without reporting a number.
        if wire.get("termination") not in (
            "timed_out", "no_reply", "no_exit_code", "not_executed",
            "captured", "acted", "desktop_unavailable", "output_too_large",
        ):
            return _error(400, "oracle_mesh_invalid_body")
    elif isinstance(wire.get("exit_code"), bool) or not isinstance(wire.get("exit_code"), int):
        return _error(400, "oracle_mesh_invalid_body")
    if wire.get("content_bytes") == 0 and wire.get("content_sha256") == "":
        # Legacy empty-read shape: canonicalize before verification and
        # pinning so a 0-byte outcome is delivered instead of stranding.
        wire = {**wire, "content_sha256": _EMPTY_RESULT_SHA256}

    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected")
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("consume_oracle_mesh_dispatch", "finish_oracle_mesh_dispatch",
                   "mark_oracle_mesh_store_failed",
                   "record_oracle_mesh_first_result",
                   "store_oracle_mesh_original",
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
    #: #4139: the verified body of each lane, kept so a result larger than one
    #: conversation message can be split across deterministic message ids.
    command_output: str | None = None
    read_output: str | None = None
    #: #4139 desktop lane: the verified observation note, the verified
    #: screenshot bytes (None when the turn carries no image) and the op the
    #: dispatch row ordered. Messages are built after the pin below.
    desktop_note: str | None = None
    desktop_blob: bytes | None = None
    desktop_op: str | None = None
    desktop_arg: str | None = None
    result_digest = wire["content_sha256"] if wire["content_bytes"] else _EMPTY_RESULT_SHA256
    result_size = wire["content_bytes"]
    if dispatch.get("kind") != "desktop" and any(
        key in wire for key in _RESULT_BLOB_KEYS
    ):
        # Screenshot evidence on a non-desktop turn is untrusted by shape.
        # The consumed dispatch still closes as failed and nothing reaches
        # the conversation; an identical resend pins the same digest and
        # lands on the same verdict instead of appending twice.
        outcome = "failed"
        summary = "untrusted-result"
        status = "failed"
        content = (
            "실행 결과를 검증하지 못했습니다. "
            "사유: 결과 무결성 불일치."
        )
    elif dispatch.get("kind") == "command":
        # #4139 terminal lane. The body is the command output, verified with the
        # same UTF-8/SHA rules; the exit code is whatever the PC reported, and a
        # console that never answered stays "확인되지 않음". A large output is
        # split across messages, so this branch never rejects a verified result.
        verified_output = _verified_result_text(
            dispatch, wire, max_bytes=_MAX_RESULT_BODY_BYTES,
        )
        command_text = dispatch.get("command_text")
        if (
            verified_output is None
            or not isinstance(command_text, str) or not command_text
        ):
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "명령 실행 결과를 검증하지 못했습니다. "
                "사유: 결과 무결성 불일치."
            )
        else:
            content = _command_result_content(dispatch, wire, verified_output)
            command_output = verified_output
            if wire["termination"] in ("exited", "output_too_large"):
                if wire["exit_code"] == 0:
                    outcome, summary, status = "done", "exited/0", "completed"
                else:
                    outcome = "failed"
                    summary = str(wire["termination"]) + "/" + str(wire["exit_code"])
                    status = "failed"
            elif wire["termination"] == "not_executed":
                # Nothing ran, so nothing succeeded: a refusal is reported as a
                # failure of this turn without inventing a program exit code.
                outcome = "failed"
                summary = "not_executed"
                status = "failed"
            elif wire["termination"] == "no_exit_code":
                # Delivered and complete, with the code unobserved: the console
                # answered and the shell ran the appended sentinel statement, so
                # the turn is finished, while nothing here claims exit 0.
                outcome, summary, status = "done", "no_exit_code", "completed"
            else:
                outcome = "failed"
                summary = str(wire["termination"])
                status = "failed"
    elif dispatch.get("kind") == "desktop":
        # #4139 desktop lane. The note is the observation text, verified with
        # the same text rules; the screenshot (captures only) is verified
        # beside it with its own digest. A desktop turn never reports an exit
        # code — there is no console sentinel on this lane — so a non-null
        # code is untrusted. The pin covers the screenshot when one is
        # present, else the note, matching what the executor pinned first.
        parsed = _parse_desktop_op_text(dispatch.get("command_text"))
        verified_note = _verified_desktop_note(wire)
        verified_blob = _verified_desktop_blob(wire)
        if (
            parsed is None
            or verified_note is None
            or verified_blob is None
            or wire.get("exit_code") is not None
        ):
            outcome = "failed"
            summary = "untrusted-result"
            status = "failed"
            content = (
                "데스크톱 실행 결과를 검증하지 못했습니다. "
                "사유: 결과 무결성 불일치."
            )
        else:
            blob = bytes(verified_blob)
            note_raw = verified_note.encode("utf-8")
            if blob:
                pinned_ok = (
                    wire["content_sha256"] == hashlib.sha256(blob).hexdigest()
                    and wire["content_bytes"] == len(blob)
                )
            else:
                pinned_ok = (
                    wire["content_sha256"] == hashlib.sha256(note_raw).hexdigest()
                    and wire["content_bytes"] == len(note_raw)
                )
            if not pinned_ok:
                outcome = "failed"
                summary = "untrusted-result"
                status = "failed"
                content = (
                    "데스크톱 실행 결과를 검증하지 못했습니다. "
                    "사유: 결과 무결성 불일치."
                )
            else:
                desktop_op, desktop_arg = parsed
                desktop_note = verified_note
                desktop_blob = blob if blob else None
                if wire["termination"] == "captured" and blob:
                    outcome, summary, status = "done", "captured", "completed"
                    content = ""
                elif wire["termination"] == "acted" and not blob:
                    outcome, summary, status = "done", "acted", "completed"
                    content = ""
                elif wire["termination"] in (
                    "desktop_unavailable", "timed_out", "not_executed",
                    "output_too_large",
                ):
                    outcome = "failed"
                    summary = str(wire["termination"])
                    status = "failed"
                    content = ""
                else:
                    outcome = "failed"
                    summary = "untrusted-result"
                    status = "failed"
                    content = (
                        "데스크톱 실행 결과를 검증하지 못했습니다. "
                        "사유: 결과 무결성 불일치."
                    )
    elif wire["termination"] == "exited" and wire["exit_code"] == 0:
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
            content = (
                "PC 파일 읽기 결과\n--- 출력 1/1 시작 ---\n"
                + (verified_text if verified_text else "(빈 파일)")
                + "\n--- 출력 끝 ---"
            )
            read_output = verified_text if verified_text else None
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
    # Every stored message is now bounded by the splitter, so the former
    # 1 000-character refusal has no case left to serve.

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
        # A pin failure must stay retryable: park the received row so the
        # identical resend is accepted as claim="retry" instead of dying
        # on 409. Pin comparison and idempotent append still prevent any
        # second delivery.
        try:
            await history_store.mark_oracle_mesh_store_failed(
                dispatch_id=wire["dispatch_id"],
            )
        except Exception:
            pass
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

    base_message_id = result_message_id(
        conversation_id=conversation_id,
        command_id=dispatch["command_id"],
        revision_ref=dispatch["revision_ref"],
    )
    if command_output is not None:
        if wire["termination"] == "output_too_large" and not command_output:
            # The executor withheld the body at the wire envelope, so there
            # is no original to store and nothing to split: the observed
            # exit code is delivered with an explicit non-delivery notice.
            messages = [_command_output_withheld_content(dispatch, wire)]
        else:
            head = _command_head(dispatch, wire)
            output_parts = _command_output_parts(
                command_output, _command_part_budget(head),
            )
            if len(output_parts) > _MAX_COMMAND_MESSAGE_PARTS:
                # Over the per-run message-row guard: the verified original is
                # kept in the private store first. The conversation carries a
                # head preview plus the owner-scoped retrieval reference;
                # "stored" is claimed only after the put succeeds, never before.
                try:
                    await history_store.store_oracle_mesh_original(
                        user_id=dispatch["user_id"],
                        dispatch_id=wire["dispatch_id"],
                        conversation_id=conversation_id,
                        message_id=base_message_id,
                        raw=command_output,
                        expected_sha256=result_digest,
                        expected_bytes=result_size,
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
                    # Storage failed: park the row so the executor resends
                    # the SAME bytes. No completion is reported, and the PC
                    # command is never re-run for a store failure.
                    try:
                        await history_store.mark_oracle_mesh_store_failed(
                            dispatch_id=wire["dispatch_id"],
                        )
                    except Exception:
                        pass
                    return _error(503, "oracle_mesh_original_unavailable")
                messages = [_command_original_stored_content(
                    dispatch, wire, command_output,
                )]
            else:
                messages = _command_part_messages(head, output_parts)
    elif read_output is not None:
        head = ["PC 파일 읽기 결과"]
        output_parts = _command_output_parts(
            read_output, _command_part_budget(head),
        )
        if len(output_parts) > _MAX_COMMAND_MESSAGE_PARTS:
            # The read lane carries the same guard as the command lane. The
            # verified file body is stored whole first, so a large document
            # becomes a preview plus a retrieval reference instead of either
            # hundreds of messages or a silent refusal.
            try:
                await history_store.store_oracle_mesh_original(
                    user_id=dispatch["user_id"],
                    dispatch_id=wire["dispatch_id"],
                    conversation_id=conversation_id,
                    message_id=base_message_id,
                    raw=read_output,
                    expected_sha256=result_digest,
                    expected_bytes=result_size,
                )
            except HistoryForbidden:
                try:
                    await history_store.finish_oracle_mesh_dispatch(
                        dispatch_id=wire["dispatch_id"], outcome="failed",
                    )
                except Exception:
                    pass
                return _error(403, "oracle_mesh_conversation_forbidden")
            except Exception:
                try:
                    await history_store.mark_oracle_mesh_store_failed(
                        dispatch_id=wire["dispatch_id"],
                    )
                except Exception:
                    pass
                return _error(503, "oracle_mesh_original_unavailable")
            messages = [_file_read_stored_content(dispatch, wire, read_output)]
        else:
            messages = _file_read_part_messages(output_parts)
    elif desktop_note is not None and desktop_op is not None:
        # #4139 desktop lane. A capture stores its screenshot bytes first:
        # "stored" is claimed only after the put succeeds, never before. An
        # input or failed turn carries its note directly; notes are short by
        # construction (executor observations, never file bodies).
        if desktop_blob is not None:
            if not callable(getattr(
                history_store, "store_oracle_mesh_original_bytes", None
            )):
                return _error(503, "oracle_mesh_unconfigured")
            try:
                await history_store.store_oracle_mesh_original_bytes(
                    user_id=dispatch["user_id"],
                    dispatch_id=wire["dispatch_id"],
                    conversation_id=conversation_id,
                    message_id=base_message_id,
                    raw=desktop_blob,
                    media_type=_DESKTOP_SCREENSHOT_MEDIA_TYPE,
                    expected_sha256=result_digest,
                    expected_bytes=result_size,
                )
            except HistoryForbidden:
                try:
                    await history_store.finish_oracle_mesh_dispatch(
                        dispatch_id=wire["dispatch_id"], outcome="failed",
                    )
                except Exception:
                    pass
                return _error(403, "oracle_mesh_conversation_forbidden")
            except Exception:
                try:
                    await history_store.mark_oracle_mesh_store_failed(
                        dispatch_id=wire["dispatch_id"],
                    )
                except Exception:
                    pass
                return _error(503, "oracle_mesh_original_unavailable")
            messages = [_desktop_capture_content(
                dispatch, wire, desktop_op, desktop_arg,
                desktop_note, result_digest,
            )]
        elif summary in ("acted",):
            messages = [_desktop_act_content(
                dispatch, wire, desktop_op, desktop_arg, desktop_note,
            )]
        else:
            messages = [_desktop_failed_content(
                dispatch, wire, desktop_op, desktop_arg, desktop_note,
            )]
    else:
        messages = [content]
    appended = False
    try:
        for index, part in enumerate(messages):
            message_id = base_message_id if len(messages) == 1 else (
                base_message_id + "_p" + str(index)
            )
            appended = await history_store.append_local_task_result(
                user_id=dispatch["user_id"],
                run_id=dispatch["run_id"],
                message_id=message_id,
                summary=summary,
                content=part,
                status=status,
                # A terminal result is the only caller that opts out of the
                # shared edge trim; every other message keeps today's behavior.
                preserve_edges=(dispatch.get("kind") == "command"),
            ) or appended
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


async def oracle_mesh_read_original(request: Request) -> Response:
    """Owner-scoped read of one stored over-budget command original.

    Only the dispatch id comes from the browser. The dispatch row (owner,
    run, correlation), the originating conversation and the deterministic
    result id are all re-derived server-side, so no browser-chosen object
    key or foreign-account result is addressable. Unknown ids, foreign
    accounts and missing objects all answer 404 without disclosing which
    part failed; a stored object that disagrees with the dispatch pin is a
    503, never served bytes.
    """
    uid = current_user_id(request)
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required")
    params = getattr(request, "path_params", None) or {}
    dispatch_id = _ref(params.get("dispatch_id"), 128)
    if dispatch_id is None:
        return _error(404, "oracle_mesh_original_unavailable")
    history_store = getattr(request.app.state, "history_store", None)
    for method in ("get_oracle_mesh_dispatch_for_owner", "get_claw_run",
                   "read_oracle_mesh_original"):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured")
    try:
        dispatch = await history_store.get_oracle_mesh_dispatch_for_owner(
            user_id=uid, dispatch_id=dispatch_id,
        )
    except Exception:
        return _error(503, "oracle_mesh_unconfigured")
    if not isinstance(dispatch, dict):
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        run_row = await history_store.get_claw_run(uid, dispatch.get("run_id"))
    except Exception:
        run_row = None
    conversation_id = (
        validate_conversation_id((run_row or {}).get("conversation_id"))
        if isinstance(run_row, dict) else None
    )
    if not conversation_id:
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        message_id = result_message_id(
            conversation_id=conversation_id,
            command_id=dispatch.get("command_id"),
            revision_ref=dispatch.get("revision_ref"),
        )
    except Exception:
        return _error(404, "oracle_mesh_original_unavailable")
    try:
        stored = await history_store.read_oracle_mesh_original(
            user_id=uid, dispatch_id=dispatch_id,
            conversation_id=conversation_id, message_id=message_id,
        )
    except HistoryError:
        return _error(503, "oracle_mesh_original_unavailable")
    except Exception:
        return _error(503, "oracle_mesh_unconfigured")
    if stored is None:
        return _error(404, "oracle_mesh_original_unavailable")
    payload, pinned_sha = stored
    if dispatch.get("kind") == "desktop":
        # A desktop capture serves its screenshot bytes. The pin already
        # binds these exact bytes; the magic is rechecked so a non-image can
        # never leave through the image path.
        if not payload.startswith(_DESKTOP_SCREENSHOT_MAGIC):
            return _error(503, "oracle_mesh_original_unavailable")
        return Response(
            payload, media_type="image/jpeg",
            headers={**_NO_STORE, "X-Oracle-Mesh-Content-SHA256": pinned_sha},
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return _error(503, "oracle_mesh_original_unavailable")
    return Response(
        text, media_type="text/plain; charset=utf-8",
        headers={**_NO_STORE, "X-Oracle-Mesh-Content-SHA256": pinned_sha},
    )


async def oracle_mesh_engine_desktop_call(request: Request) -> JSONResponse:
    """Engine-only authenticated desktop dispatch; browser cookies never act as proof.

    A signed call carries only an owner session reference and existing run id.
    Control Plane must resolve the current session independently before the
    existing owner-scoped desktop dispatch may run.
    """
    import hmac
    import hashlib
    import time

    secret = getattr(request.app.state, "claw_engine_desktop_secret", None)
    if not isinstance(secret, str) or len(secret) < 32:
        return _error(503, "claw_engine_desktop_unconfigured")
    raw = await request.body()
    if len(raw) > 8192:
        return _error(413, "claw_engine_desktop_invalid_body")
    timestamp = request.headers.get("X-Claw-Engine-Time", "")
    signature = request.headers.get("X-Claw-Engine-Proof", "")
    try:
        seconds = int(timestamp)
    except (ValueError, TypeError):
        return _error(401, "claw_engine_proof_required")
    if abs(int(time.time()) - seconds) > 60 or not isinstance(signature, str) or len(signature) != 64:
        return _error(401, "claw_engine_proof_required")
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return _error(401, "claw_engine_proof_required")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _error(400, "claw_engine_desktop_invalid_body")
    status_query = isinstance(payload, dict) and payload.get("mode") in ("status", "image")
    expected_keys = (
        {"subject_id", "run_id", "dispatch_id", "mode"} if status_query
        else {"subject_id", "run_id", "device_id", "desktop_op"}
    )
    if (not isinstance(payload, dict)
        or set(payload) != expected_keys
        or not all(
            isinstance(payload[k], str) and 0 < len(payload[k]) <= 512
            for k in ("subject_id", "run_id")
        )
        or (status_query and (not isinstance(payload["dispatch_id"], str)
            or not 0 < len(payload["dispatch_id"]) <= 128))
        or (not status_query and (
            not isinstance(payload["desktop_op"], str)
            or not 0 < len(payload["desktop_op"]) <= 512
            or (payload["device_id"] is not None and (
                not isinstance(payload["device_id"], str)
                or not 0 < len(payload["device_id"]) <= 128))))):
        return _error(400, "claw_engine_desktop_invalid_body")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if (not callable(getattr(identity, "resolve_product_user_for_subject", None))
        or not callable(getattr(identity, "resolve_current_auth_session", None))):
        return _error(503, "claw_engine_identity_unavailable")
    try:
        uid = await identity.resolve_product_user_for_subject(
            product_id="b54-padiem-claw",
            canonical_subject_id=payload["subject_id"],
        )
        session = await identity.resolve_current_auth_session(
            product_id="b54-padiem-claw", product_user_id=uid,
        )
    except Exception:
        return _error(401, "canonical_session_required")
    from datetime import datetime, timezone
    if (session is None or session.subject.subject_id != payload["subject_id"]
        or session.product_id != "b54-padiem-claw"
        or not session.is_active(now=datetime.now(timezone.utc))
        or not session.tenant_id):
        return _error(401, "canonical_session_required")
    if status_query:
        history_store = getattr(request.app.state, "history_store", None)
        reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
        if not callable(reader):
            return _error(503, "oracle_mesh_unconfigured")
        try:
            dispatch = await reader(
                user_id=uid, dispatch_id=payload["dispatch_id"],
            )
        except Exception:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        if (not isinstance(dispatch, dict)
            or dispatch.get("run_id") != payload["run_id"]
            or dispatch.get("kind") != "desktop"):
            return _error(404, "oracle_mesh_run_unavailable")
        state = dispatch.get("state")
        if payload["mode"] == "image":
            if state != "done" or not isinstance(dispatch.get("result_sha256"), str):
                return _error(409, "oracle_mesh_capture_not_ready")
            try:
                run = await history_store.get_claw_run(uid, payload["run_id"])
                conversation_id = validate_conversation_id(
                    (run or {}).get("conversation_id")
                )
                if not conversation_id:
                    return _error(404, "oracle_mesh_run_unavailable")
                message_id = result_message_id(
                    conversation_id=conversation_id,
                    command_id=dispatch["command_id"],
                    revision_ref=dispatch["revision_ref"],
                )
                stored = await history_store.read_oracle_mesh_original(
                    user_id=uid, dispatch_id=dispatch["dispatch_id"],
                    conversation_id=conversation_id, message_id=message_id,
                )
            except Exception:
                return _error(503, "oracle_mesh_original_unavailable")
            if stored is None:
                return _error(404, "oracle_mesh_original_unavailable")
            raw, digest = stored
            if (not isinstance(raw, bytes) or not raw.startswith(b"\xff\xd8\xff")
                or digest != dispatch["result_sha256"]):
                return _error(503, "oracle_mesh_original_unavailable")
            return Response(
                raw, media_type="image/jpeg",
                headers={**_NO_STORE, "X-Oracle-Mesh-Content-SHA256": digest},
            )
        if state not in {"pending", "received", "store_failed", "done", "failed"}:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        return _response({
            "ok": True,
            "dispatch": {
                "dispatch_id": dispatch["dispatch_id"],
                "run_id": payload["run_id"],
                "kind": "desktop",
                "state": state,
                "result_sha256": dispatch.get("result_sha256"),
            },
        })
    return await dispatch_oracle_mesh_desktop_intent(
        request, desktop_op=payload["desktop_op"],
        wire={"run_id": payload["run_id"], "device_id": payload["device_id"], "confirmed": True},
        trusted_owner=(session, uid, session.tenant_id),
    )
