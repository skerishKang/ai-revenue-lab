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
from .request_telemetry import emit_stage_event

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
#: #4139 result envelope. The Claw request route already accepts a 6 MB
#: body for one user message, so a command result is bounded by the same
#: proven limit instead of a trial-era 8 KB.
_MAX_RESULT_BODY_BYTES = 6_000_000
#: One stored conversation message. Existing product bound
#: (history.HistoryStore.MAX_HISTORY_MESSAGE_CHARS): a larger output is
#: split across several messages, never truncated.
_MAX_COMMAND_MESSAGE_CHARS = 8000
#: Storage guard for one command result: 256 parts of 8 000 characters is
#: ~2 MB of stored text. Beyond it the output is withheld with an explicit
#: message instead of filling a conversation.
_MAX_COMMAND_MESSAGE_PARTS = 256
#: Headroom the message head (command, method, stream, exit state, markers)
#: needs on top of an output chunk, so a stored message never exceeds the
#: shared per-message bound.
_COMMAND_HEADER_CHARS = 600
#: A path or a command may contain Korean (or any non-ASCII) characters.
#: The only forbidden characters are control characters.
_MAX_PATH_VALUE_CHARS = 1024
_SAFE_REF_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:@+-"
)
#: #4139 read lane envelope, shared with the command lane and the executor.
#: The former 768-byte trial cap could not read a normal document; a larger
#: body is split across conversation messages, never truncated.
_MAX_FILE_TEXT_BYTES = _MAX_RESULT_BODY_BYTES
#: #4139 command lane display limit is gone: an output larger than one
#: conversation message is split, and an output larger than the wire
#: envelope is reported as oversize. Nothing is silently dropped.
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
_MAX_COMMAND_OUTPUT_BYTES = 3000

_REQUEST_KEYS = frozenset({"device_id", "run_id", "root_ref", "path_relative", "confirmed"})
_RESULT_KEYS = frozenset({
    "dispatch_id", "nonce", "termination", "exit_code",
    "content_utf8", "content_sha256", "content_bytes",
})

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


def _read_json(raw: bytes, keys: frozenset, limit: int = _MAX_BODY_BYTES) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if type(value) is not dict or set(value) != keys:
        return None
    return value


def _text_value(value: Any, limit: int = 1024) -> str | None:
    """A path, a file name or a command: any language, no control characters.

    Windows paths, Korean file names and UTF-8 commands are ordinary input, so
    the ASCII-only reference alphabet does not apply here. The bound is length
    plus "no control characters"; nothing else is restricted.
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
    return _read_json(raw, keys, limit)


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


def _command_output_too_large_content(
    dispatch: dict[str, Any], wire: dict[str, Any], output_chars: int,
) -> str:
    """A result whose output would fill the conversation with hundreds of parts.

    The output itself is verified and pinned (bytes and digest are on the
    dispatch row), so nothing is silently dropped; only the stored text is
    withheld, with the exact size and the storage bound stated.
    """
    lines = _command_header(dispatch, wire)
    lines.append(
        "출력 " + str(output_chars) + "자가 저장 한도 "
        + str(_MAX_COMMAND_MESSAGE_PARTS) + "개 메시지를 초과하여 대화에 싣지 않았습니다."
    )
    lines.append("출력 본문과 SHA-256은 dispatch에 그대로 보관되어 있습니다.")
    return "\n".join(lines)


def _command_output_parts(output: str, limit: int = 8000) -> list[str]:
    """Split one output into conversation-sized parts on line boundaries.

    A larger result is stored as several messages through the existing message
    append path; no part is ever truncated, and line boundaries are preserved
    because a shell output is read line by line.
    """
    if len(output) <= limit:
        return [output]
    parts: list[str] = []
    current = ""
    for line in output.split("\n"):
        # A single line may itself exceed the bound (one long JSON dump, one
        # base64 blob): it is split on characters so nothing is dropped.
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > limit and current:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current or not parts:
        parts.append(current)
    return parts


async def oracle_mesh_read_result(request: Request) -> JSONResponse:
    """Executor submit: secret + single-use nonce, verified, appended once."""
    wire = await _read_body(request, _RESULT_KEYS, limit=_MAX_RESULT_BODY_BYTES)
    if wire is None:
        return _error(400, "oracle_mesh_invalid_body")
    if _ref(wire.get("dispatch_id"), 128) is None:
        return _error(400, "oracle_mesh_invalid_body")
    if _ref(wire.get("nonce"), 128) is None:
        return _error(400, "oracle_mesh_invalid_body")
    if wire.get("termination") not in (
        "exited", "cancelled", "timed_out", "no_reply", "output_too_large",
    ):
        return _error(400, "oracle_mesh_invalid_body")
    # #4139: a wait timeout and a console that never answered have NO observed
    # exit code. That is carried as null, never invented as 0; only a real
    # "exited" run must report an integer.
    if wire.get("exit_code") is None:
        if wire.get("termination") not in ("timed_out", "no_reply"):
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
    result_digest = wire["content_sha256"] if wire["content_bytes"] else _EMPTY_RESULT_SHA256
    result_size = wire["content_bytes"]
    if dispatch.get("kind") == "command":
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
            else:
                outcome = "failed"
                summary = str(wire["termination"])
                status = "failed"
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
        output_parts = _command_output_parts(
            command_output, _MAX_COMMAND_MESSAGE_CHARS - _COMMAND_HEADER_CHARS,
        )
        if len(output_parts) > _MAX_COMMAND_MESSAGE_PARTS:
            # Storage guard, never a silent drop: the byte count is reported.
            messages = [_command_output_too_large_content(
                dispatch, wire, len(command_output),
            )]
        else:
            total = str(len(output_parts))
            head = _command_header(dispatch, wire)
            messages = []
            for index, part in enumerate(output_parts):
                lines = list(head)
                lines.append("--- 출력 " + str(index + 1) + "/" + total + " 시작 ---")
                lines.append(part)
                lines.append("--- 출력 끝 ---")
                messages.append("\n".join(lines))
    elif read_output is not None:
        output_parts = _command_output_parts(
            read_output, _MAX_COMMAND_MESSAGE_CHARS - _COMMAND_HEADER_CHARS,
        )
        total = str(len(output_parts))
        messages = []
        for index, part in enumerate(output_parts):
            lines = ["PC 파일 읽기 결과"]
            lines.append("--- 출력 " + str(index + 1) + "/" + total + " 시작 ---")
            lines.append(part)
            lines.append("--- 출력 끝 ---")
            messages.append("\n".join(lines))
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
