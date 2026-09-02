"""Same-origin browser routes for B62 orchestration presentation/approval intent."""

from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth_routes import auth_ready, current_user_id
from .history import HistoryForbidden, HistoryStore
from .model_policy import ModelPolicyError, resolve_model_policy
from .orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError
from .request_contract import BrowserRequestError, _validate_payload
from .usage_gate import UsageGate

MAX_ORCHESTRATION_BROWSER_BODY_BYTES = 256 * 1024
_CONTINUATION_RE = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


def _bridge(request: Request) -> B62EngineOrchestrationBridge | None:
    bridge = getattr(request.app.state, "orchestration_bridge", None)
    return bridge if isinstance(bridge, B62EngineOrchestrationBridge) and bridge.ready else None


def _user_id(request: Request) -> str | None:
    if not auth_ready(request):
        return None
    return current_user_id(request)


async def orchestration_status(request: Request) -> JSONResponse:
    uid = _user_id(request)
    return JSONResponse(
        {
            "orchestration_ready": _bridge(request) is not None and uid is not None,
            "authenticated": uid is not None,
        },
        headers={"Cache-Control": "no-store"},
    )


async def _json_body(request: Request) -> Any:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_ORCHESTRATION_BROWSER_BODY_BYTES:
                raise B62OrchestrationError("request_too_large", "요청이 너무 큽니다.", status_code=413)
        except ValueError:
            raise B62OrchestrationError("invalid_request", "요청 형식이 올바르지 않습니다.", status_code=422) from None
    body = await request.body()
    if len(body) > MAX_ORCHESTRATION_BROWSER_BODY_BYTES:
        raise B62OrchestrationError("request_too_large", "요청이 너무 큽니다.", status_code=413)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise B62OrchestrationError("invalid_request", "요청 형식이 올바르지 않습니다.", status_code=422) from None


def parse_approval_intent(raw: Any) -> tuple[str, str, str]:
    if not isinstance(raw, dict) or set(raw) != {
        "continuationRef",
        "pauseId",
        "outcome",
        "requiresTrustedDecision",
    }:
        raise B62OrchestrationError("invalid_approval_intent", "확인 요청 형식이 올바르지 않습니다.", status_code=422)
    continuation_ref = raw.get("continuationRef")
    pause_id = raw.get("pauseId")
    outcome = raw.get("outcome")
    if not isinstance(continuation_ref, str) or not _CONTINUATION_RE.fullmatch(continuation_ref):
        raise B62OrchestrationError("invalid_approval_intent", "확인 요청 형식이 올바르지 않습니다.", status_code=422)
    if not isinstance(pause_id, str) or not _SAFE_ID_RE.fullmatch(pause_id):
        raise B62OrchestrationError("invalid_approval_intent", "확인 요청 형식이 올바르지 않습니다.", status_code=422)
    if outcome not in {"approved", "denied"} or raw.get("requiresTrustedDecision") is not True:
        raise B62OrchestrationError("invalid_approval_intent", "확인 선택이 올바르지 않습니다.", status_code=422)
    return continuation_ref, pause_id, outcome


def parse_cancel_intent(raw: Any) -> str:
    if not isinstance(raw, dict) or set(raw) != {"continuationRef"}:
        raise B62OrchestrationError("invalid_cancel_intent", "취소 요청 형식이 올바르지 않습니다.", status_code=422)
    ref = raw.get("continuationRef")
    if not isinstance(ref, str) or not _CONTINUATION_RE.fullmatch(ref):
        raise B62OrchestrationError("invalid_cancel_intent", "취소 요청 형식이 올바르지 않습니다.", status_code=422)
    return ref


