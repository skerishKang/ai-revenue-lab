"""Owner-written sessions over the existing queue and confirmation records."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone

from starlette.responses import JSONResponse

from . import mcp_gateway_session as transport
from . import mcp_gateway_shell as shell
from .pc_command_confirmation import (
    direct_command_eligible, is_affirmative_reply, select_pending_command_row,
)

API_PATH = "/api/chat/pc/session"
_CARD_ACTIONS = ("pc_session_start", "pc_session_input")
_PREFIX = re.compile(r"^\s*PC\s+세션(?:\s|$)", re.I)
_START = re.compile(r"PC\s+세션\s+시작(?:\s+(powershell|cmd|bash))?\s+`([^`]*)`\s*", re.I)
_INPUT = re.compile(r"PC\s+세션\s+(dsp_[0-9a-f]{32})\s+입력\s+`([^`]*)`\s*", re.I)
_CONTROL = re.compile(r"PC\s+세션\s+(dsp_[0-9a-f]{32})\s+(읽기|상태|중지)\s*", re.I)
_CARD_MARKER = "\n<!--pc-session-confirm:"
_METHODS = {"start": "pc_shell_start", "input": "pc_shell_input",
            "read": "pc_shell_read", "status": "pc_shell_read", "stop": "pc_shell_stop"}
_API_FIELDS = {"op", "conversation_id", "job_id", "text", "enter", "key", "secret",
               "offset", "length", "wait_ms"}


def enabled(request):
    return bool(getattr(getattr(request.app.state, "settings", None), "chat_pc_session_enabled", False))


def _error(code, status=422):
    message = ("비밀 입력의 보관 시간이 끝났습니다. 가려진 입력 칸에 다시 입력해 주세요."
               if code == "pc_session_input_expired" else
               "PC 세션 요청을 확인하지 못했습니다. 같은 대화에서 다시 확인해 주세요.")
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def parse_owner_turn(text):
    """None means unrelated; a recognized but malformed prefix fails closed."""
    if not isinstance(text, str) or not _PREFIX.match(text):
        return None
    value = text.strip()
    match = _START.fullmatch(value)
    if match:
        return {"op": "start", "interactive": True, "mode": "user",
                "shell": (match[1] or "powershell").lower(), "command": match[2]}
    match = _INPUT.fullmatch(value)
    if match:
        return {"op": "input", "job_id": match[1].lower(), "text": match[2]}
    match = _CONTROL.fullmatch(value)
    if match:
        return {"op": {"읽기": "read", "상태": "status", "중지": "stop"}[match[2]],
                "job_id": match[1].lower()}
    return {}


def reserved_turn_error(request, *, user_text, owner_turn, has_attachments):
    """Reserved session syntax must not fall back into a model/tool turn."""
    if enabled(request) and parse_owner_turn(user_text) is not None:
        if not owner_turn:
            return _error("pc_session_owner_turn_required")
        if has_attachments:
            return _error("pc_session_bad_request")
    return None


def claw_response(response):
    """Keep Claw's existing delta/done SSE shape with the typed card result."""
    from starlette.responses import Response
    if response.status_code != 200:
        return response
    value = json.loads(response.body)
    terminal = {key: value[key] for key in ("conversation_id", "pc_session", "decision_status")}
    terminal["done"] = True
    frames = "event: delta\ndata: " + json.dumps({"delta": value["answer"]}, ensure_ascii=False)
    frames += "\n\nevent: done\ndata: " + json.dumps(terminal, ensure_ascii=False) + "\n\n"
    return Response(frames, media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-store"})


def _valid_operation(operation, *, api=False):
    if not isinstance(operation, dict):
        return False
    op = operation.get("op")
    if op not in _METHODS or api and op == "start":
        return False
    args = {k: v for k, v in operation.items() if k != "op"}
    if op == "start":
        return transport.validate_pc_session_start_arguments(args)
    if op == "input":
        return transport.validate_pc_session_input_arguments(args)
    allowed = {"job_id", "offset", "length"} | ({"wait_ms"} if op in {"read", "status"} else set())
    return (set(args) <= allowed and shell._valid_job_id(args.get("job_id"))
            and transport._range_valid(args))


async def _owner(request):
    # Shared transport passes trusted_owner: verify the original browser CSRF
    # and canonical owner first, exactly as the ordinary command lane does.
    from .claw_connector_enrollment_routes import _verified_owner_request
    from .auth_routes import current_user_id
    from .oracle_mesh_read_return_routes import _dispatch_workspace_id
    session, denial = await _verified_owner_request(request)
    if denial is not None or session is None:
        return None, denial if denial is not None else _error("canonical_session_required", 401)
    uid = current_user_id(request)
    workspace = await _dispatch_workspace_id(request, uid, session)
    if not isinstance(uid, str) or not uid or not isinstance(workspace, str) or not workspace:
        return None, _error("pc_session_unavailable", 503)
    return (uid, session, workspace), None


async def _conversation(history, uid, cid, *, required):
    from .history import PRODUCT_SCOPE_CHAT, validate_conversation_id
    try:
        cid = validate_conversation_id(cid)
        if cid is None:
            return None if not required else False
        owned = await history.get_conversation(uid, cid, product_scope=PRODUCT_SCOPE_CHAT)
        return cid if isinstance(owned, dict) else False
    except Exception:
        return False


async def _target(request, *, owner, operation, conversation_id, selected_device=None):
    """Follow-ups bind to the saved start row, not the browser's current PC."""
    from .pc_work_context import resolve_pc_work_context, read_saved_device_selection
    from .mcp_gateway_execution import _check_mesh_grant
    from padiem_ai_core.pc_device_identity import is_pc_device_id
    uid, session, workspace = owner
    history = request.app.state.history_store
    if operation["op"] == "start":
        device = selected_device
        if device is None:
            saved = await read_saved_device_selection(request, owner_id=uid, workspace_id=workspace)
            device = saved.device_id if saved.status == "selected" else None
    else:
        job = operation["job_id"]
        private = await shell._authorize_job(request, identity={"user_id": uid},
                                             job_id=job, require_receipt=False)
        public = await shell._dispatch_row(request, uid=uid, dispatch_id=job)
        if private is None or not isinstance(public, dict) or public.get("job_operation") != {"op": "session"}:
            return None
        run = await history.get_claw_run(uid, private.get("run_id"))
        if (not isinstance(run, dict) or run.get("action") != "pc_session"
                or run.get("conversation_id") != conversation_id
                or run.get("workspace_id") != workspace):
            return None
        device = private["device_id"]
        if selected_device is not None and selected_device != device:
            return None
    if not is_pc_device_id(device):
        return None
    context = await resolve_pc_work_context(request, owner_id=uid, workspace_id=workspace,
        session_id=session.session_id, selected_device_id=device, execution_device_id=device)
    if (context.selection_offline or not context.selected_confirmed or not context.tool_available
            or context.selected_device_id != device or context.execution_device_id != device
            or not await _check_mesh_grant(request, session, device_id=device,
                                           owner_ref=uid, denied_reason=[])):
        return None
    return device


def _snapshot(result, *, job_id=None):
    value = {k: v for k, v in result.items() if not k.startswith("_")
             and k not in {"answer", "conversation_id", "run_id", "sessions"}}
    if job_id is not None:
        value.setdefault("job_id", job_id)
    if isinstance(result.get("sessions"), list):
        rows = result["sessions"]
        if len(rows) == 1:
            value.update(rows[0])
        elif not rows:
            value.update(status="failed", code="pc_session_not_found", alive=False)
    return value


def _response(result, *, conversation_id, job_id=None):
    snapshot = _snapshot(result, job_id=job_id)
    job = snapshot.get("job_id")
    answer = (("PC 세션 " + job + " 상태를 확인했습니다.") if shell._valid_job_id(job)
              else "PC 세션 요청을 확인했습니다.")
    if snapshot.get("status") not in {"completed", "waiting_approval"}:
        answer = "PC 세션 요청을 완료하지 못했습니다. 출력을 읽어 상태를 확인해 주세요."
    return JSONResponse({"answer": answer, "conversation_id": conversation_id,
        "decision_status": "pc_session", "pc_session": snapshot,
        "orchestration": {"events": [], "approval_pause": None, "continuation_ref": None}})


def _needs_confirmation(operation, user_text):
    if operation["op"] not in {"start", "input"}:
        return False
    value = operation.get("command", operation.get("text", ""))
    return bool(value) and not direct_command_eligible(user_text, value)


async def _call(request, *, owner, operation, conversation_id, device, user_text):
    uid, session, workspace = owner
    args = {k: v for k, v in operation.items() if k != "op"}
    if operation["op"] == "status":
        args["status_only"] = True
    return await transport.execute_authorized_session(request, tool_name=_METHODS[operation["op"]],
        arguments=args, identity={"user_id": uid, "device_id": device}, session=session,
        workspace_id=workspace, conversation_id=conversation_id, history_text=user_text)


async def _secret_capability(request, *, owner, operation, conversation_id, device):
    result = await _call(request, owner=owner, operation={"op": "status", "job_id": operation["job_id"]},
        conversation_id=conversation_id, device=device, user_text="PC 세션 비밀 입력 지원 확인")
    if result.get("status") != "completed" or result.get("ok") is not True:
        return result
    if "secret_mask" not in result.get("features", []):
        return transport._failure("pc_session_unsupported")
    rows = result.get("sessions", [])
    if len(rows) != 1 or rows[0].get("session") != operation["job_id"][4:]:
        return transport._failure("pc_session_not_found")
    if rows[0].get("alive") is not True:
        return transport._failure("pc_session_expired" if rows[0].get("ended") == "expired" else "pc_session_ended")
    return None


async def _stage(request, *, owner, operation, conversation_id, device, user_text):
    from .mcp_gateway_execution import _new_lane_run_id
    from .history import MAX_HISTORY_TITLE_CHARS
    from .desktop_typed_text import deposit_typed_text
    uid, _, workspace = owner
    history = request.app.state.history_store
    payload = {"operation": dict(operation), "device": device}
    if operation.get("secret") is True:
        failure = await _secret_capability(request, owner=owner, operation=operation,
                                          conversation_id=conversation_id, device=device)
        if failure is not None:
            return _response(failure, conversation_id=conversation_id, job_id=operation["job_id"])
        text = payload["operation"].pop("text")
        ref = await deposit_typed_text(request.app.state.queue_client, text)
        if ref is None:
            return _error("pc_session_unavailable", 503)
        payload["secret_input"] = {"ref": ref, "chars": len(text), "bytes": len(text.encode())}
        user_text = "PC 세션 비밀 입력: " + str(len(text)) + "자"
        display = user_text
    else:
        display = operation.get("command", operation.get("text", "")).replace("\n", "\\n")
    run_id = _new_lane_run_id()
    # Existing message + run card bind the exact server-staged request, its
    # original PC and options. Secret metadata contains only a ref and lengths.
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode()
    staged = user_text + _CARD_MARKER + encoded + "-->"
    cid = await history.begin_chat_stream_turn(user_id=uid, run_id=run_id, workspace_id=workspace,
                                              user_text=staged, conversation_id=conversation_id)
    await history.record_claw_run(user_id=uid, run_id=run_id, channel="web",
        action="pc_session_" + operation["op"], title=("Chat: " + user_text.strip())[:MAX_HISTORY_TITLE_CHARS],
        status="waiting_approval", conversation_id=cid, workspace_id=workspace,
        result_summary="pc_session_confirm:" + hashlib.sha256(staged.strip().encode()).hexdigest())
    notice = " 비밀 입력은 3분 뒤 지워지므로 그 전에 확인해 주세요." if operation.get("secret") else ""
    return JSONResponse({"answer": "PC 세션 확인: `" + display + "`을 전달하려면 '네'라고 답해 주세요." + notice,
        "conversation_id": cid, "decision_status": "pc_session_confirm",
        "pc_session": {"job_id": operation.get("job_id"), "status": "waiting_approval",
                       "confirmation_required": True},
        "orchestration": {"events": [], "approval_pause": None, "continuation_ref": None}})


async def _pending(request, *, owner, conversation_id):
    """Read the exact server-staged turn; consume only after fresh authority."""
    from .history import PRODUCT_SCOPE_CHAT
    uid, _, workspace = owner
    history = request.app.state.history_store
    row = select_pending_command_row(
        await history.list_recent_claw_runs(uid, limit=30, workspace_id=workspace),
        conversation_id=conversation_id, now=datetime.now(timezone.utc), actions=_CARD_ACTIONS)
    if row is None:
        return None
    run = await history.get_claw_run(uid, row["run_id"])
    if not isinstance(run, dict) or run.get("workspace_id") != workspace:
        return None
    context = await history.get_conversation_model_context(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
    messages = context.get("messages", []) if isinstance(context, dict) else []
    staged = next((m.get("content") for m in reversed(messages) if isinstance(m, dict)
                   and m.get("role") == "user"), None)
    if (not isinstance(staged, str) or row.get("result_summary") !=
            "pc_session_confirm:" + hashlib.sha256(staged.strip().encode()).hexdigest()):
        return None
    try:
        prefix, encoded = staged.rsplit(_CARD_MARKER, 1)
        if not encoded.endswith("-->"):
            return None
        payload = json.loads(base64.b64decode(encoded[:-3], validate=True))
        operation = payload["operation"]
        secret = payload.get("secret_input")
        check = {**operation, "text": "present"} if secret is not None else operation
        if (set(payload) - {"operation", "device", "secret_input"} or not _valid_operation(check)
                or row["action"] != "pc_session_" + operation["op"]):
            return None
        if secret is not None and (operation.get("secret") is not True or "text" in operation
                or not isinstance(secret, dict) or set(secret) != {"ref", "chars", "bytes"}
                or not re.fullmatch(r"[0-9a-f]{32}", secret.get("ref", ""))
                or any(type(secret.get(k)) is not int or not 1 <= secret[k] <= bound
                       for k, bound in (("chars", 4000), ("bytes", 16000)))):
            return None
        return row, operation, payload["device"], prefix, secret
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


async def _execute(request, *, owner, operation, conversation_id, device, user_text):
    if operation.get("secret") is True:
        text = operation.get("text", "")
        user_text = "PC 세션 비밀 입력: " + str(len(text)) + "자, " + str(len(text.encode())) + "바이트"
    result = await _call(request, owner=owner, operation=operation, conversation_id=conversation_id,
                         device=device, user_text=user_text)
    cid = result.get("conversation_id", conversation_id)
    if operation["op"] == "start" and result.get("ok") is True and shell._valid_job_id(result.get("job_id")):
        job, run_id = result["job_id"], result.get("run_id")
        await request.app.state.history_store.append_step_result_message(user_id=owner[0], run_id=run_id,
            message_id=run_id + "_session", content="PC 세션 " + job
            + "를 열었습니다. 이 대화에서 'PC 세션 " + job + " 상태'로 이어갈 수 있습니다.")
    return _response(result, conversation_id=cid, job_id=operation.get("job_id"))


def _transport_enabled(request):
    settings = getattr(request.app.state, "settings", None)
    return (enabled(request) and transport.pc_session_enabled(request)
            and getattr(settings, "mcp_pc_shell_enabled", False)
            and getattr(settings, "mcp_pc_shell_user_mode_enabled", False))


async def handle_owner_turn(request, *, user_text, conversation_id=None, selected_device=None,
                            owner_turn=True, has_attachments=False):
    """Before model dispatch; None leaves unrelated owner text unchanged."""
    if not enabled(request):
        return None
    operation = parse_owner_turn(user_text)
    affirmative = is_affirmative_reply(user_text)
    if operation is None and not affirmative:
        return None
    if not owner_turn:
        return _error("pc_session_owner_turn_required") if operation is not None else None
    if operation == {} or operation is not None and (has_attachments or not _valid_operation(operation)):
        return _error("pc_session_bad_request")
    if not _transport_enabled(request):
        return _error("pc_session_disabled", 404) if operation is not None else None
    try:
        owner, denial = await _owner(request)
        if denial is not None:
            return denial if operation is not None else None
        history = request.app.state.history_store
        cid = await _conversation(history, owner[0], conversation_id,
                                  required=operation is None or operation["op"] != "start")
        if cid is False:
            return _error("pc_session_not_found", 404) if operation is not None else None
        if operation is None:
            pending = await _pending(request, owner=owner, conversation_id=cid)
            if pending is None:
                return None
            if has_attachments:
                return _error("pc_session_bad_request")
            row, operation, pinned_device, staged_text, secret = pending
            device = await _target(request, owner=owner, operation=operation,
                                   conversation_id=cid, selected_device=pinned_device)
            if device is None:
                return _error("pc_session_not_found", 404)
            if secret is not None:
                failure = await _secret_capability(request, owner=owner, operation=operation,
                                                  conversation_id=cid, device=device)
                if failure is not None:
                    return _response(failure, conversation_id=cid, job_id=operation["job_id"])
            if await history.consume_pc_command_confirmation(owner[0], row["run_id"], action=row["action"]) is not True:
                return _error("pc_session_confirmation_unavailable", 409)
            if secret is not None:
                value = await request.app.state.queue_client.call("take_desktop_text", ref=secret["ref"])
                if (not isinstance(value, str) or len(value) != secret["chars"]
                        or len(value.encode()) != secret["bytes"]):
                    return _error("pc_session_input_expired", 409)
                operation = {**operation, "text": value}
                if not _valid_operation(operation):
                    return _error("pc_session_bad_request")
            return await _execute(request, owner=owner, operation=operation, conversation_id=cid,
                                  device=device, user_text=staged_text)
        device = await _target(request, owner=owner, operation=operation, conversation_id=cid,
                               selected_device=selected_device if operation["op"] == "start" else None)
        if device is None:
            return _error("pc_session_not_found", 404)
        if _needs_confirmation(operation, user_text):
            return await _stage(request, owner=owner, operation=operation, conversation_id=cid,
                                device=device, user_text=user_text)
        return await _execute(request, owner=owner, operation=operation, conversation_id=cid,
                              device=device, user_text=user_text)
    except Exception:
        return _error("pc_session_unavailable", 503)


async def session_card_request(request):
    """Masked values arrive here, never in a chat/model turn."""
    from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
    if not _transport_enabled(request):
        return _error("pc_session_disabled", 404)
    try:
        owner, denial = await _owner(request)
        if denial is not None:
            return denial
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return _error("pc_session_bad_request", 415)
        data = json.loads(await read_bounded_request_body(request, max_bytes=32768))
        if not isinstance(data, dict) or set(data) - _API_FIELDS:
            return _error("pc_session_bad_request")
        operation = {k: v for k, v in data.items() if k != "conversation_id"}
        if not _valid_operation(operation, api=True):
            return _error("pc_session_bad_request")
        cid = await _conversation(request.app.state.history_store, owner[0],
                                  data.get("conversation_id"), required=True)
        if cid is False:
            return _error("pc_session_not_found", 404)
        device = await _target(request, owner=owner, operation=operation, conversation_id=cid)
        if device is None:
            return _error("pc_session_not_found", 404)
        user_text = "PC 세션 " + operation["job_id"] + " " + operation["op"]
        if operation["op"] == "input" and operation.get("secret") is not True:
            user_text += ": " + operation.get("text", operation.get("key", ""))
        if _needs_confirmation(operation, user_text):
            return await _stage(request, owner=owner, operation=operation, conversation_id=cid,
                                device=device, user_text=user_text)
        return await _execute(request, owner=owner, operation=operation, conversation_id=cid,
                              device=device, user_text=user_text)
    except (ValueError, TypeError, UnicodeError, RequestBodyTooLarge):
        return _error("pc_session_bad_request")
    except Exception:
        # Transport exceptions can contain the input or its encoded frame.
        return _error("pc_session_input_uncertain", 503)
