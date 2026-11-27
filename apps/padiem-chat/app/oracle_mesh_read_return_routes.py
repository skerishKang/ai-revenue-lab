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
import contextvars
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.powershell_literal import ps_literal, ps_utf8_literal
from .oracle_mesh_log import (
    _RESULT_LOG,
    ensure_result_log_host_visible,
    _identity_bridge_failure_log_line,
    _PC_RESULT_ACTION_WORDS,
    _PC_RESULT_STATUS_WORDS,
    _PC_RESULT_REASON_WORDS,
    _pc_result_word,
    log_pc_result_store_stage,
)

from .pc_device_pairing_store import PcPairingError
from .pc_dispatch_ttl import chat_pc_dispatch_ttl, dispatch_ttl_seconds
from .pc_share_timeout import (
    PC_SHARE_UNAVAILABLE_CODE,
    PC_SHARE_UNAVAILABLE_MESSAGE_KO,
    share_command_prefix,
    share_roots_of,
)

from .auth_routes import current_user_id
from .claw_connector_enrollment_routes import _verified_owner_request
from .journal_host import ensure_journal_visible
from .claw_memory_routes import _resolve_memory_workspace
from .claw_pc_read_command import (
    pc_read_chunk_command,
    pc_read_length,
    pc_read_offset,
)
from .claw_pc_search_command import (
    PC_SEARCH_MAX_LIMIT,
    PC_SEARCH_SCAN_MAX_FILES,
    pc_search_command,
    pc_search_mode,
    pc_search_path,
    pc_search_query,
    pc_search_roots,
)
from .claw_local_task_result_projection import result_message_id
from .connector_account_shadow import mode_connector_read
from .control_plane_identity import IdentityBridgeError
from .desktop_typed_text import (
    MAX_TYPED_CHARS as _MAX_TYPED_TEXT_CHARS,
    deposit_typed_text,
    text_is_deliverable,
    type_marker_op,
)
from .history import (
    HistoryError,
    HistoryForbidden,
    MAX_HISTORY_MESSAGE_CHARS,
    is_multi_command_action,
    validate_conversation_id,
)
from .history_append_reason import last_append_reason
from .request_telemetry import emit_stage_event


from .oracle_mesh_contract import (
    ORACLE_MESH_READ_REQUEST_PATH,
    ORACLE_MESH_READ_POLL_PATH,
    ORACLE_MESH_READ_RESULT_PATH,
    ORACLE_MESH_READ_CANCEL_PATH,
    ORACLE_MESH_READ_BUSY_PATH,
    ORACLE_MESH_READ_CANCEL_POLL_PATH,
    ORACLE_MESH_READ_LANE_STATUS_PATH,
    ORACLE_MESH_READ_ORIGINAL_PATH,
    ORACLE_MESH_OWNERSHIP_MAP_ENV,
    ORACLE_MESH_LEGACY_MAP_LANE_ENV,
    RETIRED_OWNERSHIP_MAP,
    ORACLE_MESH_EXECUTION_MODE_ENV,
    EXECUTION_MODE_OFF,
    EXECUTION_MODE_MESH,
    EXECUTION_MODE_NATIVE,
    _EXECUTION_MODES,
    ORACLE_MESH_CHANNEL_SECRET_ENV,
    CONNECTOR_WATCH_READ_SECRET_ENV,
    ORACLE_MESH_CHANNEL_HEADER,
    _DISPATCH_TTL,
    _MAX_RESULT_BODY_BYTES,
    _MAX_BODY_BYTES,
    _MAX_DESKTOP_ENGINE_BODY_BYTES,
    _MAX_COMMAND_MESSAGE_CHARS,
    _MAX_COMMAND_MESSAGE_PARTS,
    _MAX_PATH_VALUE_CHARS,
    _SAFE_REF_CHARS,
    _PRESENCE_BODY_KEYS,
    _PRESENCE_ENTRY_KEYS,
    _PRESENCE_ENTRY_OPTIONAL_KEYS,
    _MAX_PRESENCE_BODY_BYTES,
    _MAX_FILE_TEXT_BYTES,
    _EXECUTOR,
    _COMMAND_ROOT_REF,
    _COMMAND_PATH_RELATIVE,
    _COMMAND_FILE_SENTINEL,
    _COMMAND_SHELL_LABEL,
    _COMMAND_ECHO_MARK,
    _COMMAND_ECHO_PREFIX,
    _REQUEST_KEYS,
    _RESULT_KEYS,
    _RESULT_BLOB_KEYS,
    _RESULT_OPTIONAL_KEYS,
    _DESKTOP_COMMAND_PREFIX,
    _DESKTOP_OPS,
    _DESKTOP_SHELL_LABEL,
    _DESKTOP_SCREENSHOT_MEDIA_TYPE,
    _DESKTOP_SCREENSHOT_MAGIC,
    _DESKTOP_ORIGINAL_MARKER_PREFIX,
    _EMPTY_RESULT_SHA256,
)

