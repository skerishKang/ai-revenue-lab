"""B62 server-side bridge to the Engine-owned orchestration client.

B62 owns product presentation and authenticated user intent only. The Engine
remains orchestration/continuation authority. Exact resume payloads are retained
server-side so browser input cannot alter the paused execution identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any, Protocol
import uuid

from padiem_ai_engine_client import PadiemAiEngineClient, PadiemAiEngineClientError
from padiem_ai_core.orchestration_events import OrchestrationEventKind

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_CONTINUATION_RE = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_ALLOWED_EVENT_KINDS = frozenset(item.value for item in OrchestrationEventKind)
_TERMINAL_EVENT_KINDS = frozenset({"run_completed", "run_failed", "run_cancelled"})


class B62OrchestrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class OrchestrationSnapshot:
    continuation_ref: str
    user_id: str
    pause_id: str
    engine_request: Mapping[str, Any]
    user_text: str
    conversation_id: str | None
    expires_at: str
    state: str


@dataclass(frozen=True, slots=True)
class B62OrchestrationResult:
    orchestration: Mapping[str, Any]
    answer: str | None
    user_text: str
    conversation_id: str | None
    decision_status: str | None = None


class OrchestrationStateStore(Protocol):
    async def save_pause(
        self,
        *,
        user_id: str,
        continuation_ref: str,
        pause_id: str,
        engine_request: Mapping[str, Any],
        user_text: str,
        conversation_id: str | None,
        expires_at: str,
    ) -> None: ...

    async def load_active(self, *, user_id: str, continuation_ref: str) -> OrchestrationSnapshot: ...

    async def record_decision(
        self,
        *,
        snapshot: OrchestrationSnapshot,
        decision_id: str,
        outcome: str,
        authority_ref: str,
        evidence_ref: str,
        decided_at: str,
    ) -> None: ...

    async def set_state(
        self,
        *,
        user_id: str,
        continuation_ref: str,
        state: str,
    ) -> None: ...


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse_aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise B62OrchestrationError(
            "invalid_orchestration_state",
            "저장된 작업 상태를 확인할 수 없습니다.",
            status_code=503,
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise B62OrchestrationError(
            "invalid_orchestration_state",
            "저장된 작업 상태를 확인할 수 없습니다.",
            status_code=503,
        )
    return parsed


class D1OrchestrationStateStore:
    """Product-local snapshot/audit store; never the Engine continuation authority."""

    def __init__(self, db: Any) -> None:
        if db is None:
            raise ValueError("D1 binding is required")
        self._db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self._db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self._db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def save_pause(
        self,
        *,
        user_id: str,
        continuation_ref: str,
        pause_id: str,
        engine_request: Mapping[str, Any],
        user_text: str,
        conversation_id: str | None,
        expires_at: str,
    ) -> None:
        now = _now_iso()
        request_json = json.dumps(
            dict(engine_request),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        await self._run(
            "INSERT INTO orchestration_continuations "
            "(continuation_ref, user_id, pause_id, request_json, user_text, conversation_id, expires_at, state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            continuation_ref,
            user_id,
            pause_id,
            request_json,
            user_text,
            conversation_id,
            expires_at,
            now,
            now,
        )

    async def load_active(self, *, user_id: str, continuation_ref: str) -> OrchestrationSnapshot:
        row = await self._first(
            "SELECT continuation_ref, user_id, pause_id, request_json, user_text, conversation_id, expires_at, state "
            "FROM orchestration_continuations WHERE continuation_ref=? AND user_id=?",
            continuation_ref,
            user_id,
        )
        if row is None or row.get("state") != "active":
            raise B62OrchestrationError(
                "continuation_not_available",
                "이 작업은 더 이상 이어갈 수 없습니다.",
                status_code=409,
            )
        try:
            engine_request = json.loads(str(row.get("request_json", "")))
        except json.JSONDecodeError:
            raise B62OrchestrationError(
                "invalid_orchestration_state",
                "저장된 작업 상태를 확인할 수 없습니다.",
                status_code=503,
            ) from None
        if not isinstance(engine_request, dict):
            raise B62OrchestrationError(
                "invalid_orchestration_state",
                "저장된 작업 상태를 확인할 수 없습니다.",
                status_code=503,
            )
        return OrchestrationSnapshot(
            continuation_ref=str(row.get("continuation_ref", "")),
            user_id=str(row.get("user_id", "")),
            pause_id=str(row.get("pause_id", "")),
            engine_request=engine_request,
            user_text=str(row.get("user_text", "")),
            conversation_id=(
                str(row.get("conversation_id")) if row.get("conversation_id") is not None else None
            ),
            expires_at=str(row.get("expires_at", "")),
            state="active",
        )

    async def record_decision(
        self,
        *,
        snapshot: OrchestrationSnapshot,
        decision_id: str,
        outcome: str,
        authority_ref: str,
        evidence_ref: str,
        decided_at: str,
    ) -> None:
        await self._run(
            "INSERT INTO orchestration_decisions "
            "(decision_id, continuation_ref, user_id, pause_id, outcome, authority_ref, evidence_ref, decided_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            decision_id,
            snapshot.continuation_ref,
            snapshot.user_id,
            snapshot.pause_id,
            outcome,
            authority_ref,
            evidence_ref,
            decided_at,
            _now_iso(),
        )
        await self._run(
            "UPDATE orchestration_continuations SET state='resuming', updated_at=? "
            "WHERE continuation_ref=? AND user_id=? AND state='active'",
            _now_iso(),
            snapshot.continuation_ref,
            snapshot.user_id,
        )

    async def set_state(
        self,
        *,
        user_id: str,
        continuation_ref: str,
        state: str,
    ) -> None:
        if state not in {"active", "resumed", "completed", "denied", "cancelled", "expired"}:
            raise ValueError("unsupported orchestration state")
        await self._run(
            "UPDATE orchestration_continuations SET state=?, updated_at=? "
            "WHERE continuation_ref=? AND user_id=?",
            state,
            _now_iso(),
            continuation_ref,
            user_id,
        )


def _safe_id(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise B62OrchestrationError(
            "invalid_engine_response",
            "AI 작업 상태를 안전하게 표시할 수 없습니다.",
            status_code=502,
        )
    return value


def _safe_events(raw_events: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_events, list) or not raw_events:
        raise B62OrchestrationError(
            "invalid_engine_response",
            "AI 작업 상태를 확인할 수 없습니다.",
            status_code=502,
        )
    out: list[dict[str, Any]] = []
    previous = 0
    for raw in raw_events:
        if not isinstance(raw, Mapping):
            raise B62OrchestrationError("invalid_engine_response", "AI 작업 상태를 확인할 수 없습니다.", status_code=502)
        kind = raw.get("kind")
        sequence = raw.get("sequence")
        if kind not in _ALLOWED_EVENT_KINDS or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= previous:
            raise B62OrchestrationError("invalid_engine_response", "AI 작업 상태를 확인할 수 없습니다.", status_code=502)
        previous = sequence
        out.append(
            {
                "event_id": _safe_id("event_id", raw.get("event_id")),
                "run_id": _safe_id("run_id", raw.get("run_id")),
                "trace_id": _safe_id("trace_id", raw.get("trace_id")),
                "app_id": _safe_id("app_id", raw.get("app_id")),
                "kind": kind,
                "sequence": sequence,
            }
        )
    return out


def project_public_orchestration(raw: Any) -> dict[str, Any]:
    """Project only B62-safe lifecycle data; drop route/context/plan/tool metadata."""
    if not isinstance(raw, Mapping):
        raise B62OrchestrationError("invalid_engine_response", "AI 작업 응답을 확인할 수 없습니다.", status_code=502)
    events = _safe_events(raw.get("events"))
    latest = events[-1]["kind"]
    public: dict[str, Any] = {
        "events": events,
        "approval_pause": None,
        "continuation_ref": None,
        "answer": None,
    }
    pause = raw.get("approval_pause")
    if latest == "approval_paused" or pause is not None:
        ref = raw.get("continuation_ref")
        if not isinstance(ref, str) or not _CONTINUATION_RE.fullmatch(ref) or not isinstance(pause, Mapping):
            raise B62OrchestrationError("invalid_engine_response", "확인이 필요한 작업 상태를 확인할 수 없습니다.", status_code=502)
        pause_id = _safe_id("pause_id", pause.get("continuation_id"))
        requirement = pause.get("requirement")
        expires_at = pause.get("expires_at")
        if pause.get("status") != "paused" or requirement not in {"user_confirmation", "external_authorization"} or not isinstance(expires_at, str):
            raise B62OrchestrationError("invalid_engine_response", "확인이 필요한 작업 상태를 확인할 수 없습니다.", status_code=502)
        _parse_aware(expires_at)
        public["approval_pause"] = {
            "status": "paused",
            "continuation_id": pause_id,
            "requirement": requirement,
            "expires_at": expires_at,
        }
        public["continuation_ref"] = ref
    if latest == "run_completed":
        execution = raw.get("execution")
        answer = execution.get("answer") if isinstance(execution, Mapping) else None
        if not isinstance(answer, str) or not answer.strip():
            raise B62OrchestrationError("invalid_engine_response", "AI가 표시할 답변을 만들지 못했습니다.", status_code=502)
        public["answer"] = answer.strip()
    if latest in _TERMINAL_EVENT_KINDS and public["approval_pause"] is not None:
        raise B62OrchestrationError("invalid_engine_response", "AI 작업 상태가 서로 충돌합니다.", status_code=502)
    return public


def project_cancel_result(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or raw.get("status") != "cancelled":
        raise B62OrchestrationError("invalid_engine_response", "작업 취소 결과를 확인할 수 없습니다.", status_code=502)
    events = _safe_events(raw.get("events"))
    if events[-1]["kind"] != "run_cancelled":
        raise B62OrchestrationError("invalid_engine_response", "작업 취소 결과를 확인할 수 없습니다.", status_code=502)
    return {"events": events, "approval_pause": None, "continuation_ref": None, "answer": None}


def _engine_error(exc: PadiemAiEngineClientError) -> B62OrchestrationError:
    code = exc.code if isinstance(exc.code, str) else "engine_request_failed"
    status = exc.status if isinstance(exc.status, int) and 400 <= exc.status <= 599 else 502
    messages = {
        "continuation_identity_mismatch": "이전 작업과 현재 확인 요청이 일치하지 않습니다.",
        "continuation_expired": "확인 가능한 시간이 지나 작업을 이어갈 수 없습니다.",
        "approval_decision_expired": "확인 가능한 시간이 지나 작업을 이어갈 수 없습니다.",
        "upstream_timeout": "AI 응답 시간이 초과되었습니다. 다시 시도해 주세요.",
        "upstream_rate_limited": "AI 사용량이 잠시 많습니다. 잠시 후 다시 시도해 주세요.",
    }
    return B62OrchestrationError(code, messages.get(code, "AI 작업을 처리하지 못했습니다. 다시 시도해 주세요."), status_code=status)


class B62EngineOrchestrationBridge:
    def __init__(self, *, client: PadiemAiEngineClient, store: OrchestrationStateStore) -> None:
        if client is None or store is None:
            raise ValueError("client and store are required")
        self._client = client
        self._store = store
        self.ready = True

    @staticmethod
    def build_engine_request(
        *,
        user_id: str,
        messages: Sequence[Mapping[str, str]],
        skill: Any,
        model_id: str,
        conversation_id: str | None,
        additional_system_context: str | None = None,
    ) -> dict[str, Any]:
        _safe_id("user_id", user_id)
        trace_id = f"b62_orch_{uuid.uuid4().hex[:24]}"
        agent_id = f"b62_{getattr(skill, 'id', 'auto')}"
        request: dict[str, Any] = {
            "agent": {
                "id": _safe_id("agent_id", agent_id),
                "title": str(getattr(skill, "title", "Padiem Chat")),
                "description": str(getattr(skill, "description", "Padiem Chat request")),
                "system_instruction": getattr(skill, "system_instruction", None),
                "task_type": str(getattr(skill, "task_type", "general")),
                "optimize_for": str(getattr(skill, "optimize_for", "balanced")),
                "max_tokens": getattr(skill, "max_tokens", None),
                "model_policy": {"model": model_id},
            },
            "messages": [dict(item) for item in messages],
            "trace_id": trace_id,
            "execution_context": {"trace_id": trace_id},
            "subject_id": user_id,
            "max_retries": 3,
            "require_evidence": False,
            "require_verification": False,
        }
        if conversation_id is not None:
            request["session_id"] = conversation_id
        if additional_system_context:
            request["additional_system_context"] = additional_system_context
        return request

    async def _persist_pause(
        self,
        *,
        public: Mapping[str, Any],
        engine_request: Mapping[str, Any],
        user_id: str,
        user_text: str,
        conversation_id: str | None,
    ) -> None:
        pause = public.get("approval_pause")
        ref = public.get("continuation_ref")
        if pause is None:
            return
        assert isinstance(pause, Mapping) and isinstance(ref, str)
        await self._store.save_pause(
            user_id=user_id,
            continuation_ref=ref,
            pause_id=str(pause["continuation_id"]),
            engine_request=engine_request,
            user_text=user_text,
            conversation_id=conversation_id,
            expires_at=str(pause["expires_at"]),
        )

    async def start(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, str]],
        skill: Any,
        model_id: str,
        user_text: str,
        conversation_id: str | None,
        additional_system_context: str | None = None,
    ) -> B62OrchestrationResult:
        engine_request = self.build_engine_request(
            user_id=user_id,
            messages=messages,
            skill=skill,
            model_id=model_id,
            conversation_id=conversation_id,
            additional_system_context=additional_system_context,
        )
        try:
            raw = await self._client.orchestrate(engine_request)
        except PadiemAiEngineClientError as exc:
            raise _engine_error(exc) from exc
        public = project_public_orchestration(raw)
        await self._persist_pause(
            public=public,
            engine_request=engine_request,
            user_id=user_id,
            user_text=user_text,
            conversation_id=conversation_id,
        )
        answer = public.get("answer") if isinstance(public.get("answer"), str) else None
        return B62OrchestrationResult(public, answer, user_text, conversation_id)

    async def resume(
        self,
        *,
        user_id: str,
        continuation_ref: str,
        pause_id: str,
        outcome: str,
    ) -> B62OrchestrationResult:
        snapshot = await self._store.load_active(user_id=user_id, continuation_ref=continuation_ref)
        if snapshot.pause_id != pause_id:
            raise B62OrchestrationError(
                "continuation_identity_mismatch",
                "확인 요청이 현재 작업과 일치하지 않습니다.",
                status_code=409,
            )
        if _parse_aware(snapshot.expires_at) <= datetime.now(timezone.utc):
            await self._store.set_state(user_id=user_id, continuation_ref=continuation_ref, state="expired")
            raise B62OrchestrationError("continuation_expired", "확인 가능한 시간이 지나 작업을 이어갈 수 없습니다.", status_code=409)
        if outcome not in {"approved", "denied"}:
            raise B62OrchestrationError("invalid_approval_intent", "확인 선택이 올바르지 않습니다.", status_code=422)

        decision_id = f"decision_{uuid.uuid4().hex}"
        authority_ref = f"b62_session:{user_id}"
        evidence_ref = f"b62_decision:{decision_id}"
        decided_at = _now_iso()
        await self._store.record_decision(
            snapshot=snapshot,
            decision_id=decision_id,
            outcome=outcome,
            authority_ref=authority_ref,
            evidence_ref=evidence_ref,
            decided_at=decided_at,
        )
        resume_request = dict(snapshot.engine_request)
        resume_request["continuation_ref"] = snapshot.continuation_ref
        resume_request["decision"] = {
            "decision_id": decision_id,
            "pause_id": snapshot.pause_id,
            "outcome": outcome,
            "authority_ref": authority_ref,
            "evidence_ref": evidence_ref,
            "decided_at": decided_at,
        }
        try:
            raw = await self._client.resume_orchestration(resume_request)
        except PadiemAiEngineClientError as exc:
            if exc.code == "approval_denied":
                await self._store.set_state(user_id=user_id, continuation_ref=continuation_ref, state="denied")
                return B62OrchestrationResult(
                    {"events": [], "approval_pause": None, "continuation_ref": None, "answer": None},
                    None,
                    snapshot.user_text,
                    snapshot.conversation_id,
                    decision_status="denied",
                )
            await self._store.set_state(user_id=user_id, continuation_ref=continuation_ref, state="active")
            raise _engine_error(exc) from exc

        public = project_public_orchestration(raw)
        next_pause = public.get("approval_pause")
        await self._store.set_state(
            user_id=user_id,
            continuation_ref=continuation_ref,
            state="resumed" if next_pause is not None else "completed",
        )
        if next_pause is not None:
            await self._persist_pause(
                public=public,
                engine_request=snapshot.engine_request,
                user_id=user_id,
                user_text=snapshot.user_text,
                conversation_id=snapshot.conversation_id,
            )
        answer = public.get("answer") if isinstance(public.get("answer"), str) else None
        return B62OrchestrationResult(public, answer, snapshot.user_text, snapshot.conversation_id)

    async def cancel(self, *, user_id: str, continuation_ref: str) -> B62OrchestrationResult:
        snapshot = await self._store.load_active(user_id=user_id, continuation_ref=continuation_ref)
        try:
            raw = await self._client.cancel_orchestration_pause(
                {"continuation_ref": snapshot.continuation_ref, "reason": "user_cancelled"}
            )
        except PadiemAiEngineClientError as exc:
            raise _engine_error(exc) from exc
        public = project_cancel_result(raw)
        await self._store.set_state(user_id=user_id, continuation_ref=continuation_ref, state="cancelled")
        return B62OrchestrationResult(
            public,
            None,
            snapshot.user_text,
            snapshot.conversation_id,
            decision_status="cancelled",
        )