def _latest_user(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            return item["content"]
    raise B62OrchestrationError("invalid_request", "사용자 질문이 필요합니다.", status_code=422)


async def _save_terminal_history(
    request: Request,
    *,
    user_id: str,
    conversation_id: str | None,
    user_text: str,
    answer: str | None,
) -> str | None:
    if not answer:
        return conversation_id
    store: HistoryStore | None = request.app.state.history_store
    if store is None:
        return conversation_id
    try:
        return await store.append_exchange(user_id, conversation_id, user_text, answer)
    except HistoryForbidden:
        return None
    except Exception:
        return conversation_id


async def api_orchestration(request: Request) -> JSONResponse:
    bridge = _bridge(request)
    if bridge is None:
        return _error("orchestration_unavailable", "작업 진행 상태 기능을 현재 사용할 수 없습니다.", 503)
    uid = _user_id(request)
    if uid is None:
        return _error("unauthorized", "이 기능을 사용하려면 로그인이 필요합니다.", 401)
    try:
        raw = await _json_body(request)
        messages, skill, tool_request, attachments, conversation_id, project_id = _validate_payload(raw)
        if tool_request is not None or attachments or project_id is not None:
            return _error(
                "orchestration_not_applicable",
                "이 요청은 기존 채팅 경로에서 처리합니다.",
                409,
            )
        policy = resolve_model_policy(messages)
    except BrowserRequestError as exc:
        return _error("invalid_request", str(exc), 422)
    except ModelPolicyError as exc:
        return _error(exc.code, exc.message, 422)
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)

    store: HistoryStore | None = request.app.state.history_store
    if conversation_id is not None and store is not None:
        try:
            existing = await store.get_conversation(uid, conversation_id)
        except Exception:
            return _error("history_unavailable", "대화 기록을 현재 사용할 수 없습니다.", 503)
        if existing is None:
            return _error("conversation_not_found", "대화를 찾을 수 없습니다.", 404)

    if getattr(request.app.state, "usage_gate_enforced", False):
        usage_gate: UsageGate = request.app.state.usage_gate
        decision = await usage_gate.authorize(
            raw_ip=request.headers.get("cf-connecting-ip"),
            user_id=uid,
        )
        if not decision.allowed:
            headers = {"Retry-After": str(decision.retry_after_seconds)} if decision.retry_after_seconds is not None else None
            return JSONResponse(
                {"error": {"code": decision.code, "message": decision.user_message}},
                status_code=decision.status_code,
                headers=headers,
            )

    user_text = _latest_user(messages)
    try:
        result = await bridge.start(
            user_id=uid,
            messages=policy.messages,
            skill=skill,
            model_id=policy.model_id,
            user_text=user_text,
            conversation_id=conversation_id,
        )
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)

    saved_id = await _save_terminal_history(
        request,
        user_id=uid,
        conversation_id=result.conversation_id,
        user_text=result.user_text,
        answer=result.answer,
    )
    payload: dict[str, Any] = {
        "orchestration": dict(result.orchestration),
        "answer": result.answer,
        "decision_status": result.decision_status,
    }
    if saved_id is not None:
        payload["conversation_id"] = saved_id
    return JSONResponse(payload)


async def api_orchestration_resume(request: Request) -> JSONResponse:
    bridge = _bridge(request)
    if bridge is None:
        return _error("orchestration_unavailable", "작업 진행 상태 기능을 현재 사용할 수 없습니다.", 503)
    uid = _user_id(request)
    if uid is None:
        return _error("unauthorized", "이 기능을 사용하려면 로그인이 필요합니다.", 401)
    try:
        raw = await _json_body(request)
        continuation_ref, pause_id, outcome = parse_approval_intent(raw)
        result = await bridge.resume(
            user_id=uid,
            continuation_ref=continuation_ref,
            pause_id=pause_id,
            outcome=outcome,
        )
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)

    saved_id = await _save_terminal_history(
        request,
        user_id=uid,
        conversation_id=result.conversation_id,
        user_text=result.user_text,
        answer=result.answer,
    )
    payload: dict[str, Any] = {
        "orchestration": dict(result.orchestration),
        "answer": result.answer,
        "decision_status": result.decision_status,
    }
    if saved_id is not None:
        payload["conversation_id"] = saved_id
    return JSONResponse(payload)


async def api_orchestration_cancel(request: Request) -> JSONResponse:
    bridge = _bridge(request)
    if bridge is None:
        return _error("orchestration_unavailable", "작업 진행 상태 기능을 현재 사용할 수 없습니다.", 503)
    uid = _user_id(request)
    if uid is None:
        return _error("unauthorized", "이 기능을 사용하려면 로그인이 필요합니다.", 401)
    try:
        raw = await _json_body(request)
        continuation_ref = parse_cancel_intent(raw)
        result = await bridge.cancel(user_id=uid, continuation_ref=continuation_ref)
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)
    return JSONResponse(
        {
            "orchestration": dict(result.orchestration),
            "answer": None,
            "decision_status": "cancelled",
        }
    )


def install_orchestration_routes(app: Any, bridge: B62EngineOrchestrationBridge | None) -> None:
    """Install routes ahead of the catch-all static Mount without changing app_factory."""
    app.state.orchestration_bridge = bridge
    routes = [
        Route("/api/orchestration/status", orchestration_status, methods=["GET"]),
        Route("/api/orchestration", api_orchestration, methods=["POST"]),
        Route("/api/orchestration/resume", api_orchestration_resume, methods=["POST"]),
        Route("/api/orchestration/cancel", api_orchestration_cancel, methods=["POST"]),
    ]
    for route in reversed(routes):
        app.router.routes.insert(0, route)
