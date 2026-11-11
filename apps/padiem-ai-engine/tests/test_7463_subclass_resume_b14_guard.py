"""#7463: 실제 조립 체인(CanonicalIdempotency 체인)의 resume이 never-issued ref를 409로 거절한다.

#7467이 부모 OrchestrationEngineService.resume_payload의 B14 가드를 저장소 조회
뒤로 옮겼지만, 실제로 호출되는 하위 클래스
(IdentityBoundOrchestrationEngineService·AdmissionBoundOrchestrationEngineService)
에는 선행 가드가 남아 배포 스모크 A10의 S1·S4가 409 대신 503
b14_service_unavailable로 실패했다. 이 시험은 worker_identity.py가 B14 미연결로
조립하는 것과 같은 서비스(b14_service_bound=False + continuation_store 연결)를
그대로 만들어 검사한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from padiem_ai_core import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    B14RouteMetadata,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    RunMetadata,
    RunStatus,
    VerifiedApprovalDecision,
)

from app.continuation_binding import InMemoryIdentityBoundContinuationStore
from app.continuation_identity import build_continuation_execution_identity
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from app.orchestration_idempotency_service import (
    CanonicalIdempotencyOrchestrationEngineService,
)
from app.service import build_execution_request

APP_ID = "b62"


class MockRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer="resumed",
            route=B14RouteMetadata(selected_provider="mock", selected_model="mock"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_7463",
                app_id=APP_ID,
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class Verifier:
    def verify(self, submission, *, pause, app_id):
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


def payload() -> dict:
    return {
        "app_id": APP_ID,
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
            "model_policy": {"model": "test/route"},
        },
        "messages": [{"role": "user", "content": "Hello engine"}],
        "session_id": "session_7463",
        "additional_system_context": "Bound context",
        "trace_id": "tr_7463",
        "execution_context": {"trace_id": "tr_7463", "timeout_seconds": 15.0},
        "subject_id": "subject_7463",
        "max_retries": 3,
        "require_evidence": False,
        "require_verification": False,
    }


def decision() -> dict:
    return {
        "decision_id": "decision_7463",
        "pause_id": "pause_7463",
        "outcome": ApprovalOutcome.APPROVED.value,
        "authority_ref": "user:admin",
        "evidence_ref": "session:auth",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }


def issue(store: InMemoryIdentityBoundContinuationStore, original: dict) -> str:
    _, request, context = build_execution_request(
        {
            key: original[key]
            for key in (
                "app_id", "agent", "messages", "session_id",
                "additional_system_context", "trace_id", "execution_context",
            )
            if key in original
        }
    )
    assert context is not None
    identity = build_continuation_execution_identity(
        app_id=original["app_id"],
        request=request,
        context=context,
        subject_id=original.get("subject_id"),
        plan=None,
        recovery_policy=None,
        max_retries=original.get("max_retries", 3),
        require_evidence=original.get("require_evidence", False),
        require_verification=original.get("require_verification", False),
    )
    now = datetime.now(timezone.utc)
    return store.issue(
        app_id=original["app_id"],
        pause=ApprovalPause(
            pause_id="pause_7463",
            run_id="run_7463",
            agent_runtime_id="agent:padiem:orchestrator_1",
            tool_id="calc",
            invocation_sha256="0" * 64,
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            trace_id="tr_7463",
        ),
        execution_identity=identity,
    )


def unbound_service(store, *, cls=CanonicalIdempotencyOrchestrationEngineService):
    """worker_identity.py가 B14 미연결로 조립하는 것과 같은 모양(b14_service_bound=False + 저장소)."""
    return cls(
        runtime_factory=lambda app_id: MockRuntime(),
        b14_service_bound=False,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )


async def test_a10_s1_never_issued_resume_is_409_not_503() -> None:
    """A10 S1: 서버가 발급한 적 없는 continuation_ref로 resume하면 409다(503 아님)."""
    store = InMemoryIdentityBoundContinuationStore()
    service = unbound_service(store)
    request = dict(payload())
    request["continuation_ref"] = "cont_" + "0" * 64  # 발급된 적 없는 올바른 형식
    request["decision"] = decision()
    response = await service.resume_payload(request)
    assert response.status_code == 409, response.body
    assert response.body["error"]["code"] == "invalid_continuation"


async def test_a10_s4_malformed_resume_ref_is_409_not_503() -> None:
    """A10 S4: 형식이 잘못된 continuation_ref로 resume하면 409다(503 아님)."""
    store = InMemoryIdentityBoundContinuationStore()
    service = unbound_service(store)
    request = dict(payload())
    request["continuation_ref"] = "not-a-continuation-ref"
    request["decision"] = decision()
    response = await service.resume_payload(request)
    assert response.status_code == 409, response.body
    assert response.body["error"]["code"] == "invalid_continuation"


async def test_a10_s2_cancel_never_issued_is_409() -> None:
    """A10 S2: cancel도 B14 미연결에서 never-issued ref를 409로 거절한다(기존 동작 유지)."""
    store = InMemoryIdentityBoundContinuationStore()
    service = unbound_service(store)
    response = await service.cancel_payload(
        {"app_id": APP_ID, "continuation_ref": "cont_" + "1" * 64}
    )
    assert response.status_code == 409, response.body
    assert response.body["error"]["code"] == "invalid_continuation"


async def test_a10_valid_continuation_without_b14_still_503_before_execution() -> None:
    """유효한 continuation인데 B14 미연결이면 저장소 조회 뒤 503이다(실행 경로만)."""
    store = InMemoryIdentityBoundContinuationStore()
    service = unbound_service(store)
    ref = issue(store, payload())
    request = dict(payload())
    request["continuation_ref"] = ref
    request["decision"] = decision()
    response = await service.resume_payload(request)
    assert response.status_code == 503, response.body
    assert response.body["error"]["code"] == "b14_service_unavailable"
    # 가드는 실행 시작 전에 있으므로 런타임은 호출되지 않는다.
    assert service._runtime_factory is not None


async def test_a10_admission_bound_resume_never_issued_is_409_not_503() -> None:
    """두 번째 고친 지점(AdmissionBound 체인)도 never-issued resume을 409로 거절한다."""
    store = InMemoryIdentityBoundContinuationStore()
    service = unbound_service(store, cls=AdmissionBoundOrchestrationEngineService)
    request = dict(payload())
    request["continuation_ref"] = "cont_" + "2" * 64
    request["decision"] = decision()
    response = await service.resume_payload(request)
    assert response.status_code == 409, response.body
    assert response.body["error"]["code"] == "invalid_continuation"


async def test_a7_orchestrate_b14_unavailable_still_503() -> None:
    """A7: B14 미연결 일반 요청(orchestrate)은 여전히 503 b14_service_unavailable이다."""
    store = InMemoryIdentityBoundContinuationStore()
    service = unbound_service(store)
    response = await service.orchestrate_payload(payload())
    assert response.status_code == 503, response.body
    assert response.body["error"]["code"] == "b14_service_unavailable"
