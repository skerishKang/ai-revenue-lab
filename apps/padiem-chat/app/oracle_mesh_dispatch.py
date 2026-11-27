"""Oracle Mesh owner request and dispatch staging."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from padiem_ai_core.pc_device_identity import is_pc_device_id

from .auth_routes import current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .claw_memory_routes import _resolve_memory_workspace
from .connector_account_shadow import mode_connector_read
from .control_plane_identity import IdentityBridgeError
from .history import HistoryError, HistoryForbidden
from .pc_dispatch_ttl import dispatch_ttl_seconds
from .request_telemetry import emit_stage_event
from .oracle_mesh_contract import (
    EXECUTION_MODE_MESH, _COMMAND_FILE_SENTINEL, _COMMAND_PATH_RELATIVE,
    _COMMAND_ROOT_REF, _DISPATCH_TTL, _REQUEST_KEYS,
)
from .oracle_mesh_http import (
    _channel_source, _error, _invalid_body, _read_body, _ref, _response, _text_value,
)
from .oracle_mesh_pc_paths import _PC_FILES_READ_ROOT_REF, _PC_FILES_SAFE_REF
from .oracle_mesh_desktop_ops import _parse_desktop_op_text
from .oracle_mesh_source import OracleMeshReturnSource


async def oracle_mesh_read_request(request: Request) -> JSONResponse:
    """Owner intent: verify everything server-side, stage one dispatch."""
    if _channel_source(request) is None:
        return _error(503, "oracle_mesh_unconfigured")
    wire = await _read_body(request, _REQUEST_KEYS)
    if wire is None:
        return _invalid_body("read_request")
    for key in ("device_id", "run_id", "root_ref"):
        if _ref(wire.get(key)) is None:
            return _invalid_body("read_request", "ref:" + key)
    if _text_value(wire.get("path_relative")) is None:
        return _invalid_body("read_request", "path_relative")
    if wire.get("confirmed") is not True:
        return _invalid_body("read_request", "confirmed")
    return await dispatch_oracle_mesh_read_intent(request, wire)


async def _dispatch_workspace_id(request: Request, uid: str, session: Any) -> str | None:
    """The workspace one staged dispatch is written under.

    The memory shadow pointer answers first, exactly as it always has. When
    that non-authoritative local pointer is absent or stale (its session was
    rotated or expired), the canonical session this request already verified
    owns the same workspace: its tenant. This is the fallback the PC lane
    applies in ``chat_pc_drive._resolve_chat_owner``; the engine files lane
    kept hard-failing on the pointer alone, so a stale row refused every
    dispatch the authority itself had already answered for (2026-11-09).
    """
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace_id = None
    if not isinstance(workspace_id, str) or not workspace_id:
        workspace_id = getattr(session, "tenant_id", None)
    return workspace_id if isinstance(workspace_id, str) and workspace_id else None


async def dispatch_oracle_mesh_read_intent(
    request: Request, wire: dict[str, Any]
) -> JSONResponse:
    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return denial if denial is not None else _error(401, "canonical_session_required")
    uid = current_user_id(request)
    workspace_id = await _dispatch_workspace_id(request, uid, session)
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
        consent = await mode_connector_read(
            identity, "consent", session_id=session.session_id, device_id=wire["device_id"],
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
        scope = await mode_connector_read(
            identity, "owner_scope", session_id=session.session_id,
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


async def _active_owner_link_node(
    request: Request, *, user_id: str | None, device_id: str | None,
) -> str | None:
    """The owner's exact active link for this PC, or ``None``.

    #6801 made the linked PC the command target. The deployment map's unpinned
    row names no PC, so a token-pinned device must travel to the linked node
    instead of the row's placeholder ref.
    """
    if not isinstance(user_id, str) or not user_id:
        return None
    if not isinstance(device_id, str) or not device_id:
        return None
    store = getattr(request.app.state, "pc_device_pairing_store", None)
    if not callable(getattr(store, "links_for_owner", None)):
        return None
    try:
        links = await store.links_for_owner(user_id=user_id)
    except Exception:
        return None
    for link in links if isinstance(links, list) else []:
        if (isinstance(link, dict) and link.get("mesh_node_id") == device_id
                and link.get("state") == "active"):
            return device_id
    return None


async def _owner_command_target(
    request: Request, mesh_source: Any, *, account_ref: str | None,
    owner_id: str | None, device_id: str | None,
) -> dict[str, Any] | None:
    """Resolve the deployment command row for this owner, then pin an unpinned hit.

    The map rows in this deployment are keyed by the verified product user id,
    while the connector scope answers a different account-ref axis; the grant
    lane already falls back to the token owner (#6792). The terminal lane needs
    the same fallback, or a valid command grant reads as unverified.
    """
    target: dict[str, Any] | None = None
    tried: set[str] = set()
    for ref in (account_ref, owner_id):
        if not isinstance(ref, str) or not ref or ref in tried:
            continue
        tried.add(ref)
        target = mesh_source.command_target(account_ref=ref, device_id=device_id)
        if target is not None:
            break
    if target is None:
        return None
    if target.get("device_id") is None:
        linked = await _active_owner_link_node(
            request, user_id=owner_id, device_id=device_id,
        )
        if linked is not None:
            return {**target, "device_id": linked, "node_ref": linked}
    return target


async def dispatch_oracle_mesh_command_intent(
    request: Request, *, command: str, wire: dict[str, Any],
    trusted_owner: tuple[Any, str, str] | None = None,
    tool_call_ref: str | None = None,
    files_target: dict[str, Any] | None = None,
    background: bool = False,
    job_operation: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
    user_mode: bool = False,
    read_only: bool = False,
    share_roots: list[str] | None = None,
    helper_update_control: bool = False,
    maintenance_before_write=None,
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

    ``files_target`` is how the PC-files lane passes the target it already
    resolved from this account's own PC links (#5573). It is server-derived and
    never a caller value, and it exists so the folder the model was told about
    and the device that receives the command cannot be chosen twice and drift.
    A deployment with no directory to ask passes the map row it resolved, so the
    behaviour is unchanged; the terminal lane passes nothing at all and keeps
    asking the map.
    """
    if trusted_owner is None:
        session, denial = await _verified_owner_request(request)
        if denial is not None or session is None:
            return denial if denial is not None else _error(401, "canonical_session_required")
        uid = current_user_id(request)
        workspace_id = await _dispatch_workspace_id(request, uid, session)
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
    if not isinstance(command, str) or not command.strip():
        return _error(422, "oracle_mesh_command_invalid")
    if ttl_seconds is not None and (
            not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool)
            or not 1 <= ttl_seconds <= 3600):
        return _error(422, "oracle_mesh_ttl_invalid")

    try:
        scope = await mode_connector_read(identity, "owner_scope", session_id=session.session_id)
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

    if files_target is not None:
        # The file lane resolved this account's own PC already. Resolving it a
        # second time against the map here is how a folder and a device start
        # disagreeing, so the resolved target is the authority for this call.
        target = files_target
        if (
            not isinstance(target, dict)
            or not isinstance(target.get("node_ref"), str)
            or not is_pc_device_id(target["node_ref"])
        ):
            return _error(403, "oracle_mesh_command_unverified")
    else:
        target = await _owner_command_target(
            request, mesh_source, account_ref=account_ref,
            owner_id=uid, device_id=selected,
        )
    if target is None:
        return _error(403, "oracle_mesh_command_unverified")

    from .pc_helper_update_routes import command_update_denial
    fixed_install = False
    if maintenance_before_write is not None:
        from .pc_helper_registration import is_fixed_system_refresh_command
        from .pc_helper_install import is_fixed_system_install_command
        from .pc_helper_version_routes import helper_manifest
        fixed_install = is_fixed_system_install_command(
            command, manifest=helper_manifest(request.app.state), user_mode=user_mode)
        if (not callable(maintenance_before_write) or trusted_owner is None
                or user_mode is not False or background or read_only or helper_update_control
                or ttl_seconds != 300 or wire.get("confirmed") is not True
                or not (fixed_install or is_fixed_system_refresh_command(command, user_mode=user_mode))):
            return _error(403, "oracle_mesh_command_unverified")
    update_denial = None if fixed_install else await command_update_denial(
        request.app.state, device_id=target.get("device_id") or target["node_ref"],
        command=command, user_mode=user_mode, helper_update_control=helper_update_control,
        now=datetime.now(timezone.utc),
    )
    if update_denial is not None:
        return _error(*update_denial)

    try:
        bound = await history_store.get_local_task_correlation(uid, wire["run_id"])
    except Exception:
        bound = None
    broker_admitted = (
        tool_call_ref is None
        and isinstance(bound, dict)
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
        # A file tool call is keyed by its stable per-call reference, so the
        # same call inside one run cannot execute twice. Other lanes keep the
        # generated dispatch-scoped reference.
        tool_request_ref = tool_call_ref or ("oracle_mesh_tool_" + suffix)
        request_id = "oracle_mesh_req_" + suffix
        revision_ref = "oracle_mesh_rev_" + suffix
        evidence_ref = None
        # The command is part of the correlation: a different command for the
        # same run is a different request, never a silent retarget.
        request_fingerprint = hashlib.sha256(
            (account_ref + "|" + target["node_ref"] + "|" + command).encode("utf-8")
        ).hexdigest()

    if ttl_seconds is None:
        ttl_seconds = dispatch_ttl_seconds(run_row)
    now = datetime.now(timezone.utc)
    try:
        # A maintenance row is the execution authority. Re-read all host-side
        # authority facts here, after all awaits used to prepare the row.
        if maintenance_before_write is not None and await maintenance_before_write() is not True:
            return _error(403, "oracle_mesh_command_unverified")
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
            expires_at=(now + (_DISPATCH_TTL if ttl_seconds is None
                               else timedelta(seconds=ttl_seconds))).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            kind="command",
            command_text=command,
            tool_call_ref=tool_call_ref,
            read_only=read_only,
            **({"share_roots": share_roots} if share_roots else {}),
            **({"background": True, "job_operation": job_operation} if background else {}),
            user_mode=user_mode,
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
            # Echo the server-resolved target so the caller can prove the
            # signed dispatch used the same PC it named to the model.
            "device_id": target.get("device_id") or target["node_ref"],
            "execution": "server_owned",
            "broker_acknowledged": False,
            "user_mode": user_mode,
        },
    })


