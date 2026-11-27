"""Engine desktop and Chat PC drive routes."""
from __future__ import annotations

import hashlib
import json

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .claw_local_task_result_projection import result_message_id
from .desktop_typed_text import (
    MAX_TYPED_CHARS as _MAX_TYPED_TEXT_CHARS,
    deposit_typed_text, text_is_deliverable, type_marker_op,
)
from .history import validate_conversation_id
from .oracle_mesh_contract import _MAX_DESKTOP_ENGINE_BODY_BYTES
from .oracle_mesh_dispatch import (
    _dispatch_workspace_id, dispatch_oracle_mesh_command_intent,
    dispatch_oracle_mesh_desktop_intent,
)
from .oracle_mesh_engine_auth import _verify_engine_proof, _engine_pc_files_owner
from .oracle_mesh_engine_output import _engine_pc_public_output
from .oracle_mesh_http import _NO_STORE, _error, _response
from .oracle_mesh_log import _identity_bridge_failure_log_line
from .pc_dispatch_ttl import chat_pc_dispatch_ttl


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
