"""#7088: Confirmation-gated connector tool continuation bridge (Chat <-> Engine).

Reuses the canonical ``OrchestrationStateStore`` (``orchestration_continuations`` +
``orchestration_decisions``) so paused Gmail draft actions share the exact same
owner-scoped durability, single-use state transitions, and browser confirmation
card (``orchestration_pause`` -> ``/api/orchestration/resume`` / ``cancel``)
without introducing a second continuation store or database table.

No mail body, subject, recipient, or credential ever enters the journal or
stored continuation request metadata; the Engine retains the SHA-256-pinned
``ToolInvocation`` on its own side and grants confirmation for that single
execution only after ``AuthenticatedFirstPartyApprovalDecisionVerifier`` passes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import re
from typing import Any
import uuid

from starlette.requests import Request

from .chat_connector_tools import (
    CONNECTOR_TOOL_BINDINGS,
    GMAIL_CREATE_DRAFT_TOOL_NAME,
    GMAIL_DELETE_DRAFT_TOOL_NAME,
    GMAIL_REFERENCE_APP_ID,
    is_confirmation_connector_tool_name,
)
from .connector_tool_engine_client import ConnectorToolEngineError
from .orchestration_bridge import (
    B62OrchestrationError,
    B62OrchestrationResult,
    D1OrchestrationStateStore,
    OrchestrationSnapshot,
    OrchestrationStateStore,
    project_cancel_result,
    project_public_orchestration,
)

from .request_telemetry import emit_stage_event

CONNECTOR_TOOL_PAUSE_LANE = "connector_tool"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONNECTOR_RESULT_CONTEXT_CHARS = 24_000


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise B62OrchestrationError(
            "invalid_orchestration_state",
            "저장된 확인 상태를 읽을 수 없습니다.",
            status_code=503,
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise B62OrchestrationError(
            "invalid_orchestration_state",
            "저장된 확인 상태를 읽을 수 없습니다.",
            status_code=503,
        )
    return parsed


def _event(
    *,
    run_id: str,
    trace_id: str,
    app_id: str,
    kind: str,
    sequence: int,
) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:20]}",
        "run_id": run_id,
        "trace_id": trace_id,
        "app_id": app_id,
        "kind": kind,
        "sequence": sequence,
    }


def _is_usable_pause_store(candidate: Any) -> bool:
    return all(
        callable(getattr(candidate, method, None))
        for method in ("save_pause", "load_active", "record_decision", "set_state")
    )


def resolve_connector_pause_store(request: Request) -> OrchestrationStateStore | None:
    """Resolve the existing owner-scoped OrchestrationStateStore without duplicating it."""

    explicit = getattr(request.app.state, "connector_tool_pause_store", None)
    if _is_usable_pause_store(explicit):
        return explicit
    bridge = getattr(request.app.state, "orchestration_bridge", None)
    bridge_store = getattr(bridge, "_store", None)
    if _is_usable_pause_store(bridge_store):
        return bridge_store
    cached = getattr(request.app.state, "_derived_connector_pause_store", None)
    if _is_usable_pause_store(cached):
        return cached
    db = getattr(request.app.state, "account_data_db", None)
    if db is not None and callable(getattr(db, "prepare", None)):
        derived = D1OrchestrationStateStore(db)
        request.app.state._derived_connector_pause_store = derived
        return derived
    return None


async def pause_connector_tool_turn(
    request: Request,
    *,
    uid: str | None,
    tool_name: str,
    tool: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
    skill: Any,
    reference_context: str | None,
    conversation_id: str | None,
    latest_user: str | None,
) -> dict[str, Any]:
    """Persist one paused connector-tool continuation and return public orchestration JSON."""

    if not isinstance(uid, str) or not uid:
        raise B62OrchestrationError(
            "unauthorized",
            "이 기능을 사용하려면 로그인이 필요합니다.",
            status_code=401,
        )
    if not is_confirmation_connector_tool_name(tool_name):
        raise B62OrchestrationError(
            "connector_tool_unsupported",
            "확인 대상 커넥터 도구가 아닙니다.",
            status_code=422,
        )
    store = resolve_connector_pause_store(request)
    if store is None:
        raise B62OrchestrationError(
            "orchestration_unavailable",
            "확인 대기 저장소를 사용할 수 없습니다.",
            status_code=503,
        )
    canonical_tool_id, app_id, _agent_id = CONNECTOR_TOOL_BINDINGS[tool_name]
    raw_run_id = tool.get("run_id")
    run_id = (
        raw_run_id
        if isinstance(raw_run_id, str) and _SAFE_ID_RE.fullmatch(raw_run_id)
        else f"ctrun_{uuid.uuid4().hex[:20]}"
    )
    trace_id = f"b62_ct_{uuid.uuid4().hex[:20]}"
    raw_orchestration = {
        "events": [
            _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="run_started", sequence=1),
            _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="tool_started", sequence=2),
            _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="approval_paused", sequence=3),
        ],
        "continuation_ref": tool.get("continuation_ref"),
        "approval_pause": tool.get("approval_pause"),
    }
    public = project_public_orchestration(raw_orchestration)
    pause = public["approval_pause"]
    continuation_ref = public["continuation_ref"]
    assert isinstance(pause, Mapping) and isinstance(continuation_ref, str)

    stored_messages = [
        {"role": str(item.get("role", "user")), "content": str(item.get("content", ""))}
        for item in messages
        if isinstance(item, Mapping) and isinstance(item.get("content"), str)
    ]
    await store.save_pause(
        user_id=uid,
        continuation_ref=continuation_ref,
        pause_id=str(pause["continuation_id"]),
        engine_request={
            "lane": CONNECTOR_TOOL_PAUSE_LANE,
            "tool_name": tool_name,
            "app_id": app_id,
            "canonical_tool_id": canonical_tool_id,
            "run_id": run_id,
            "trace_id": trace_id,
            "skill_id": getattr(skill, "id", None) if skill is not None else None,
            "messages": stored_messages,
            "reference_context": reference_context if isinstance(reference_context, str) else None,
        },
        user_text=latest_user if isinstance(latest_user, str) else "",
        conversation_id=conversation_id,
        expires_at=str(pause["expires_at"]),
    )
    return public


async def emit_paused_connector_tool_sse(
    request: Request,
    *,
    uid: str | None,
    tool_name: str,
    tool: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
    skill: Any,
    reference_context: str | None,
    conversation_id: str | None,
    latest_user: str | None,
    started_perf: float,
    timing: Any,
    public_sse: Any,
) -> bytes:
    """Persist paused connector tool and return the single SSE frame to yield."""

    import time as _time

    try:
        public_pause = await pause_connector_tool_turn(
            request,
            uid=uid,
            tool_name=tool_name,
            tool=tool,
            messages=messages,
            skill=skill,
            reference_context=reference_context,
            conversation_id=conversation_id,
            latest_user=latest_user,
        )
    except Exception:
        timing.set_outcome("error")
        emit_stage_event(
            stage="chat.connector_tools.execute",
            outcome="error",
            duration_ms=(_time.perf_counter() - started_perf) * 1000.0,
            code="connector_tool_pause_unavailable",
        )
        return public_sse(
            "error",
            {
                "error": {
                    "code": "connector_tool_unavailable",
                    "message": "사용자 확인 요청을 준비하지 못했습니다. 다시 시도해 주세요.",
                }
            },
        )
    emit_stage_event(
        stage="chat.connector_tools.execute",
        outcome="ok",
        duration_ms=(_time.perf_counter() - started_perf) * 1000.0,
        code=f"{tool_name}:paused",
    )
    print(f"connector_tools paused tool={tool_name}", flush=True)
    timing.set_outcome("ok")
    return public_sse("orchestration_pause", {"orchestration": public_pause})


async def load_active_connector_tool_pause(
    request: Request,
    *,
    user_id: str,
    continuation_ref: str,
    has_bridge: bool,
) -> tuple[OrchestrationStateStore, OrchestrationSnapshot] | None:
    """Return ``(store, snapshot)`` when ``continuation_ref`` is an active connector-tool pause."""

    store = resolve_connector_pause_store(request)
    if store is None:
        return None
    try:
        snapshot = await store.load_active(user_id=user_id, continuation_ref=continuation_ref)
    except B62OrchestrationError:
        if has_bridge:
            return None
        raise
    if snapshot.engine_request.get("lane") == CONNECTOR_TOOL_PAUSE_LANE:
        return store, snapshot
    return None


def _fallback_draft_answer(tool_name: str) -> str:
    if tool_name == GMAIL_CREATE_DRAFT_TOOL_NAME:
        return "Gmail 초안을 생성했습니다. 메일은 발송되지 않았습니다."
    if tool_name == GMAIL_DELETE_DRAFT_TOOL_NAME:
        return "Gmail 초안을 삭제했습니다."
    return "요청한 작업을 완료했습니다."


async def _compose_resumed_connector_answer(
    request: Request,
    *,
    tool_name: str,
    tool_output: Any,
    saved_request: Mapping[str, Any],
    fallback_user_text: str,
) -> str:
    b14_client = getattr(request.app.state, "b14_client", None)
    stream_fn = getattr(b14_client, "stream_text_auto", None)
    if not callable(stream_fn):
        return _fallback_draft_answer(tool_name)

    try:
        result_json = json.dumps(tool_output, ensure_ascii=False)
    except (TypeError, ValueError):
        result_json = json.dumps({"completed": True, "sent": False}, ensure_ascii=False)
    if len(result_json) > _CONNECTOR_RESULT_CONTEXT_CHARS:
        result_json = result_json[:_CONNECTOR_RESULT_CONTEXT_CHARS] + " …(잘림)"
    result_context = f"[connector:{tool_name} 결과]\n{result_json}"
    ref_ctx = saved_request.get("reference_context")
    additional = (f"{ref_ctx}\n\n" if isinstance(ref_ctx, str) and ref_ctx else "") + result_context

    raw_messages = saved_request.get("messages")
    messages = (
        [dict(m) for m in raw_messages if isinstance(m, Mapping)]
        if isinstance(raw_messages, list) and raw_messages
        else [{"role": "user", "content": fallback_user_text}]
    )
    skill_obj = None
    skill_id = saved_request.get("skill_id")
    if isinstance(skill_id, str) and skill_id:
        try:
            from .task_modes import get_task_mode

            skill_obj = get_task_mode(skill_id)
        except Exception:
            skill_obj = None

    parts: list[str] = []
    try:
        stream = stream_fn(messages, skill=skill_obj, additional_system_context=additional)
        async for event in stream:
            delta = getattr(event, "delta_content", None)
            if isinstance(delta, str) and delta:
                parts.append(delta)
            if getattr(event, "done", False):
                break
    except Exception:
        # Side-effect already committed on Gmail; surface a deterministic truth
        # instead of failing the turn and misleading the user into re-creating.
        return _fallback_draft_answer(tool_name)
    composed = "".join(parts).strip()
    return composed or _fallback_draft_answer(tool_name)


async def resume_connector_tool_pause(
    request: Request,
    *,
    store: OrchestrationStateStore,
    snapshot: OrchestrationSnapshot,
    pause_id: str,
    outcome: str,
) -> B62OrchestrationResult:
    """Verify owner intent and forward to Engine /internal/v1/tools/resume."""

    if snapshot.pause_id != pause_id:
        raise B62OrchestrationError(
            "continuation_identity_mismatch",
            "확인 요청이 현재 작업과 일치하지 않습니다.",
            status_code=409,
        )
    if _parse_aware(snapshot.expires_at) <= datetime.now(timezone.utc):
        await store.set_state(
            user_id=snapshot.user_id,
            continuation_ref=snapshot.continuation_ref,
            state="expired",
        )
        raise B62OrchestrationError(
            "continuation_expired",
            "확인 가능한 시간이 지나 작업을 이어갈 수 없습니다.",
            status_code=409,
        )
    if outcome not in {"approved", "denied"}:
        raise B62OrchestrationError(
            "invalid_approval_intent",
            "확인 선택이 올바르지 않습니다.",
            status_code=422,
        )

    tool_name = snapshot.engine_request.get("tool_name")
    app_id = snapshot.engine_request.get("app_id")
    if not is_confirmation_connector_tool_name(tool_name) or app_id != GMAIL_REFERENCE_APP_ID:
        raise B62OrchestrationError(
            "invalid_orchestration_state",
            "저장된 커넥터 확인 상태를 검증할 수 없습니다.",
            status_code=503,
        )
    engine_client = getattr(request.app.state, "connector_tool_engine_client", None)
    if engine_client is None:
        raise B62OrchestrationError(
            "connector_tool_unavailable",
            "커넥터 도구를 현재 사용할 수 없습니다.",
            status_code=503,
        )

    decision_id = f"decision_{uuid.uuid4().hex}"
    authority_ref = f"b62_session:{snapshot.user_id}"
    evidence_ref = f"b62_decision:{decision_id}"
    decided_at = _utc_iso_z()
    await store.record_decision(
        snapshot=snapshot,
        decision_id=decision_id,
        outcome=outcome,
        authority_ref=authority_ref,
        evidence_ref=evidence_ref,
        decided_at=decided_at,
    )
    decision = {
        "decision_id": decision_id,
        "pause_id": snapshot.pause_id,
        "outcome": outcome,
        "authority_ref": authority_ref,
        "evidence_ref": evidence_ref,
        "decided_at": decided_at,
    }
    try:
        resumed = await engine_client.resume(
            app_id=app_id,
            continuation_ref=snapshot.continuation_ref,
            decision=decision,
        )
    except ConnectorToolEngineError as exc:
        if exc.code in {"continuation_expired", "approval_decision_expired"}:
            next_state = "expired"
        elif exc.status_code == 409 and exc.code in {
            "approval_decision_mismatch",
            "invalid_approval_decision",
        }:
            next_state = "active"
        else:
            next_state = "active" if exc.status_code >= 500 else "expired"
        await store.set_state(
            user_id=snapshot.user_id,
            continuation_ref=snapshot.continuation_ref,
            state=next_state,
        )
        raise B62OrchestrationError(exc.code, exc.message, status_code=exc.status_code) from exc

    if resumed.get("status") == "denied":
        await store.set_state(
            user_id=snapshot.user_id,
            continuation_ref=snapshot.continuation_ref,
            state="denied",
        )
        print(f"connector_tools resume tool={tool_name} outcome=denied", flush=True)
        return B62OrchestrationResult(
            {"events": [], "approval_pause": None, "continuation_ref": None, "answer": None},
            None,
            snapshot.user_text,
            snapshot.conversation_id,
            decision_status="denied",
        )

    await store.set_state(
        user_id=snapshot.user_id,
        continuation_ref=snapshot.continuation_ref,
        state="completed",
    )
    print(f"connector_tools resume tool={tool_name} outcome=approved", flush=True)
    tool_body = resumed.get("tool") if isinstance(resumed.get("tool"), Mapping) else {}
    answer = await _compose_resumed_connector_answer(
        request,
        tool_name=str(tool_name),
        tool_output=tool_body.get("output"),
        saved_request=snapshot.engine_request,
        fallback_user_text=snapshot.user_text,
    )
    raw_run_id = snapshot.engine_request.get("run_id")
    run_id = (
        raw_run_id
        if isinstance(raw_run_id, str) and _SAFE_ID_RE.fullmatch(raw_run_id)
        else f"ctrun_{uuid.uuid4().hex[:20]}"
    )
    raw_trace_id = snapshot.engine_request.get("trace_id")
    trace_id = (
        raw_trace_id
        if isinstance(raw_trace_id, str) and _SAFE_ID_RE.fullmatch(raw_trace_id)
        else f"b62_ct_{uuid.uuid4().hex[:20]}"
    )
    public = project_public_orchestration(
        {
            "events": [
                _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="run_started", sequence=1),
                _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="run_resumed", sequence=2),
                _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="tool_completed", sequence=3),
                _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="run_completed", sequence=4),
            ],
            "execution": {"answer": answer},
            "approval_pause": None,
        }
    )
    return B62OrchestrationResult(
        public,
        answer,
        snapshot.user_text,
        snapshot.conversation_id,
        decision_status="approved",
    )


async def cancel_connector_tool_pause(
    request: Request,
    *,
    store: OrchestrationStateStore,
    snapshot: OrchestrationSnapshot,
) -> B62OrchestrationResult:
    """Cancel one paused connector-tool continuation via Engine /internal/v1/tools/cancel."""

    tool_name = snapshot.engine_request.get("tool_name")
    app_id = snapshot.engine_request.get("app_id")
    if not is_confirmation_connector_tool_name(tool_name) or app_id != GMAIL_REFERENCE_APP_ID:
        raise B62OrchestrationError(
            "invalid_orchestration_state",
            "저장된 커넥터 확인 상태를 검증할 수 없습니다.",
            status_code=503,
        )
    engine_client = getattr(request.app.state, "connector_tool_engine_client", None)
    if engine_client is None:
        raise B62OrchestrationError(
            "connector_tool_unavailable",
            "커넥터 도구를 현재 사용할 수 없습니다.",
            status_code=503,
        )
    try:
        await engine_client.cancel(
            app_id=app_id,
            continuation_ref=snapshot.continuation_ref,
            reason="user_cancelled",
        )
    except ConnectorToolEngineError as exc:
        raise B62OrchestrationError(exc.code, exc.message, status_code=exc.status_code) from exc

    await store.set_state(
        user_id=snapshot.user_id,
        continuation_ref=snapshot.continuation_ref,
        state="cancelled",
    )
    print(f"connector_tools cancel tool={tool_name} outcome=cancelled", flush=True)
    raw_run_id = snapshot.engine_request.get("run_id")
    run_id = (
        raw_run_id
        if isinstance(raw_run_id, str) and _SAFE_ID_RE.fullmatch(raw_run_id)
        else f"ctrun_{uuid.uuid4().hex[:20]}"
    )
    raw_trace_id = snapshot.engine_request.get("trace_id")
    trace_id = (
        raw_trace_id
        if isinstance(raw_trace_id, str) and _SAFE_ID_RE.fullmatch(raw_trace_id)
        else f"b62_ct_{uuid.uuid4().hex[:20]}"
    )
    public = project_cancel_result(
        {
            "status": "cancelled",
            "events": [
                _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="run_started", sequence=1),
                _event(run_id=run_id, trace_id=trace_id, app_id=app_id, kind="run_cancelled", sequence=2),
            ],
        }
    )
    return B62OrchestrationResult(
        public,
        None,
        snapshot.user_text,
        snapshot.conversation_id,
        decision_status="cancelled",
    )
