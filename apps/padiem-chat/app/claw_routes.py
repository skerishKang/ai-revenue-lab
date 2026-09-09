"""Claw Manual Intake Preview + Real Execution Routes (#2086 / #2215).

Provides:
- POST /api/claw/manual-intake/preview — deterministic preview (existing)
- POST /api/claw/manual-intake/execute — real P01/Engine-backed execution (#2215)

The preview route remains deterministic and never calls provider/P01.
The execute route consumes the existing B54 P01 composition chain:

    ManualIntakeRequest
    → create_claw_run
    → P01CoreOrchestrationAdapter
    → P01EngineOrchestrationClient
    → Engine
    → B14

Both routes are fail-closed: missing/malformed input, missing Engine
configuration, Engine timeout/unreachable, and malformed P01 responses
all return bounded safe errors. No credential/provider raw text leaks
into the browser. No silent preview fallback after explicit execute.
"""

from __future__ import annotations

import json
from typing import Any
import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .usage_gate import UsageGate
from kagent.manual_intake import (
    ContractError,
    ManualIntakeAction,
    ManualIntakeChannel,
    ManualIntakeRequest,
    ManualIntakeRouter,
)
from kagent.p01_adapter import P01AdapterError
from kagent.p01_run_flow import (
    create_claw_run,
    p01_adapter_from_environment,
)

MAX_MANUAL_INTAKE_BODY_BYTES = 64 * 1024  # 64 KiB
MAX_CONTENT_CHARS = 4_000
MAX_SENDER_CHARS = 120

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_ACTION_MAP: dict[str, ManualIntakeAction] = {
    "quote": ManualIntakeAction.QUOTE_DRAFT,
    "order": ManualIntakeAction.ORDER_DRAFT,
    "reply": ManualIntakeAction.REPLY_DRAFT,
    "summary": ManualIntakeAction.SUMMARIZE_REQUEST,
    "quote_draft": ManualIntakeAction.QUOTE_DRAFT,
    "order_draft": ManualIntakeAction.ORDER_DRAFT,
    "reply_draft": ManualIntakeAction.REPLY_DRAFT,
    "summarize_request": ManualIntakeAction.SUMMARIZE_REQUEST,
    "extract_candidates": ManualIntakeAction.EXTRACT_CANDIDATES,
}

_CHANNEL_MAP: dict[str, ManualIntakeChannel] = {
    "kakao": ManualIntakeChannel.KAKAO,
    "sms": ManualIntakeChannel.SMS,
    "email": ManualIntakeChannel.EMAIL,
    "telegram": ManualIntakeChannel.TELEGRAM,
    "discord": ManualIntakeChannel.DISCORD,
    "other": ManualIntakeChannel.OTHER,
}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _usage_denied_response(decision) -> JSONResponse:
    headers = dict(_NO_STORE_HEADERS)
    if decision.retry_after_seconds is not None:
        headers["Retry-After"] = str(decision.retry_after_seconds)
    return JSONResponse(
        {"ok": False, "error": {"code": decision.code, "message": decision.user_message}},
        status_code=decision.status_code,
        headers=headers,
    )


async def _usage_gate_denial(request: Request) -> JSONResponse | None:
    """Server-derived B62 usage gate for the real-execution path.

    Identity comes only from the signed-in session cookie and the trusted
    edge IP header; nothing in the request body can supply or override it.
    Returns a bounded product-safe response when denied, otherwise None.
    """
    if not getattr(request.app.state, "usage_gate_enforced", False):
        return None
    uid = current_user_id(request) if auth_ready(request) else None
    usage_gate: UsageGate = request.app.state.usage_gate
    decision = await usage_gate.authorize(
        raw_ip=request.headers.get("cf-connecting-ip"),
        user_id=uid,
    )
    return _usage_denied_response(decision) if not decision.allowed else None