async def dispatch_oracle_mesh_file_read_intent(
    request: Request, *, wire: dict[str, Any],
    trusted_owner: tuple[Any, str, str],
    tool_call_ref: str,
    target: dict[str, Any],
    root: str,
    relative: str,
    background: bool = False,
    job_operation: dict[str, Any] | None = None,
    user_mode: bool = False,
    ttl_seconds: int | None = None,
) -> JSONResponse:
    """Stage ONE PC-files read on the existing kind="read" Mesh lane.

    #5015: the Engine has already resolved the canonical owner, workspace and
    deployment target (the same target the list call used). This function
    reuses the command lane's authority checks and dispatch correlation, then
    stages a read row instead of a shell command. It does not open a browser
    session, does not accept a command, and does not add a second store: the
    existing executor reads the file with ``meshctrl.js download`` and the
    existing result route pins/stores the verified bytes.
    """
    session, uid, workspace_id = trusted_owner
    if (
        not uid or not workspace_id
        or not getattr(session, "tenant_id", None)
    ):
        return _error(401, "canonical_session_required")

    mesh_source = _channel_source(request)
    if mesh_source is None or mesh_source.execution_mode != EXECUTION_MODE_MESH:
        return _error(503, "oracle_mesh_unconfigured")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    history_store = getattr(request.app.state, "history_store", None)
    for method in (
        "get_claw_run", "get_local_task_correlation", "create_oracle_mesh_dispatch",
    ):
        if not callable(getattr(history_store, method, None)):
            return _error(503, "oracle_mesh_unconfigured")
    if not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return _error(503, "oracle_mesh_unconfigured")

    selected = wire.get("device_id")
    if selected is not None and (not isinstance(selected, str) or not selected):
        return _error(422, "oracle_mesh_device_invalid")
    if (
        not isinstance(tool_call_ref, str)
        or _PC_FILES_SAFE_REF.fullmatch(tool_call_ref) is None
        or not isinstance(root, str) or not root
        or not isinstance(relative, str) or not relative
        or not isinstance(target, dict)
        or not isinstance(target.get("node_ref"), str) or not target["node_ref"]
    ):
        return _error(422, "oracle_mesh_file_call_invalid")

    try:
        scope = await mode_connector_read(
            identity, "owner_scope", session_id=session.session_id,
        )
    except Exception as exc:
        emit_stage_event(
            stage="mesh.files_owner_scope", outcome="error", duration_ms=0,
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

    node_ref = target["node_ref"]
    device_id = target.get("device_id") or node_ref
    if not isinstance(device_id, str) or not device_id:
        return _error(422, "oracle_mesh_file_call_invalid")
    # The target row supplies the approved root; the relative path is the
    # caller's already-validated file inside that root. The command lane uses
    # the same root + relative shape, so a read cannot target another folder.
    file_path = root + "/" + relative

    # #5015: the Engine file tools are per-call correlated. A broker-admitted
    # legacy correlation belongs to the run's single-command lane and is never
    # borrowed here; the tool call reference is the exact correlation key.
    suffix = uuid.uuid4().hex
    cmd_id = "oracle_mesh_cmd_" + suffix
    request_id = "oracle_mesh_req_" + suffix
    revision_ref = "oracle_mesh_rev_" + suffix
    evidence_ref = None
    # The read target is part of the correlation: a different file for the same
    # tool call is a different request, never a silent retarget.
    request_fingerprint = hashlib.sha256(
        (
            account_ref + "|" + node_ref + "|read|" + file_path
        ).encode("utf-8")
    ).hexdigest()

    if ttl_seconds is None:
        ttl_seconds = dispatch_ttl_seconds(run_row)
    now = datetime.now(timezone.utc)
    try:
        dispatch = await history_store.create_oracle_mesh_dispatch(
            user_id=uid,
            run_id=wire["run_id"],
            command_id=cmd_id,
            tool_request_ref=tool_call_ref,
            request_id=request_id,
            revision_ref=revision_ref,
            evidence_ref=evidence_ref,
            request_fingerprint=request_fingerprint,
            account_ref=account_ref,
            workspace_ref=connector_workspace_ref,
            device_id=device_id,
            binding_ref=None,
            node_ref=node_ref,
            root_ref=_PC_FILES_READ_ROOT_REF,
            path_relative=relative,
            file_path=file_path,
            expires_at=(now + (_DISPATCH_TTL if ttl_seconds is None
                               else timedelta(seconds=ttl_seconds))).isoformat(
                timespec="milliseconds",
            ).replace("+00:00", "Z"),
            kind="read",
            tool_call_ref=tool_call_ref,
            read_only=True,
            **({"background": True, "job_operation": job_operation} if background else {}),
            user_mode=user_mode,
        )
    except HistoryForbidden:
        return _error(404, "oracle_mesh_run_unavailable")
    except HistoryError as exc:
        if str(exc) == "oracle mesh dispatch row exceeds the storage row bound":
            return _error(413, "oracle_mesh_dispatch_too_large")
        if str(exc) == "oracle mesh command execution is uncertain":
            # A read has no PC mutation, but the existing dispatch guard still
            # owns the decision. It is surfaced, never retried in disguise.
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
            "kind": "read",
            "device_id": device_id,
            "execution": "server_owned",
            "broker_acknowledged": False,
        },
    })

