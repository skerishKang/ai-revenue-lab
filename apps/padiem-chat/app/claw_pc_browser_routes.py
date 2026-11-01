"""Signed browser-only Mesh lane; existing identity, dispatch and result stores."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re

from starlette.requests import Request
from starlette.responses import Response
from padiem_ai_core.pc_device_identity import is_pc_device_id

from . import oracle_mesh_read_return_routes as mesh
from .claw_pc_browser_command import (
    PC_BROWSER_OPS, PcBrowserCommandError, browser_scope_claim, pc_browser_command,
)

BROWSER_CAPTURE_PATH = "/api/claw/connector/browser-captures/{dispatch_id}"
_CALL_REF = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_CAPTURE_DISPATCH = re.compile(r"^dsp_[0-9a-f]{32}$")
_PREFIX = "pc_browser:"


def _claim(request, raw, *, product):
    encoded = request.headers.get("X-Claw-PC-Scope")
    proof = request.headers.get("X-Claw-PC-Scope-Proof")
    if encoded is None and proof is None:
        return None, mesh._error(403, "pc_scope_required")
    if (not isinstance(encoded, str) or len(encoded) > 1024
            or not isinstance(proof, str) or re.fullmatch(r"[0-9a-f]{64}", proof) is None):
        return None, mesh._error(401, "pc_scope_proof_invalid")
    secret = request.app.state.claw_engine_desktop_secret
    stamp = request.headers.get("X-Claw-Engine-Time", "")
    expected = hmac.new(secret.encode(), stamp.encode() + b"." + raw + b"." + encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, proof):
        return None, mesh._error(401, "pc_scope_proof_invalid")
    try:
        claim = json.loads(encoded)
    except (ValueError, TypeError):
        return None, mesh._error(422, "pc_scope_claim_invalid")
    app_id = "padiem-chat" if product == "chat" else "b54-padiem-claw"
    if (not isinstance(claim, dict) or claim.get("app_id") != app_id
            or not browser_scope_claim({key: value for key, value in claim.items() if key != "app_id"})):
        return None, mesh._error(422, "pc_scope_claim_invalid")
    return claim, None


def _browser_op(dispatch):
    if not isinstance(dispatch, dict) or dispatch.get("kind") != "command":
        return None
    reference = dispatch.get("tool_request_ref")
    if not isinstance(reference, str) or not reference.startswith(_PREFIX):
        return None
    op, separator, reference = reference[len(_PREFIX):].partition(":")
    return op if separator and op in PC_BROWSER_OPS and _CALL_REF.fullmatch(reference) else None


async def _original(store, uid, dispatch):
    run = await store.get_claw_run(uid, dispatch["run_id"])
    cid = mesh.validate_conversation_id((run or {}).get("conversation_id"))
    if not cid:
        raise ValueError("browser_original_unavailable")
    message_id = mesh.result_message_id(conversation_id=cid, command_id=dispatch["command_id"],
                                        revision_ref=dispatch["revision_ref"])
    stored = await store.read_oracle_mesh_original(user_id=uid, dispatch_id=dispatch["dispatch_id"],
                                                  conversation_id=cid, message_id=message_id)
    if stored is None:
        raise ValueError("browser_original_unavailable")
    raw, digest = stored
    if (not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != digest
            or digest != dispatch.get("result_sha256")):
        raise ValueError("browser_original_unavailable")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("browser_original_unavailable")
    return value


def _capture(value):
    result = value.get("result")
    capture = result.get("capture") if isinstance(result, dict) else None
    if (not (value.get("ok") is True or value.get("ok") == "true") or not isinstance(result, dict)
            or result.get("state") != "captured"
            or not isinstance(capture, dict) or capture.get("mime_type") != "image/png"
            or not isinstance(capture.get("data"), str)
            or type(capture.get("bytes")) is not int):
        raise ValueError("browser_capture_unavailable")
    raw = base64.b64decode(capture["data"], validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) != capture["bytes"] or digest != capture.get("sha256"):
        raise ValueError("browser_capture_unavailable")
    return raw, digest


async def _device(request, session, selected):
    source = mesh._channel_source(request)
    if source is None or source.execution_mode != mesh.EXECUTION_MODE_MESH:
        return None, mesh._error(503, "oracle_mesh_unconfigured")
    try:
        owner = await request.app.state.control_plane_identity_authority.resolve_connector_owner_scope(
            session_id=session.session_id)
        account = owner.get("account_ref")
        if not isinstance(account, str) or not account:
            raise ValueError("owner unavailable")
        target = source.command_target(account_ref=account, device_id=selected)
    except Exception:
        return None, mesh._error(503, "oracle_mesh_device_directory_unavailable")
    if not target:
        return None, mesh._error(403, "oracle_mesh_command_unverified")
    return target.get("device_id") or target["node_ref"], None


async def _browser_call(request: Request, *, product: str):
    raw, error = await mesh._verify_engine_proof(request, max_body_bytes=131072)
    if error is not None:
        return error
    claim, error = _claim(request, raw, product=product)
    if error is not None:
        return error
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return mesh._error(400, "pc_browser_body_invalid")
    if not isinstance(payload, dict):
        return mesh._error(400, "pc_browser_body_invalid")
    mode = payload.get("mode")
    common = {"subject_id", "run_id", "mode"}
    expected = {
        "context": common | {"device_id"},
        "dispatch": common | {"device_id", "op", "arguments", "page_url", "tool_call_ref"},
        "command_status": common | {"dispatch_id"}, "result": common | {"dispatch_id"},
        "read_output": common | {"device_id", "handle", "offset", "length"},
    }.get(mode) if isinstance(mode, str) else None
    if mode == "dispatch" and "confirmation" in payload:
        expected = expected | {"confirmation"}
    if (expected is None or set(payload) != expected
            or any(not isinstance(payload.get(key), str) or not 0 < len(payload[key]) <= 512
                   for key in ("subject_id", "run_id"))):
        return mesh._error(400, "pc_browser_body_invalid")
    selected = payload.get("device_id")
    if selected is not None and not is_pc_device_id(selected):
        return mesh._error(422, "oracle_mesh_device_invalid")
    if mode in ("command_status", "result") and (
            not isinstance(payload["dispatch_id"], str) or not 0 < len(payload["dispatch_id"]) <= 128):
        return mesh._error(400, "pc_browser_body_invalid")
    if mode == "read_output" and (type(payload["offset"]) is not int or payload["offset"] < 0
                                  or type(payload["length"]) is not int or not 0 <= payload["length"] <= 65536):
        return mesh._error(422, "pc_output_range_invalid")
    uid, session, error = await mesh._engine_pc_files_owner(request, product=product,
                                                         subject_id=payload["subject_id"])
    if error is not None:
        return error
    store = getattr(request.app.state, "history_store", None)
    try:
        run = await store.get_claw_run(uid, payload["run_id"])
        if run is None and product == "chat" and mode in ("context", "dispatch"):
            from .chat_pc_drive import promote_chat_pc_stream_run
            run = await promote_chat_pc_stream_run(request, uid=uid, run_id=payload["run_id"],
                                                  device_id=selected, action="pc_browser_query")
        if (not isinstance(run, dict) or run.get("run_id") != payload["run_id"]
                or not run.get("conversation_id")):
            return mesh._error(404, "oracle_mesh_run_unavailable")
        saved = await store.get_pc_run_scope(user_id=uid, run_id=payload["run_id"])
        if saved is not None and saved != claim:
            return mesh._error(403, "pc_scope_frozen")
        if mode in ("context", "dispatch"):
            await store.pin_pc_run_scope(user_id=uid, run_id=payload["run_id"], claim=claim)
        elif saved != claim:
            return mesh._error(403, "pc_scope_required")
    except mesh.HistoryForbidden:
        return mesh._error(403, "pc_scope_frozen")
    except Exception:
        return mesh._error(503, "oracle_mesh_run_unavailable")
    if mode in ("command_status", "result"):
        try:
            dispatch = await store.get_oracle_mesh_dispatch_for_owner(user_id=uid, dispatch_id=payload["dispatch_id"])
        except Exception:
            return mesh._error(503, "oracle_mesh_dispatch_unavailable")
        op = _browser_op(dispatch)
        if not op or dispatch.get("run_id") != payload["run_id"] or op not in claim["ops"]:
            return mesh._error(404, "oracle_mesh_run_unavailable")
        # The established signed command path owns terminal states, original
        # hashes and output storage. Browser checks only narrow its admission.
        existing = mesh.oracle_chat_engine_pc_drive_call if product == "chat" else mesh.oracle_mesh_engine_desktop_call
        if mode != "result":
            return await existing(request)
        # Browser children already bound page text with their 8 KiB handle
        # contract. A second text preview would split their JSON document.
        # Reuse the command terminal receipt and original pin, then return the
        # whole typed receipt (with private PNG bytes removed) to the Engine.
        if dispatch.get("state") != "done":
            return mesh._error(409, "oracle_mesh_result_not_ready")
        if dispatch.get("termination") != "exited" or type(dispatch.get("exit_code")) is not int:
            return await existing(request)
        try:
            original = await _original(store, uid, dispatch)
            result = original.get("result")
            capture = result.get("capture") if isinstance(result, dict) else None
            if capture is not None:
                if op != "browser_screenshot" or dispatch["exit_code"] != 0:
                    raise ValueError("unexpected capture")
                image, digest = _capture(original)
                result.pop("path", None)
                result["capture"] = {"mime_type": "image/png", "sha256": digest,
                    "bytes": len(image), "url": BROWSER_CAPTURE_PATH.replace("{dispatch_id}", dispatch["dispatch_id"])}
            return mesh._response({"ok": True, "dispatch": {
                "dispatch_id": dispatch["dispatch_id"], "run_id": payload["run_id"],
                "kind": "command", "state": "done", "result_sha256": dispatch["result_sha256"],
                "termination": dispatch["termination"], "exit_code": dispatch["exit_code"],
                "output": json.dumps(original, ensure_ascii=False, separators=(",", ":"))}})
        except Exception:
            return mesh._error(503, "browser_result_unavailable")
    device, error = await _device(request, session, selected)
    if error is not None:
        return error
    if mode == "context":
        return mesh._response({"ok": True, "run_id": payload["run_id"],
            "device": {"device_id": device, "status": "configured", "online_verified": False},
            "tools": ["claw.pc." + op for op in claim["ops"]]})
    if mode == "read_output":
        return await mesh._engine_pc_output_call(store, payload=payload, uid=uid, device_id=device)
    op = payload.get("op")
    if not isinstance(op, str) or op not in claim["ops"]:
        return mesh._error(403, "pc_scope_denied")
    reference = payload.get("tool_call_ref")
    if not isinstance(reference, str) or _CALL_REF.fullmatch(reference) is None:
        return mesh._error(422, "browser_call_invalid")
    try:
        command = pc_browser_command(op, page_url=payload["page_url"], arguments=payload["arguments"],
                                     confirmation=payload.get("confirmation"))
    except PcBrowserCommandError as exc:
        return mesh._error(422, exc.code)
    try:
        workspace = await mesh._resolve_memory_workspace(request, uid)
    except Exception:
        workspace = None
    if not workspace:
        return mesh._error(503, "oracle_mesh_workspace_unavailable")
    response = await mesh.dispatch_oracle_mesh_command_intent(request, command=command,
        wire={"run_id": payload["run_id"], "device_id": device, "confirmed": True},
        trusted_owner=(session, uid, workspace), tool_call_ref=_PREFIX + op + ":" + reference,
        files_target=None)
    if response.status_code == 200:
        try:
            await store.update_claw_run_status(uid, payload["run_id"], "running")
        except Exception:
            pass
    return response


async def oracle_mesh_engine_claw_browser_call(request):
    return await _browser_call(request, product="claw")


async def oracle_mesh_engine_chat_browser_call(request):
    return await _browser_call(request, product="chat")


async def read_browser_capture(history_store, *, user_id: str, dispatch_id: str,
                               device_id: str | None = None):
    """Read one authenticated owner's image; MCP additionally pins its device."""
    if not isinstance(dispatch_id, str) or not _CAPTURE_DISPATCH.fullmatch(dispatch_id):
        raise ValueError("browser_capture_unavailable")
    dispatch = await history_store.get_oracle_mesh_dispatch_for_owner(user_id=user_id, dispatch_id=dispatch_id)
    bound_device = None
    if device_id is not None:
        # The device binding is the owner-scoped private read's fact; the public
        # dispatch row deliberately carries none.
        reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
        private = await reader(user_id=user_id, dispatch_id=dispatch_id) if callable(reader) else None
        bound_device = (private.get("device_id") if isinstance(private, dict)
                        else dispatch.get("device_id"))
    if (_browser_op(dispatch) != "browser_screenshot" or dispatch.get("state") != "done"
            or dispatch.get("termination") != "exited" or type(dispatch.get("exit_code")) is not int
            or dispatch.get("exit_code") != 0
            or device_id is not None and bound_device != device_id):
        raise ValueError("browser_capture_unavailable")
    value = await _original(history_store, user_id, dispatch)
    return _capture(value)


async def browser_capture(request: Request):
    uid = mesh.current_user_id(request)
    if not isinstance(uid, str) or not uid:
        return mesh._error(401, "canonical_session_required")
    try:
        raw, digest = await read_browser_capture(request.app.state.history_store, user_id=uid,
                                                 dispatch_id=request.path_params.get("dispatch_id"))
    except Exception:
        return mesh._error(404, "browser_capture_unavailable")
    return Response(raw, media_type="image/png", headers={**mesh._NO_STORE,
        "X-Content-Type-Options": "nosniff", "X-Padiem-Browser-Capture-Sha256": digest})
