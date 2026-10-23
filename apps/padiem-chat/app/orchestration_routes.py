"""Same-origin browser routes for B62 orchestration presentation/approval intent."""

from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth_routes import auth_ready, current_user_id
from .b14_client import PADIEM_IDENTITY_INSTRUCTION, _chat_product_identity_instruction
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .central_model_route_runtime import chat_request_tier_context
from .grounding import GroundingError
from .history import HistoryForbidden, HistoryStore
from .history import PRODUCT_SCOPE_CHAT
from .member_grade_access import selected_admin_denial, selected_grade_denial
from .model_policy import (
    ModelPolicyError,
    resolve_model_policy,
    resolve_request_model_policy,
)
from .orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError
from .public_chat import public_chat_result
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
    try:
        body = await read_bounded_request_body(
            request,
            max_bytes=MAX_ORCHESTRATION_BROWSER_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        raise B62OrchestrationError(
            "request_too_large",
            "요청이 너무 큽니다.",
            status_code=413,
        ) from None
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
        return await store.append_exchange(user_id, conversation_id, user_text, answer, product_scope=PRODUCT_SCOPE_CHAT)
    except HistoryForbidden:
        return None
    except Exception:
        return conversation_id


async def _run_pc_lane(
    request: Request,
    *,
    user_text: str,
    execution_user_text: str | None = None,
    skill: Any,
    model_id: str,
    tier: str,
    conversation_id: str | None,
    device_id: Any,
    run_id: Any = None,
) -> tuple[str | None, str | None]:
    """Run the existing PC drive/file lane for this turn, if it applies.

    The lane itself decides whether the turn is a PC request, resolves the
    server-verified target, and owns the plan, the grant checks and the answer
    persistence. A turn that is not a PC request returns ``(None, None)`` and
    the caller continues with the ordinary orchestration path.
    """
    from .chat_pc_drive import ChatPCDriveError, execute_chat_pc_drive_lane

    try:
        outcome = await execute_chat_pc_drive_lane(
            request,
            user_text=user_text,
            execution_user_text=execution_user_text,
            skill=skill,
            model_id=model_id,
            conversation_id=conversation_id,
            tier=tier,
            device_id=device_id if isinstance(device_id, str) else None,
            run_id=run_id if isinstance(run_id, str) else None,
        )
    except ChatPCDriveError as exc:
        raise _PcLaneRefusal(exc.code, exc.user_message, exc.status_code) from exc
    if outcome is None:
        return None, None
    answer, lane_conversation_id = outcome
    return answer, lane_conversation_id


class _PcLaneRefusal(Exception):
    """A bounded refusal from the existing PC lane."""

    def __init__(self, code: str, user_message: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.user_message = user_message
        self.status_code = status_code


def public_grounding_evidence(items: Any) -> list[dict[str, Any]]:
    """The browser-safe evidence projection for a grounded answer.

    The same allowlisted projection the Chat stream route uses: a title, a
    public URL, a snippet, the retrieval time and the source type. The
    provider identity stays server-side.
    """
    raw = [
        {
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "snippet": item.snippet,
            "retrieved_at": item.retrieved_at,
            "provider": item.provider,
            "source_type": item.source_type,
        }
        for item in items
    ]
    projected = public_chat_result({"evidence": raw})
    evidence = projected.get("evidence", [])
    return evidence if isinstance(evidence, list) else []


async def api_orchestration(request: Request) -> JSONResponse:
    bridge = _bridge(request)
    if bridge is None:
        return _error("orchestration_unavailable", "작업 진행 상태 기능을 현재 사용할 수 없습니다.", 503)
    uid = _user_id(request)
    if uid is None:
        return _error("unauthorized", "이 기능을 사용하려면 로그인이 필요합니다.", 401)
    try:
        raw = await _json_body(request)
        messages, skill, tool_request, attachments, conversation_id, project_id, custom = _validate_payload(raw)
        if tool_request is not None or attachments or project_id is not None or custom is not None:
            return _error(
                "orchestration_not_applicable",
                "이 요청은 기존 채팅 경로에서 처리합니다.",
                409,
            )
        # #5015: an explicit browser tier is a preference, not authority.
        # Reuse the same server-side grade/administrator gates and resolver the
        # Chat stream route applies. A legacy request without a tier keeps the
        # existing alias/default resolution.
        if "tier" in raw:
            if raw.get("tier") == "admin":
                admin_denial = await selected_admin_denial(request, uid)
                if admin_denial is not None:
                    return admin_denial
            else:
                tier_denial = await selected_grade_denial(request, uid, raw["tier"])
                if tier_denial is not None:
                    return tier_denial
            async with chat_request_tier_context(request, raw["tier"]):
                policy = resolve_request_model_policy(messages)
                # #5347: the Chat stream route composes the product identity while
                # the server-verified tier context is bound. The Engine lane has no
                # B14 product default, so the same render is sampled here and
                # carried on the Engine wire.
                product_identity = _chat_product_identity_instruction()
        else:
            policy = resolve_model_policy(messages)
            product_identity = PADIEM_IDENTITY_INSTRUCTION
    except BrowserRequestError as exc:
        return _error("invalid_request", str(exc), 422)
    except ModelPolicyError as exc:
        return _error(exc.code, exc.message, 422)
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)

    store: HistoryStore | None = request.app.state.history_store
    if conversation_id is not None and store is not None:
        try:
            existing = await store.get_conversation(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
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
    # #5015: the resolved policy already removed a hidden tier alias from the
    # execution messages. The PC lane uses that text for its model/Engine
    # prompt, while the original user_text above remains the stored user turn.
    execution_user_text = _latest_user(policy.messages)
    # #5015: a browser turn may reach this surface instead of the Chat stream
    # route. The generic bridge call below carries NO PC plan and NO selected
    # target, so a PC request could never reach the existing PC file lane: the
    # Engine would run a plan without the PC query steps, and the selected PC
    # would never be part of the request. Reuse the existing PC module (the
    # same one the Chat stream route uses) so the PC plan, the server-verified
    # target and the existing Mesh grant checks stay exactly where they are.
    # No second executor, no second target store, no browser-chosen target.
    try:
        pc_lane_answer, pc_lane_conversation_id = await _run_pc_lane(
            request,
            user_text=user_text,
            execution_user_text=execution_user_text,
            skill=skill,
            model_id=policy.model_id,
            tier=raw.get("tier", "free") if isinstance(raw.get("tier"), str) else "free",
            conversation_id=conversation_id,
            device_id=raw.get("device_id"),
            run_id=raw.get("pc_run_id"),
        )
    except _PcLaneRefusal as exc:
        return _error(exc.code, exc.user_message, exc.status_code)
    if pc_lane_answer is not None:
        # The PC lane already persisted the verified exchange in its own
        # conversation, so the answer is not stored a second time here.
        payload: dict[str, Any] = {
            "orchestration": {"status": "completed", "source": "pc_file_lane"},
            "answer": pc_lane_answer,
            "decision_status": "completed",
        }
        if pc_lane_conversation_id is not None:
            payload["conversation_id"] = pc_lane_conversation_id
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    # #4469: in production the PADIEM Chat composer is answered by THIS lane
    # (the browser tries the orchestration route first), so the shared public
    # web search has to run here as well. The existing Core search decision,
    # the existing TinyFish/Daum provider and the existing evidence
    # projection are reused unchanged: only the lane that actually answers the
    # turn now runs the retrieval. A request that needs no current external
    # fact still performs no provider call.
    auto_grounding = getattr(request.app.state, "auto_grounding", None)
    prepare_grounding = getattr(auto_grounding, "prepare", None)
    grounding_context: str | None = None
    grounded_evidence: list[dict[str, Any]] = []
    if callable(prepare_grounding):
        try:
            _explicit = bool(raw.get("web_search")) if isinstance(raw, dict) else False
            try:
                auto_plan = await prepare_grounding(
                    messages,
                    skill=skill,
                    additional_system_context=None,
                    explicit_search=_explicit,
                )
            except TypeError:
                auto_plan = await prepare_grounding(
                    messages,
                    skill=skill,
                    additional_system_context=None,
                )
        except GroundingError as exc:
            return _error(exc.code, exc.user_message, exc.status_code)
        prepared = getattr(auto_plan, "prepared", None)
        if prepared is not None:
            grounding_context = prepared.context
            grounded_evidence = public_grounding_evidence(prepared.evidence)

    try:
        result = await bridge.start(
            user_id=uid,
            messages=policy.messages,
            skill=skill,
            model_id=policy.model_id,
            user_text=user_text,
            conversation_id=conversation_id,
            additional_system_context=grounding_context,
            product_identity=product_identity,
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
    if grounded_evidence:
        # The browser contract for a grounded answer: the same tool marker and
        # the same public evidence the Chat stream route already returns.
        payload["answer_status"] = "answered_with_evidence"
        payload["evidence"] = grounded_evidence
        payload["tool"] = {"id": "web_search", "title": "웹 검색"}
    if saved_id is not None:
        payload["conversation_id"] = saved_id
    return JSONResponse(payload)

def _resume_skill():
    try:
        from .task_modes import get_task_mode

        return get_task_mode("auto")
    except Exception:
        from types import SimpleNamespace

        return SimpleNamespace(id="auto")

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

    # #4469: resume must keep the same public evidence contract as the
    # original grounded turn, so the sources survive an approval continuation.
    grounded_evidence: list[dict[str, Any]] = []
    auto_grounding = getattr(request.app.state, "auto_grounding", None)
    prepare_grounding = getattr(auto_grounding, "prepare", None)
    if callable(prepare_grounding) and isinstance(result.user_text, str) and result.user_text.strip():
        try:
            try:
                auto_plan = await prepare_grounding(
                    [{"role": "user", "content": result.user_text}],
                    skill=_resume_skill(),
                    additional_system_context=None,
                    explicit_search=False,
                )
            except TypeError:
                auto_plan = await prepare_grounding(
                    [{"role": "user", "content": result.user_text}],
                    skill=_resume_skill(),
                    additional_system_context=None,
                )
        except GroundingError:
            auto_plan = None
        prepared = getattr(auto_plan, "prepared", None) if auto_plan is not None else None
        if prepared is not None:
            grounded_evidence = public_grounding_evidence(prepared.evidence)

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
    if grounded_evidence:
        payload["answer_status"] = "answered_with_evidence"
        payload["evidence"] = grounded_evidence
        payload["tool"] = {"id": "web_search", "title": "웹 검색"}
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