from .oracle_mesh_source import (
    legacy_map_lane_enabled,
    UnconfiguredOracleMeshReturnSource,
    OracleMeshReturnSource,
    _resolve_oracle_store_text,
    build_oracle_mesh_return_source,
    _mesh_source_unconfigured,
    _resolve_optional_secret,
    build_oracle_mesh_return_source_from_env,
    valid_claw_engine_desktop_secret,
    host_engine_lane_mount_marker,
)


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

    if not getattr(request.app.state, "oracle_mesh_legacy_map_lane", True):
        # Retired on purpose: this request names a file for the deployment map, which
        # is no longer an authority. Tell the owner where the working path is instead
        # of a 403 that says "not yours" about a file that is theirs.
        return None, _error(
            409, "oracle_mesh_map_lane_retired",
            "이 방식은 더 이상 쓰지 않아요 — 내 컴퓨터 연결에서 폴더를 고르세요.",
        )
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
        scope = await mode_connector_read(identity, "owner_scope", session_id=session.session_id)
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
            consent = await mode_connector_read(
                identity, "consent",
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


from .oracle_mesh_http import (
    _NO_STORE,
    _response,
    _error,
    _BODY_REFUSAL,
    _refused,
    _invalid_body,
    _read_json,
    _text_value,
    _ref,
    _read_body,
    _read_result_body,
    _channel_source,
    _channel_proof,
    _watch_read_proof,
)


from .oracle_mesh_dispatch import (
    oracle_mesh_read_request,
    _dispatch_workspace_id,
    dispatch_oracle_mesh_read_intent,
    _active_owner_link_node,
    _owner_command_target,
    dispatch_oracle_mesh_command_intent,
    dispatch_oracle_mesh_file_read_intent,
    dispatch_oracle_mesh_desktop_intent,
    _deployment_target_for,
)


from .oracle_mesh_desktop_ops import (
    _DESKTOP_KEY_NAMES,
    _DESKTOP_KEY_MODIFIER_CODES,
    _DESKTOP_RESERVED_KEY_COMBOS,
    _desktop_key_combo_is_valid,
    _parse_desktop_op_text,
    _DESKTOP_TYPE_MARKER,
    _desktop_text_ref,
)


from .oracle_mesh_presence import (
    _read_presence,
    _PairingRefusalLog,
    _refusal_reason,
    _pairing_refusal_log,
    _record_mesh_presence,
)


from .oracle_mesh_poll import (
    _oracle_mesh_poll_max_bytes,
    _oracle_mesh_poll_granted_root,
    _oracle_mesh_poll_share_roots,
    oracle_mesh_read_poll,
    oracle_mesh_read_cancel_check,
    oracle_mesh_read_cancel_poll,
    oracle_mesh_read_busy_check,
    oracle_mesh_read_lane_status,
)


from .oracle_mesh_result_projection import (
    _verified_desktop_note,
    _verified_desktop_blob,
    _DESKTOP_OP_LABELS,
    _desktop_op_description,
    _desktop_head,
    _desktop_capture_content,
    _desktop_act_content,
    _desktop_failed_content,
    _verified_result_text,
    _verified_read_result_text,
    _pc_share_unavailable_output,
    _command_header,
    _command_result_content,
    _command_output_withheld_content,
    _command_original_stored_content,
    _command_part_messages,
    _file_read_part_messages,
    _file_read_stored_content,
    _command_markers,
    _command_part_budget,
    _command_head,
    _command_output_parts,
    _oracle_mesh_read_result_verify,
    _oracle_mesh_read_result_outcome,
)


from .oracle_mesh_result_routes import (
    _store_oracle_mesh_read_original,
    oracle_mesh_read_result,
    _oracle_mesh_read_result_store,
    oracle_mesh_read_original,
)


from .oracle_mesh_engine_auth import (
    _verify_engine_proof,
    _ENGINE_PC_FILES_SCOPE_OPS,
    _engine_pc_scope_claim,
    _engine_pc_files_owner,
    _DIRECTORY_UNUSABLE,
    _pc_files_directory_target,
    _engine_pc_files_target,
)


from .oracle_mesh_pc_paths import (
    PC_FILES_MAX_PATH_CHARS,
    PC_FILES_LIST_PAGE_SIZE,
    PC_FILES_READ_MAX_BYTES,
    PC_FILES_ERROR_PREFIX,
    _PC_FILES_READ_TOOL_MARKER,
    _PC_FILES_READ_ROOT_REF,
    _PC_FILES_SAFE_REF,
    _pc_files_text,
    _pc_files_approved_root,
    _pc_files_relative_path,
    _pc_files_roots_of_map_row,
    _DRIVE_REFERENCE,
    _ROOT_WORDS,
    _drive_reference,
    _pc_files_pick_root,
    _pc_files_powershell_literal,
    _PC_FILES_OPS,
    _PC_FILES_READ_OPS,
    _pc_files_read_only,
    _PC_WRITE_OPS,
    _pc_files_claim_op,
    _pc_files_search_roots,
)




#: The op ceilings the signed Engine scope claim may name, per admitted or
#: requested scope name. The names mirror the Engine's own table one-to-one
#: (``PC_REQUEST_SCOPE_TOOLS`` in kagent's pc_query_adapter) — #8098: the
#: three #8048 single-step scopes were missing here, so a recursive name
#: search (``admitted=files_search``) was refused 422 before the PC saw it.
#: The op values derive exactly like the Engine derives them: an op pairs
#: with its tool id, so a scope of only the chunk reader carries no named op
#: (``files_chunk`` → ``[]``). The browser scope is absent on purpose — a
#: browser claim verifies in claw_pc_browser_routes, never on this lane.
from .oracle_mesh_pc_write import (
    PC_BACKUP_FOLDER, PC_WRITE_ACCOUNT_PREFIX, _pc_backup_dir, _pc_ps_literal,
    _pc_write_backup_fragments, _pc_write_input_statements,
    _pc_write_scope_guard, _pc_write_operation_body,
    _pc_write_record_statements, _pc_write_command,
)
from .oracle_mesh_pc_read import (
    _PC_LIST_DEPTH_ROW_CAP, _FILTER_PREFILTER_SAFE,
    _pc_files_filter_prefilter, _pc_files_windows_folder, _pc_files_command,
)

from .oracle_mesh_engine_output import (
    _engine_pc_public_output,
    _engine_pc_job_response,
    _engine_pc_output_call,
    PC_IMAGE_ENVELOPE_PREFIX,
    PC_IMAGE_LONG_EDGE_MAX,
    PC_IMAGE_BYTE_CAP,
    _pc_image_projection,
)


async def _engine_pc_files_call(request: Request, *, product: str) -> JSONResponse:
    """One signed Engine call for the PC file context/dispatch/status/result."""
    resp, bundle = await _engine_pc_files_call_verify(request, product=product)
    if resp is not None:
        return resp
    scope_claim = bundle["scope_claim"]
    payload = bundle["payload"]
    requested_mode = bundle["requested_mode"]
    mode = bundle["mode"]
    selected = bundle["selected"]
    uid = bundle["uid"]
    session = bundle["session"]
    history_store = bundle["history_store"]
    run_row = bundle["run_row"]
    new_mode = bundle["new_mode"]
    resolved = bundle["resolved"]
    target = bundle["target"]
    roots = bundle["roots"]
    device_id = bundle["device_id"]

    if mode in ("context", "dispatch") and scope_claim is not None:
        scope_pinner = getattr(history_store, "pin_pc_run_scope", None)
        if not callable(scope_pinner):
            return _error(503, "pc_scope_store_unavailable")
        try:
            await scope_pinner(user_id=uid, run_id=payload["run_id"], claim=scope_claim)
        except HistoryForbidden:
            return _error(403, "pc_scope_frozen")
        except Exception:
            return _error(503, "pc_scope_store_unavailable")

    if mode == "context":
        # (A): the model is shown the owner's own names for the approved
        # folders, never a real path. One folder keeps the single-folder shape
        # the tools already speak; several arrive as a label list, and a call
        # must then name which one it means.
        labels = [root["label"] for root in roots]
        return _response({
            "ok": True,
            "roots": [{"label": label} for label in labels],
            # Engine guard only. The model projection remains device/tools;
            # matching a saved absolute folder to a labeled relative tool path
            # must use these owner-verified roots, never guess a home directory.
            "delegation_roots": [{"label": root["label"], "path": root["path"]} for root in roots],
            "device": {
                "device_id": device_id,
                "status": "configured",
                "folder": {
                    "name": labels[0] if len(labels) == 1 else (target.get("label") or "PC"),
                    "relative_path": ".",
                },
                "online_verified": False,
            },
            "tools": [
                "claw.pc.list_files",
                "claw.pc.read_file",
                "claw.pc.search_files",
                "claw.pc.search_contents",
                "claw.pc.query_drives",
            ],
            "run_id": payload["run_id"],
        })

    if requested_mode in ("read_output", "search_output", "store_output"):
        return await _engine_pc_output_call(
            history_store, payload=payload, uid=uid, device_id=device_id,
        )

    # The Engine has reached a real PC step for this proof- and owner-verified
    # run, so the conversation's staged row moves pending -> running. Status
    # only: no result_summary is ever passed, so a step in flight cannot be
    # mistaken for the run's answer, and the guarded write leaves a completed
    # run untouched. A lost projection must not fail the step that is running.
    mark_running = getattr(history_store, "update_claw_run_status", None)
    if callable(mark_running):
        try:
            await mark_running(uid, payload["run_id"], "running")
        except Exception:
            pass

    resp, _bundle = await _engine_pc_files_call_dispatch(
        request, payload=payload, requested_mode=requested_mode, mode=mode,
        scope_claim=scope_claim, roots=roots, selected=selected,
        session=session, uid=uid, target=target,
    )
    if resp is not None:
        return resp

    dispatch_id = payload.get("dispatch_id")
    if not isinstance(dispatch_id, str) or not 0 < len(dispatch_id) <= 128:
        return _error(400, "claw_engine_files_invalid_body")
    reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
    if not callable(reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        dispatch = await reader(user_id=uid, dispatch_id=dispatch_id)
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    kind = dispatch.get("kind") if isinstance(dispatch, dict) else None
    if (
        not isinstance(dispatch, dict)
        or dispatch.get("run_id") != payload["run_id"]
        or kind not in ("command", "read")
    ):
        return _error(404, "oracle_mesh_run_unavailable")
    if scope_claim is not None and kind == "read" and "read" not in scope_claim["ops"]:
        return _error(403, "pc_scope_denied")
    if new_mode:
        # The public row carries no device binding; the owner-scoped private
        # read is where it lives.
        private_reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
        private = await private_reader(user_id=uid, dispatch_id=dispatch_id) if callable(private_reader) else None
        bound = private.get("device_id") if isinstance(private, dict) else dispatch.get("device_id")
        if bound != device_id:
            return _error(404, "oracle_mesh_run_unavailable")
    state = dispatch.get("state")
    if state not in {"pending", "received", "store_failed", "done", "failed"}:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if requested_mode == "job_status":
        return _response({"ok": True, "result": {
            "job_id": dispatch_id,
            "state": "running" if state == "pending" and dispatch.get("claimed") is True else state,
            "kind": kind, "termination": dispatch.get("termination"), "exit_code": dispatch.get("exit_code"),
            **({"operation": dispatch["job_operation"]} if isinstance(dispatch.get("job_operation"), dict) else {}),
        }})
    if mode == "command_status":
        return _response({
            "ok": True,
            "dispatch": {
                "dispatch_id": dispatch["dispatch_id"],
                "run_id": payload["run_id"],
                "kind": kind,
                "state": state,
                "result_sha256": dispatch.get("result_sha256"),
                "termination": dispatch.get("termination"),
                "exit_code": dispatch.get("exit_code"),
                # The continuation leg projects the finished listing against the
                # folder it was asked about; the Engine sent this path and is the
                # only reader of this response.
                "file_path": dispatch.get("file_path"),
            },
        })
    # A command result is ready only after a clean terminal row. A read keeps
    # its verified body on a failed row too (the executor's bounded
    # PADIEM_PC_FILE_ERROR marker), so the Engine can surface the same error
    # mapping instead of losing it to an empty outcome.
    if kind == "read":
        if state not in ("done", "failed"):
            return _error(409, "oracle_mesh_result_not_ready")
    elif state != "done" and not (requested_mode == "job_output" and state == "failed"):
        return _error(409, "oracle_mesh_result_not_ready")
    termination = dispatch.get("termination")
    exit_code = dispatch.get("exit_code")
    if termination not in (
        "exited", "no_exit_code", "output_too_large", "not_executed",
        "timed_out", "cancelled", "no_reply", "bad_reply",
    ):
        return _error(503, "oracle_mesh_original_unavailable")
    if exit_code is None:
        if termination not in (
            "timed_out", "no_reply", "no_exit_code", "not_executed",
            "output_too_large", "cancelled", "bad_reply",
        ):
            return _error(503, "oracle_mesh_original_unavailable")
    elif isinstance(exit_code, bool) or not isinstance(exit_code, int):
        return _error(503, "oracle_mesh_original_unavailable")
    try:
        conversation_id = validate_conversation_id(
            (run_row or {}).get("conversation_id"),
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
    content, digest = stored
    if (
        not isinstance(content, bytes)
        or hashlib.sha256(content).hexdigest() != digest
        or digest != dispatch.get("result_sha256")
    ):
        return _error(503, "oracle_mesh_original_unavailable")
    try:
        output = content.decode("utf-8")
    except UnicodeDecodeError:
        return _error(503, "oracle_mesh_original_unavailable")
    image_block = None
    if kind == "read" and output.startswith(PC_IMAGE_ENVELOPE_PREFIX):
        output, image_block = _pc_image_projection(output)
    output_ref = None
    if len(output) > 4096 or requested_mode == "job_output":
        public_output, output_error = await _engine_pc_public_output(
            history_store, payload=payload, uid=uid, dispatch=dispatch,
            output=output, device_id=device_id, force=True,
        )
        if output_error is not None:
            return output_error
        output_ref = public_output["output_ref"]
        if requested_mode == "job_output":
            page = await _engine_pc_output_call(
                history_store,
                payload={**payload, "mode": "read_output", "handle": output_ref["handle"]},
                uid=uid, device_id=device_id,
            )
            if page.status_code != 200:
                return page
            result = json.loads(page.body)["result"]
            # The projected image block rides beside the paged output: a
            # job_output re-read must answer with the same image the direct
            # result carried (#7447).
            return _response({"ok": True, "result": {
                **result, "job_id": dispatch_id, "state": state,
                "output_ref": output_ref, "termination": termination, "exit_code": exit_code,
                **({"operation": dispatch["job_operation"]} if isinstance(dispatch.get("job_operation"), dict) else {}),
                **({"_pc_image": image_block} if image_block else {}),
            }})
        output = public_output["output"]
    # #7447/#7473: only a projected image read answers with the note as
    # its body, so content length/digest must describe the note the Engine
    # validates against. The stored-output reference and the plain text
    # lane keep the stored original's values: the Engine pins
    # content_bytes to the reference size there (#7473 review).
    if image_block is not None and output_ref is None:
        content_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
        content_bytes = len(output.encode("utf-8"))
    else:
        content_sha256 = digest
        content_bytes = len(content)
    return _response({
        "ok": True,
        "dispatch": {
            "dispatch_id": dispatch["dispatch_id"],
            "run_id": payload["run_id"],
            "kind": kind,
            "state": state,
            "result_sha256": digest,
            # A continuation projects the finished listing against the folder it
            # was asked about; the Engine sent this path and is the only reader.
            "file_path": dispatch.get("file_path"),
            "content_sha256": content_sha256,
            "content_bytes": content_bytes,
            "output": output,
            **({"_pc_image": image_block} if image_block else {}),
            **({"output_ref": output_ref} if output_ref else {}),
            "termination": termination,
            "exit_code": exit_code,
        },
    })


async def _engine_pc_files_call_dispatch(
    request: Request, *, payload: dict, requested_mode: str, mode: str,
    scope_claim: dict | None, roots: list, selected: str | None,
    session: Any, uid: str, target: dict,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """디스패치 분기 구간.

    본문은 리팩터 전 `_engine_pc_files_call`의 연속 구간을 글자 그대로 옮긴다.
    검사 순서·실패 응답·await 순서·디스패치 생성 인자를 그대로 지킨다.
    """
    if mode == "dispatch":
        op = payload.get("op")
        if op not in _PC_FILES_OPS:
            return _error(422, "oracle_mesh_file_op_invalid"), {}
        search_mode = None
        claim_op = op
        if op == "search":
            search_mode = pc_search_mode(payload.get("search_mode"))
            claim_op = _pc_files_claim_op(op, search_mode)
            if claim_op is None:
                return _error(422, "oracle_mesh_file_search_invalid"), {}
        # The independently signed ceiling is enforced before either dispatch
        # constructor. The existing owner/path/size/idempotency checks follow.
        if scope_claim is not None and claim_op not in scope_claim["ops"]:
            return _error(403, "pc_scope_denied"), {}
        search_roots = None
        if op == "search":
            # No folder named means every approved root, in order: the owner's
            # grant is the whole set, so a search never has to guess one and is
            # never refused for not naming one.
            search_roots = _pc_files_search_roots(roots, payload.get("path"))
            if search_roots is None:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
            if pc_search_roots(search_roots) is None:
                return _error(503, "oracle_mesh_file_root_unavailable"), {}
            root = relative = None
        else:
            picked = _pc_files_pick_root(roots, payload.get("path"))
            if picked is None:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
            root, relative = picked
            if op == "read" and not relative:
                return _error(422, "oracle_mesh_file_path_invalid"), {}
        tool_call_ref = payload.get("tool_call_ref")
        if (
            not isinstance(tool_call_ref, str)
            or _PC_FILES_SAFE_REF.fullmatch(tool_call_ref) is None
        ):
            return _error(422, "oracle_mesh_file_call_invalid"), {}
        command_workspace = await _dispatch_workspace_id(request, uid, session)
        if not command_workspace:
            return _error(503, "oracle_mesh_workspace_unavailable"), {}
        job_operation = {"op": op, "path": payload["path"]} if requested_mode == "job_start" else None
        if op in _PC_WRITE_OPS:
            # One write step, one account. The path the PC will change is built
            # the way the listing builds its folder - the root the server picked
            # plus the relative path the caller named - so a request never
            # carries an absolute target of its own.
            resolved = root.rstrip("/") + ("/" + relative if relative else "")
            content_b64 = None
            append = False
            if op == "write":
                content = payload.get("content")
                if not isinstance(content, str):
                    return _error(422, "oracle_mesh_file_content_invalid"), {}
                if "append" in payload and type(payload["append"]) is not bool:
                    return _error(422, "oracle_mesh_file_mode_invalid"), {}
                append = payload.get("append") is True
                content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
                if job_operation is not None:
                    job_operation.update(expected_bytes=len(content.encode("utf-8")),
                                         expected_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest())
                    if append:
                        job_operation["mode"] = "append"
            old_text_b64 = new_text_b64 = None
            if op == "edit":
                # #7065: the two byte sequences are carried the same way the
                # write carries its bytes, so no console code page or quoting
                # rule can change what is searched for or what is written.
                old_text, new_text = payload.get("old_text"), payload.get("new_text")
                if not isinstance(old_text, str) or not isinstance(new_text, str):
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                if not old_text:
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                replace_all = payload.get("replace_all")
                if replace_all is not None and not isinstance(replace_all, bool):
                    return _error(422, "oracle_mesh_file_edit_invalid"), {}
                if job_operation is not None:
                    job_operation["edit"] = True
                old_text_b64 = base64.b64encode(old_text.encode("utf-8")).decode("ascii")
                new_text_b64 = base64.b64encode(new_text.encode("utf-8")).decode("ascii")
            destination_path = None
            if op == "move":
                picked_destination = _pc_files_pick_root(roots, payload.get("destination"))
                if picked_destination is None:
                    return _error(422, "oracle_mesh_file_path_invalid"), {}
                destination_root, destination_relative = picked_destination
                if destination_root != root or not destination_relative:
                    # A move stays inside the folder this link was granted, and
                    # never onto the granted root itself: replacing a whole
                    # folder is not what moving one file means.
                    return _error(422, "oracle_mesh_file_path_invalid"), {}
                destination_path = destination_root.rstrip("/") + "/" + destination_relative
                if job_operation is not None:
                    job_operation["destination"] = payload["destination"]
            command = _pc_write_command(
                op=op,
                root=root,
                target=resolved,
                backup_dir=_pc_backup_dir(
                    root, datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                ),
                relative=relative,
                destination=destination_path,
                content_b64=content_b64,
                old_text_b64=old_text_b64,
                new_text_b64=new_text_b64,
                append=append,
                replace_all=bool(payload.get("replace_all")),
            )
            response = await dispatch_oracle_mesh_command_intent(
                request, command=command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                background=requested_mode == "job_start",
                job_operation=job_operation,
            )
            return _engine_pc_job_response(response, requested_mode), {}
        if op == "read":
            # #5015: the read reuses the existing kind="read" MeshCentral
            # download lane. No shell command is built for it.
            response = await dispatch_oracle_mesh_file_read_intent(
                request,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                target=target,
                root=root,
                relative=relative,
                background=requested_mode == "job_start",
                job_operation=job_operation,
            )
            return _engine_pc_job_response(response, requested_mode), {}
        if op == "read_chunk":
            offset = pc_read_offset(payload.get("offset"))
            length = pc_read_length(payload.get("length"))
            if offset is None or length is None or not relative:
                return _error(422, "oracle_mesh_file_range_invalid"), {}
            command = pc_read_chunk_command(
                root=root, relative=relative, offset=offset, length=length,
            )
            return await dispatch_oracle_mesh_command_intent(
                request, command=share_command_prefix([root]) + command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                read_only=True,
                share_roots=share_roots_of([root]),
            ), {}
        if op == "search":
            query = pc_search_query(payload.get("query"))
            if query is None:
                return _error(422, "oracle_mesh_file_search_invalid"), {}
            command = pc_search_command(
                roots=search_roots, query=query, mode=search_mode,
                limit=PC_SEARCH_MAX_LIMIT,
            )
            return await dispatch_oracle_mesh_command_intent(
                request, command=share_command_prefix(search_roots) + command,
                wire={
                    "run_id": payload["run_id"],
                    "device_id": selected,
                    "confirmed": True,
                },
                trusted_owner=(session, uid, command_workspace),
                tool_call_ref=tool_call_ref,
                files_target=target,
                read_only=True,
                share_roots=share_roots_of(search_roots),
            ), {}
        depth = payload.get("depth")
        if "depth" in payload and (
            type(depth) is not int or isinstance(depth, bool) or not 1 <= depth <= 3
        ):
            return _error(422, "oracle_mesh_file_depth_invalid"), {}
        offset = payload.get("offset")
        if "offset" in payload and (
            type(offset) is not int or isinstance(offset, bool) or not 0 <= offset <= 10_000
        ):
            return _error(422, "oracle_mesh_file_offset_invalid"), {}
        if (depth or 1) > 1 and (offset or 0) != 0:
            return _error(422, "oracle_mesh_file_offset_invalid"), {}
        recursive = payload.get("recursive")
        if "recursive" in payload and type(recursive) is not bool:
            return _error(422, "oracle_mesh_file_recursive_invalid"), {}
        if recursive is True:
            # This leg carries no name fragment, and the recursive builder
            # refuses to walk without one. A recursive name search travels as
            # the search op instead, so the flag is refused here by name rather
            # than left to fail inside the builder.
            return _error(422, "oracle_mesh_file_recursive_unsupported"), {}
        command = _pc_files_command(
            op=op, root=root, relative=relative,
            depth=depth if depth is not None else 1,
            offset=offset if offset is not None else 0,
        )
        response = await dispatch_oracle_mesh_command_intent(
            request, command=share_command_prefix([root]) + command,
            wire={
                "run_id": payload["run_id"],
                "device_id": selected,
                "confirmed": True,
            },
            trusted_owner=(session, uid, command_workspace),
            tool_call_ref=tool_call_ref,
            files_target=target,
            # #7602: only a read is handed out again after a run-out lease.
            read_only=_pc_files_read_only(op),
            share_roots=share_roots_of([root]),
            background=requested_mode == "job_start",
                job_operation=job_operation,
        )
        return _engine_pc_job_response(response, requested_mode), {}
    return None, {}


async def _engine_pc_files_call_verify(
    request: Request, *, product: str,
) -> tuple[JSONResponse | None, dict[str, object]]:
    """서명·본문 파싱·모드 검증·소유자/대상 확인 구간.

    본문은 리팩터 전 `_engine_pc_files_call`의 연속 구간을 글자 그대로 옮긴다.
    검사 순서와 실패 응답, await 순서를 그대로 지킨다.
    """
    raw, proof_error = await _verify_engine_proof(request, max_body_bytes=None)
    if proof_error is not None or raw is None:
        return (proof_error if proof_error is not None else _error(
            401, "claw_engine_proof_required",
        )), {}
    scope_claim, scope_error = _engine_pc_scope_claim(request, raw, product=product)
    if scope_error is not None:
        return scope_error, {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not isinstance(payload, dict):
        return _error(400, "claw_engine_files_invalid_body"), {}
    requested_mode = mode = payload.get("mode")
    # Only the dispatch leg has optional fields today; every other leg is exact.
    optional = set()
    if mode == "context":
        expected = {"subject_id", "run_id", "device_id", "mode"}
    elif mode == "dispatch":
        expected = {
            "subject_id", "run_id", "device_id", "op", "path",
            "tool_call_ref", "mode",
        }
        # A write names its bytes and a move names where the file lands. Nothing
        # else may add a field, and the operation itself is validated below.
        # A search names its query and which side of the file it looks at.
        extra_fields = {"write": {"content"}, "move": {"destination"},
                        "search": {"query", "search_mode"},
                        "read_chunk": {"offset", "length"}}
        # #7603: a write may name the append spelling. It is its own boolean
        # because `mode` in this body already names the transport leg.
        optional_fields = {"write": {"append"}}
        named = payload.get("op")
        if isinstance(named, str) and named in extra_fields:
            expected = expected | extra_fields[named]
        if isinstance(named, str) and named in optional_fields:
            optional = optional_fields[named]
        else:
            optional = set()
        if named == "list":
            # The widened read-only listing carries its depth and recursive
            # flag only when the caller named them; both are re-validated
            # (type and range) below before any command is built.
            for key in ("depth", "recursive"):
                if key in payload:
                    expected = expected | {key}
    elif mode == "job_start":
        expected = {"subject_id", "run_id", "device_id", "mode", "operation", "tool_call_ref"}
    elif mode == "job_status":
        expected = {"subject_id", "run_id", "device_id", "mode", "job_id"}
    elif mode == "job_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "job_id", "offset", "length"}
    elif mode == "read_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "handle", "offset", "length"}
    elif mode == "search_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "handle", "query"}
    elif mode == "store_output":
        expected = {"subject_id", "run_id", "device_id", "mode", "output", "source", "tool_call_ref"}
    elif mode in ("command_status", "result"):
        expected = {"subject_id", "run_id", "dispatch_id", "mode"}
    else:
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not (expected <= set(payload) <= expected | optional):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if not all(
        isinstance(payload.get(name), str) and 0 < len(payload[name]) <= 512
        for name in ("subject_id", "run_id")
    ):
        return _error(400, "claw_engine_files_invalid_body"), {}
    if requested_mode == "job_start":
        operation = payload.get("operation")
        if not isinstance(operation, dict) or operation.get("op") not in _PC_FILES_OPS:
            return _error(422, "oracle_mesh_file_op_invalid"), {}
        op = operation["op"]
        operation_fields = ({"op", "path"}
                            | ({"content"} if op == "write" else
                               {"old_text", "new_text", "replace_all"} if op == "edit" else
                               {"destination"} if op == "move" else set()))
        operation_optional = {"mode"} if op == "write" else set()
        if not (operation_fields <= set(operation)
                <= operation_fields | operation_optional):
            return _error(400, "claw_engine_files_invalid_body"), {}
        # The operation's own `mode` is the write spelling (overwrite/append),
        # not this body's transport leg. It must never replace the leg name,
        # and an append must reach the dispatch below as the `append` boolean:
        # dropping it here would turn a requested append into an overwrite.
        operation = dict(operation)
        write_mode = operation.pop("mode", None)
        if write_mode not in (None, "overwrite", "append"):
            return _error(422, "oracle_mesh_file_mode_invalid"), {}
        payload = {**payload, **operation}
        if write_mode == "append":
            payload["append"] = True
        mode = "dispatch"
    elif requested_mode in ("job_status", "job_output"):
        payload["dispatch_id"] = payload["job_id"]
        mode = "command_status" if requested_mode == "job_status" else "result"
    new_mode = requested_mode in {"job_start", "job_status", "job_output", "read_output", "search_output", "store_output"}
    if new_mode and scope_claim is None:
        return _error(403, "pc_scope_required"), {}
    if new_mode and (not isinstance(payload.get("device_id"), str) or not payload["device_id"]):
        return _error(422, "oracle_mesh_device_invalid"), {}
    if requested_mode in ("job_output", "read_output") and (
        type(payload.get("offset")) is not int or payload["offset"] < 0
        or type(payload.get("length")) is not int or not 0 <= payload["length"] <= 65536
    ):
        return _error(422, "pc_output_range_invalid"), {}
    selected = payload.get("device_id")
    if selected is not None and (
        not isinstance(selected, str) or not 0 < len(selected) <= 128
    ):
        return _error(422, "oracle_mesh_device_invalid"), {}
    uid, session, owner_error = await _engine_pc_files_owner(
        request, product=product, subject_id=payload["subject_id"],
    )
    if owner_error is not None:
        return owner_error, {}
    history_store = getattr(request.app.state, "history_store", None)
    if history_store is None or not callable(
        getattr(history_store, "get_claw_run", None)
    ):
        return _error(503, "oracle_mesh_unconfigured"), {}
    try:
        run_row = await history_store.get_claw_run(uid, payload["run_id"])
        if run_row is None and product == "chat" and mode == "context" and scope_claim is not None:
            from .chat_pc_drive import promote_chat_pc_stream_run
            run_row = await promote_chat_pc_stream_run(
                request, uid=uid, run_id=payload["run_id"], device_id=selected,
                action="pc_files_query",
            )
    except Exception:
        return _error(503, "oracle_mesh_run_unavailable"), {}
    if (
        not isinstance(run_row, dict)
        or run_row.get("run_id") != payload["run_id"]
        or not isinstance(run_row.get("conversation_id"), str)
        or not run_row["conversation_id"]
    ):
        return _error(404, "oracle_mesh_run_unavailable"), {}

    scope_reader = getattr(history_store, "get_pc_run_scope", None)
    try:
        saved_scope = await scope_reader(user_id=uid, run_id=payload["run_id"]) if callable(scope_reader) else None
    except Exception:
        return _error(503, "pc_scope_store_unavailable"), {}
    if saved_scope is not None and scope_claim != saved_scope:
        return _error(403, "pc_scope_required" if scope_claim is None else "pc_scope_frozen"), {}

    # The status/result legs carry only the dispatch id; adding a device hint
    # is a malformed body by contract. The dispatch itself names the PC that
    # ran the step, so use that node for the target check. Re-resolving a
    # multi-link owner without it can only answer "ambiguous" and refuse a
    # step that already ran.
    if mode in ("command_status", "result") and selected is None:
        # The private owner-scoped reader is the dispatch authority that also
        # names its PC; the public read intentionally keeps the normal row's
        # shape. Neither leg accepts a device hint from the Engine.
        reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
        if not callable(reader):
            reader = getattr(history_store, "get_oracle_mesh_dispatch_for_owner", None)
        if callable(reader) and isinstance(payload.get("dispatch_id"), str):
            try:
                status_dispatch = await reader(
                    user_id=uid, dispatch_id=payload["dispatch_id"],
                )
            except Exception:
                status_dispatch = None
            if isinstance(status_dispatch, dict):
                hint = status_dispatch.get("node_ref") or status_dispatch.get("device_id")
                if isinstance(hint, str) and hint:
                    selected = hint

    resolved, target_error = await _engine_pc_files_target(
        request, session=session, selected_device_id=selected, user_id=uid,
    )
    if target_error is not None:
        return target_error, {}
    if resolved is None:
        # No PC for this account: tool discovery answers honestly instead of
        # failing the turn, and only a call that needs a device is refused.
        if mode == "context":
            return _response({
                "ok": True,
                "roots": [],
                "device": {"device_id": selected, "status": "not_connected",
                           "online_verified": False},
                "tools": [],
                "run_id": payload["run_id"],
            }), {}
        return _error(403, "oracle_mesh_device_unverified"), {}
    target = resolved["target"]
    roots = resolved["roots"]
    device_id = target.get("device_id") or target["node_ref"]
    return None, {
        "scope_claim": scope_claim,
        "payload": payload,
        "requested_mode": requested_mode,
        "mode": mode,
        "selected": selected,
        "uid": uid,
        "session": session,
        "history_store": history_store,
        "run_row": run_row,
        "new_mode": new_mode,
        "resolved": resolved,
        "target": target,
        "roots": roots,
        "device_id": device_id,
    }


async def oracle_mesh_engine_claw_files_call(request: Request) -> JSONResponse:
    return await _engine_pc_files_call(request, product="claw")


@chat_pc_dispatch_ttl
async def oracle_mesh_engine_chat_files_call(request: Request) -> JSONResponse:
    return await _engine_pc_files_call(request, product="chat")


async def oracle_mesh_engine_desktop_call(request: Request) -> JSONResponse:
    """Engine-only authenticated desktop dispatch; browser cookies never act as proof.

    A signed call carries only an owner session reference and existing run id.
    Control Plane must resolve the current session independently before the
    existing owner-scoped desktop dispatch may run.
    """
    # #6460 step 3: a loop step may carry a typed value up to the one-shot
    # store's bound, so this lane's proof envelope is sized for it; every
    # field is still parsed and bounded below.
    raw, proof_error = await _verify_engine_proof(request, max_body_bytes=_MAX_DESKTOP_ENGINE_BODY_BYTES)
    if proof_error is not None or raw is None:
        return proof_error if proof_error is not None else _error(401, "claw_engine_proof_required")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _error(400, "claw_engine_desktop_invalid_body")
    status_query = isinstance(payload, dict) and payload.get("mode") in ("status", "image", "result", "command_status")
    run_query = isinstance(payload, dict) and payload.get("mode") == "run_status"
    command_dispatch = isinstance(payload, dict) and payload.get("mode") == "dispatch"
    desktop_dispatch = not status_query and not run_query and not command_dispatch
    expected_keys = (
        {"subject_id", "run_id", "dispatch_id", "mode"} if status_query
        else {"subject_id", "run_id", "mode"} if run_query
        else {"subject_id", "run_id", "device_id", "command", "mode"} if command_dispatch
        else {"subject_id", "run_id", "device_id", "desktop_op"}
    )
    # A loop step adds its own dispatch scope, and an Engine-chosen typed value
    # travels beside the op so it never enters the row. Both are optional, so
    # the single-action body stays byte-for-byte what it was.
    optional_keys = (frozenset({"call_ref", "desktop_text"})
                     if desktop_dispatch else frozenset())
    if (not isinstance(payload, dict)
        or not (expected_keys <= set(payload) <= expected_keys | optional_keys)
        or not all(
            isinstance(payload[k], str) and 0 < len(payload[k]) <= 512
            for k in ("subject_id", "run_id")
        )
        or (status_query and (not isinstance(payload["dispatch_id"], str)
            or not 0 < len(payload["dispatch_id"]) <= 128))
        or (command_dispatch and (
            payload.get("device_id") is not None and not isinstance(payload.get("device_id"), str)
            or not isinstance(payload.get("command"), str)
            or payload.get("command") != "Get-PSDrive -PSProvider FileSystem | Select-Object Name,Root,Used,Free | ConvertTo-Json"
        ))
        or (desktop_dispatch and (
            not isinstance(payload["desktop_op"], str)
            or not 0 < len(payload["desktop_op"]) <= 512
            or (payload["device_id"] is not None and (
                not isinstance(payload["device_id"], str)
                or not 0 < len(payload["device_id"]) <= 128))
            or ("call_ref" in payload and (
                not isinstance(payload["call_ref"], str)
                or not 0 < len(payload["call_ref"]) <= 120
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in payload["call_ref"])))
            or ("desktop_text" in payload and (
                not isinstance(payload["desktop_text"], str)
                or not 0 < len(payload["desktop_text"]) <= _MAX_TYPED_TEXT_CHARS))))):
        return _error(400, "claw_engine_desktop_invalid_body")
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(identity, "resolve_product_user_for_subject", None)):
        return _error(503, "claw_engine_identity_unavailable")
    # #5015: reuse the existing shared login/session bridge. The owner signs in
    # to the Chat product; the canonical B54 session is resolved from that same
    # server-known product user, so the Claw lane never requires a second,
    # separately active B54 login surface. The product is pinned inside the
    # Control Plane bridge and no browser/session value is accepted here.
    from padiem_control_plane.b54_identity_bridge import (
        resolve_current_b54_canonical_session as resolve_b54_session,
    )
    try:
        uid = await identity.resolve_product_user_for_subject(
            product_id="b62",
            canonical_subject_id=payload["subject_id"],
        )
    except Exception as exc:
        # #5015: bounded stage identifiers only, never identity values.
        print(_identity_bridge_failure_log_line("product_user"), flush=True)
        return _error(401, "canonical_session_required")
    try:
        bridged = await resolve_b54_session(identity, uid)
    except Exception as exc:
        print(_identity_bridge_failure_log_line("b54_session"), flush=True)
        return _error(401, "canonical_session_required")
    if (bridged is None
        or bridged.auth_session.subject.subject_id != payload["subject_id"]
        or not bridged.auth_session.tenant_id):
        print("claw_engine_bridge_mismatch", flush=True)
        return _error(401, "canonical_session_required")
    session = bridged.auth_session
    if run_query:
        # #6460 step 3 — the loop asks one question between steps: did the
        # owner stop this run? Only the owner's own run row answers, and the
        # read writes nothing.
        history_store = getattr(request.app.state, "history_store", None)
        reader = getattr(history_store, "get_claw_run", None)
        if not callable(reader):
            return _error(503, "oracle_mesh_unconfigured")
        try:
            run = await reader(uid, payload["run_id"])
        except Exception:
            return _error(503, "oracle_mesh_run_unavailable")
        if not isinstance(run, dict) or run.get("run_id") != payload["run_id"]:
            return _error(404, "oracle_mesh_run_unavailable")
        return _response({
            "ok": True,
            "run": {
                "run_id": run["run_id"],
                "state": run.get("status"),
                "updated_at": run.get("updated_at"),
            },
        })
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
        expected_kind = "command" if payload.get("mode") in ("result", "command_status") else "desktop"
        if (not isinstance(dispatch, dict)
            or dispatch.get("run_id") != payload["run_id"]
            or dispatch.get("kind") != expected_kind):
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
        if payload["mode"] == "result":
            if state != "done" or dispatch.get("kind") != "command":
                return _error(409, "oracle_mesh_result_not_ready")
            termination = dispatch.get("termination")
            exit_code = dispatch.get("exit_code")
            if termination not in (
                "exited", "no_exit_code", "output_too_large", "not_executed",
                "timed_out", "cancelled", "no_reply", "bad_reply",
            ):
                return _error(503, "oracle_mesh_original_unavailable")
            if exit_code is None:
                if termination not in (
                    "timed_out", "no_reply", "no_exit_code", "not_executed",
                    "output_too_large", "cancelled", "bad_reply",
                ):
                    return _error(503, "oracle_mesh_original_unavailable")
            elif isinstance(exit_code, bool) or not isinstance(exit_code, int):
                return _error(503, "oracle_mesh_original_unavailable")
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
            if (not isinstance(raw, bytes)
                or hashlib.sha256(raw).hexdigest() != digest
                or digest != dispatch.get("result_sha256")):
                return _error(503, "oracle_mesh_original_unavailable")
            public_output, output_error = await _engine_pc_public_output(
                history_store, payload=payload, uid=uid, dispatch=dispatch,
                output=raw.decode("utf-8", errors="replace"),
            )
            if output_error is not None:
                return output_error
            return _response({
                "ok": True,
                "dispatch": {
                    "dispatch_id": dispatch["dispatch_id"],
                    "run_id": payload["run_id"],
                    "kind": "command",
                    "state": "done",
                    "result_sha256": digest,
                    **public_output,
                    **({"content_sha256": digest, "content_bytes": len(raw)}
                       if "output_ref" in public_output else {}),
                    "termination": termination,
                    "exit_code": exit_code,
                },
            })
        if state not in {"pending", "received", "store_failed", "done", "failed"}:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        return _response({
            "ok": True,
            "dispatch": {
                "dispatch_id": dispatch["dispatch_id"],
                "run_id": payload["run_id"],
                "kind": "command" if payload.get("mode") == "command_status" else "desktop",
                "state": state,
                "result_sha256": dispatch.get("result_sha256"),
                "termination": dispatch.get("termination"),
                "exit_code": dispatch.get("exit_code"),
            },
        })
    if command_dispatch:
        command_workspace = await _dispatch_workspace_id(request, uid, session)
        if not command_workspace:
            return _error(503, "oracle_mesh_workspace_unavailable")
        return await dispatch_oracle_mesh_command_intent(
            request, command=payload["command"],
            wire={"run_id": payload["run_id"], "device_id": payload["device_id"], "confirmed": True},
            trusted_owner=(session, uid, command_workspace),
        )
    desktop_op = payload["desktop_op"]
    # #7561: a loop step is held to the owner's own standard. Input runs only
    # inside a run the owner's sentence staged as a desktop task, and a typed
    # value passes the same exception and size checks as the owner's sentence.
    from .claw_desktop_intent import loop_step_refusal
    run_reader = getattr(getattr(request.app.state, "history_store", None), "get_claw_run", None)
    if not callable(run_reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        owner_run = await run_reader(uid, payload["run_id"])
    except Exception:
        return _error(503, "oracle_mesh_run_unavailable")
    refusal = loop_step_refusal(owner_run, desktop_op, payload.get("desktop_text"))
    if refusal is not None:
        return _error(403, refusal)
    if "desktop_text" in payload:
        # #6460 step 3 — the model-driven loop types a value it chose from the
        # screen. The value goes to the one-shot store and the row names it only
        # by length, digest prefix and reference; the value itself is never
        # written into any dispatch row of this run.
        if desktop_op != "desktop:type" or not text_is_deliverable(payload["desktop_text"]):
            return _error(422, "oracle_mesh_desktop_op_invalid")
        text_ref = await deposit_typed_text(
            getattr(request.app.state, "queue_client", None),
            payload["desktop_text"],
        )
        if text_ref is None:
            return _error(503, "desktop_text_unavailable")
        desktop_op = type_marker_op(payload["desktop_text"], text_ref)
    return await dispatch_oracle_mesh_desktop_intent(
        request, desktop_op=desktop_op,
        wire={"run_id": payload["run_id"], "device_id": payload["device_id"], "confirmed": True},
        trusted_owner=(session, uid, session.tenant_id),
        tool_call_ref=payload.get("call_ref"),
    )


@chat_pc_dispatch_ttl
async def oracle_chat_engine_pc_drive_call(request: Request) -> JSONResponse:
    """Engine-only Chat product PC drive lane; browser cookies never act as proof.

    #5015 review: the b62 Chat product reaches the SAME shared Mesh command
    contract (same pinned command, ownership grant, executor channel,
    verification, pin/store and status/result vocabulary) under its own
    product identity (``b62``), user, workspace and staged run. No Claw
    product, run or authority is borrowed: the Control Plane resolves the
    current b62 session independently, the Chat lane stages its own
    ``chat_pcq_`` run row, and only command modes exist here (no desktop).
    """
    from .chat_pc_drive import CHAT_PC_DRIVE_COMMAND

    raw, proof_error = await _verify_engine_proof(request)
    if proof_error is not None or raw is None:
        return proof_error if proof_error is not None else _error(401, "claw_engine_proof_required")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return _error(400, "claw_engine_desktop_invalid_body")
    status_query = isinstance(payload, dict) and payload.get("mode") in ("result", "command_status")
    command_dispatch = isinstance(payload, dict) and payload.get("mode") == "dispatch"
    expected_keys = (
        {"subject_id", "run_id", "dispatch_id", "mode"} if status_query
        else {"subject_id", "run_id", "device_id", "command", "mode"} if command_dispatch
        else set()
    )
    if (not isinstance(payload, dict)
        or not expected_keys
        or set(payload) != expected_keys
        or not all(
            isinstance(payload[k], str) and 0 < len(payload[k]) <= 512
            for k in ("subject_id", "run_id")
        )
        or (status_query and (not isinstance(payload["dispatch_id"], str)
            or not 0 < len(payload["dispatch_id"]) <= 128))
        or (command_dispatch and (
            payload.get("device_id") is not None and not isinstance(payload.get("device_id"), str)
            or not isinstance(payload.get("command"), str)
            or payload.get("command") != CHAT_PC_DRIVE_COMMAND
        ))):
        return _error(400, "claw_engine_desktop_invalid_body")
    # Reuse the file lane's product/connector identity boundary: verify the
    # B62 caller, then resolve the shared B54 connector session independently.
    # A B62 session identifies the Chat turn; it is not connector authority.
    uid, session, owner_error = await _engine_pc_files_owner(
        request, product="chat", subject_id=payload["subject_id"],
    )
    if owner_error is not None:
        return owner_error
    history_store = getattr(request.app.state, "history_store", None)
    if history_store is None:
        return _error(503, "oracle_mesh_unconfigured")
    if status_query:
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
            or dispatch.get("kind") != "command"):
            return _error(404, "oracle_mesh_run_unavailable")
        state = dispatch.get("state")
        if payload["mode"] == "result":
            if state != "done" or dispatch.get("kind") != "command":
                return _error(409, "oracle_mesh_result_not_ready")
            termination = dispatch.get("termination")
            exit_code = dispatch.get("exit_code")
            if termination not in (
                "exited", "no_exit_code", "output_too_large", "not_executed",
                "timed_out", "cancelled", "no_reply", "bad_reply",
            ):
                return _error(503, "oracle_mesh_original_unavailable")
            if exit_code is None:
                if termination not in (
                    "timed_out", "no_reply", "no_exit_code", "not_executed",
                    "output_too_large", "cancelled", "bad_reply",
                ):
                    return _error(503, "oracle_mesh_original_unavailable")
            elif isinstance(exit_code, bool) or not isinstance(exit_code, int):
                return _error(503, "oracle_mesh_original_unavailable")
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
            content, digest = stored
            if (not isinstance(content, bytes)
                or hashlib.sha256(content).hexdigest() != digest
                or digest != dispatch.get("result_sha256")):
                return _error(503, "oracle_mesh_original_unavailable")
            public_output, output_error = await _engine_pc_public_output(
                history_store, payload=payload, uid=uid, dispatch=dispatch,
                output=content.decode("utf-8", errors="replace"),
            )
            if output_error is not None:
                return output_error
            return _response({
                "ok": True,
                "dispatch": {
                    "dispatch_id": dispatch["dispatch_id"],
                    "run_id": payload["run_id"],
                    "kind": "command",
                    "state": "done",
                    "result_sha256": digest,
                    **public_output,
                    **({"content_sha256": digest, "content_bytes": len(content)}
                       if "output_ref" in public_output else {}),
                    "termination": termination,
                    "exit_code": exit_code,
                },
            })
        if state not in {"pending", "received", "store_failed", "done", "failed"}:
            return _error(503, "oracle_mesh_dispatch_unavailable")
        return _response({
            "ok": True,
            "dispatch": {
                "dispatch_id": dispatch["dispatch_id"],
                "run_id": payload["run_id"],
                "kind": "command",
                "state": state,
                "result_sha256": dispatch.get("result_sha256"),
                "termination": dispatch.get("termination"),
                "exit_code": dispatch.get("exit_code"),
            },
        })
    command_workspace = await _dispatch_workspace_id(request, uid, session)
    if not command_workspace:
        return _error(503, "oracle_mesh_workspace_unavailable")
    try:
        store = getattr(request.app.state, "history_store", None)
        if await store.get_claw_run(uid, payload["run_id"]) is None:
            from .chat_pc_drive import promote_chat_pc_stream_run
            await promote_chat_pc_stream_run(
                request, uid=uid, run_id=payload["run_id"],
                device_id=payload["device_id"], action="pc_drive_query",
            )
    except Exception:
        return _error(503, "oracle_mesh_run_unavailable")
    return await dispatch_oracle_mesh_command_intent(
        request, command=payload["command"],
        wire={"run_id": payload["run_id"], "device_id": payload["device_id"], "confirmed": True},
        trusted_owner=(session, uid, command_workspace),
    )