async def dispatch_oracle_mesh_desktop_intent(
    request: Request, *, desktop_op: str, wire: dict[str, Any],
    trusted_owner: tuple[Any, str, str] | None = None,
    tool_call_ref: str | None = None,
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

    ``tool_call_ref`` is the per-call dispatch scope the model-driven loop
    needs: one run holds one dispatch per step instead of one dispatch in
    total, and a re-sent step still correlates to its own row and is refused
    rather than executed a second time.
    """
    if trusted_owner is None:
        session, denial = await _verified_owner_request(request)
        if denial is not None or session is None:
            return denial if denial is not None else _error(401, "canonical_session_required")
        uid = current_user_id(request)
        workspace_id = await _dispatch_workspace_id(request, uid, session)
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
        scope = await mode_connector_read(identity, "owner_scope", session_id=session.session_id)
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
    # #6460 step 3 — an owner's 그만 is authoritative: no new PC action is
    # dispatched for a run that was stopped, however late the request arrives.
    if run_row.get("status") == "cancelled":
        return _error(409, "oracle_mesh_run_stopped")

    target = await _owner_command_target(
        request, mesh_source, account_ref=account_ref,
        owner_id=uid, device_id=selected,
    )
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
        # A loop step's own call reference is its correlation: the same step
        # re-sent finds its row instead of staging a second execution.
        tool_request_ref = tool_call_ref or ("oracle_mesh_tool_" + suffix)
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
            tool_call_ref=tool_call_ref,
            read_only=False,
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