async def claw_manual_intake_preview(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")

    raw_body = await request.body()
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_MANUAL_INTAKE_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return _error(400, "invalid_content", "요청 원문을 입력해 주세요.")
    content_clean = content.strip()
    if len(content_clean) > MAX_CONTENT_CHARS:
        return _error(400, "content_too_long", f"요청 원문은 {MAX_CONTENT_CHARS}자 이하로 입력해 주세요.")

    raw_channel = str(data.get("channel") or "other").strip().lower()
    channel = _CHANNEL_MAP.get(raw_channel)
    if channel is None:
        return _error(400, "invalid_channel", f"지원되지 않는 채널입니다: {raw_channel}")

    raw_action = str(data.get("action") or "quote").strip().lower()
    action = _ACTION_MAP.get(raw_action)
    if action is None:
        return _error(400, "invalid_action", f"지원되지 않는 작업입니다: {raw_action}")

    sender_hint: str | None = None
    if "sender_hint" in data and data["sender_hint"] is not None:
        raw_sender = str(data["sender_hint"]).strip()
        if len(raw_sender) > MAX_SENDER_CHARS:
            return _error(400, "sender_hint_too_long", f"발신자 힌트는 {MAX_SENDER_CHARS}자 이하로 입력해 주세요.")
        sender_hint = raw_sender or None

    req_id = f"prev_{uuid.uuid4().hex[:12]}"
    workspace_id = "preview_ephemeral_workspace"

    try:
        intake_req = ManualIntakeRequest(
            request_id=req_id,
            workspace_id=workspace_id,
            channel=channel,
            action=action,
            raw_content=content_clean,
            sender_hint=sender_hint,
            requested_format="md",
        )
        router = ManualIntakeRouter()
        intake_result = router.process(intake_req)
    except ContractError as exc:
        return _error(400, "contract_violation", str(exc))
    except Exception as exc:
        return _error(500, "preview_generation_failed", "미리보기 생성에 실패했습니다.")

    safe_projection = intake_result.safe_dict()

    return JSONResponse(
        {
            "ok": True,
            "preview": {
                "request_id": safe_projection["request_id"],
                "channel": safe_projection["channel"],
                "action": safe_projection["action"],
                "title": safe_projection["title"],
                "result_text": safe_projection["result_text"],
                "disabled_actions": safe_projection["disabled_actions"],
                "memory_proposals": safe_projection["memory_proposals"],
                "direct_kakao_send": False,
                "direct_sms_send": False,
                "connector_required": False,
            },
        },
status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_manual_intake_execute(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 허용됩니다.")

    raw_body = await request.body()
    if not raw_body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(raw_body) > MAX_MANUAL_INTAKE_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")

    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")

    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return _error(400, "invalid_content", "요청 원문을 입력해 주세요.")
    content_clean = content.strip()
    if len(content_clean) > MAX_CONTENT_CHARS:
        return _error(400, "content_too_long", f"요청 원문은 {MAX_CONTENT_CHARS}자 이하로 입력해 주세요.")

    raw_channel = str(data.get("channel") or "other").strip().lower()
    channel = _CHANNEL_MAP.get(raw_channel)
    if channel is None:
        return _error(400, "invalid_channel", f"지원되지 않는 채널입니다: {raw_channel}")

    raw_action = str(data.get("action") or "quote").strip().lower()
    action = _ACTION_MAP.get(raw_action)
    if action is None:
        return _error(400, "invalid_action", f"지원되지 않는 작업입니다: {raw_action}")

    sender_hint: str | None = None
    if "sender_hint" in data and data["sender_hint"] is not None:
        raw_sender = str(data["sender_hint"]).strip()
        if len(raw_sender) > MAX_SENDER_CHARS:
            return _error(400, "sender_hint_too_long", f"발신자 힌트는 {MAX_SENDER_CHARS}자 이하로 입력해 주세요.")
        sender_hint = raw_sender or None

    try:
        intake_req = ManualIntakeRequest(
            request_id=f"exec_{uuid.uuid4().hex[:12]}",
            workspace_id="execute_ephemeral_workspace",
            channel=channel,
            action=action,
            raw_content=content_clean,
            sender_hint=sender_hint,
            requested_format="md",
        )
        router = ManualIntakeRouter()
        router.process(intake_req)
    except ContractError as exc:
        return _error(400, "contract_violation", str(exc))
    except Exception as exc:
        return _error(400, "invalid_input", str(exc))

    denial = await _usage_gate_denial(request)
    if denial is not None:
        return denial

    try:
        adapter = p01_adapter_from_environment()
    except P01AdapterError as exc:
        return _error(503, "engine_not_configured", "Engine 클라이언트가 설정되지 않았습니다.")

    task_text = _build_execute_task(action, content_clean)
    run = create_claw_run("padiem-chat", task_text)

    try:
        outcome = await adapter.execute(run)
    except P01AdapterError as exc:
        return _error(502, "engine_execution_failed", "Engine 실행에 실패했습니다.")
    except Exception as exc:
        return _error(502, "engine_execution_failed", "Engine 실행에 실패했습니다.")

    if outcome.projection.status.value != "completed" or not outcome.answer:
        return _error(502, "engine_execution_failed", "Engine 실행이 완료되지 않았습니다.")

    return JSONResponse(
        {
            "ok": True,
            "result": {
                "request_id": run.run_id,
                "channel": channel.value,
                "action": action.value,
                "title": f"[{channel.value.upper()}] {action.value}: {sender_hint or '미지정'}",
                "result_text": outcome.answer,
                "status": outcome.projection.status.value,
                "p01_run_id": outcome.p01_run_id,
                "p01_event_count": outcome.p01_event_count,
                "direct_kakao_send": False,
                "direct_sms_send": False,
                "connector_required": False,
            },
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


def _build_execute_task(action: ManualIntakeAction, content: str) -> str:
    action_prompts: dict[ManualIntakeAction, str] = {
        ManualIntakeAction.QUOTE_DRAFT: f"다음 요청에 대한 견적서 초안을 작성하세요.\n\n{content}",
        ManualIntakeAction.ORDER_DRAFT: f"다음 요청에 대한 발주서 초안을 작성하세요.\n\n{content}",
        ManualIntakeAction.REPLY_DRAFT: f"다음 요청에 대한 답장을 작성하세요.\n\n{content}",
        ManualIntakeAction.SUMMARIZE_REQUEST: f"다음 요청을 요약하세요.\n\n{content}",
        ManualIntakeAction.EXTRACT_CANDIDATES: f"다음 요청에서 후보 정보를 추출하세요.\n\n{content}",
    }
    return action_prompts.get(action, content)
