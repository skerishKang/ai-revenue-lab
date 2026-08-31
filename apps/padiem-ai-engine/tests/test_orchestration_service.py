"""Tests for Padiem AI Engine Orchestration Service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import pytest

from padiem_ai_core import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    B14RouteMetadata,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
    RunMetadata,
    RunStatus,
    VerifiedApprovalDecision,
)

from app.orchestration_service import (
    ORCHESTRATE_CANCEL_PATH,
    ORCHESTRATE_PATH,
    ORCHESTRATE_RESUME_PATH,
    InMemoryContinuationStore,
    OrchestrationEngineService,
)
from app.service import ServiceResponse


class MockEngineRuntime:
    def __init__(self, answer: str = "engine answer") -> None:
        self._answer = answer
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer=self._answer,
            route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_engine",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


def make_valid_payload(app_id: str = "b62") -> dict:
    return {
        "app_id": app_id,
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
        },
        "messages": [{"role": "user", "content": "Hello engine"}],
        "trace_id": "tr_orch_test",
        "execution_context": {
            "trace_id": "tr_orch_test",
            "timeout_seconds": 15.0,
        },
    }


def make_pause_payload() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "pause_id": "pause_eng_1",
        "run_id": "run_eng_1",
        "agent_runtime_id": "agent:padiem:orchestrator_1",
        "tool_id": "calc",
        "invocation_sha256": "0" * 64,
        "requirement": "user_confirmation",
        "step_index": 1,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "trace_id": "tr_orch_test",
        "agent_id": "agent:padiem:orchestrator_1",
    }


def make_decision_payload(outcome: str = "approved") -> dict:
    return {
        "decision_id": "dec_eng_1",
        "pause_id": "pause_eng_1",
        "outcome": outcome,
        "authority_ref": "user:admin",
        "evidence_ref": "session:auth",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }


class TestApprovalDecisionVerifier:
    def verify(self, submission, *, pause, app_id):
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


def make_server_continuation(service: OrchestrationEngineService) -> dict:
    pause_data = make_pause_payload()
    pause = ApprovalPause(
        pause_id=pause_data["pause_id"],
        run_id=pause_data["run_id"],
        agent_runtime_id=pause_data["agent_runtime_id"],
        tool_id=pause_data["tool_id"],
        invocation_sha256=pause_data["invocation_sha256"],
        requirement=ApprovalRequirement(pause_data["requirement"]),
        step_index=pause_data["step_index"],
        created_at=datetime.fromisoformat(pause_data["created_at"]),
        expires_at=datetime.fromisoformat(pause_data["expires_at"]),
        trace_id=pause_data["trace_id"],
    )
    store = service._continuation_store
    ref = store.issue(app_id="b62", pause=pause, plan_id=None)
    return ref


# ==============================================================================
# Unit Tests for OrchestrationEngineService
# ==============================================================================

async def test_orchestrate_successful_run() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(answer="orchestrated answer"),
        b14_service_bound=True,
    )
    payload = make_valid_payload()
    response = await service.orchestrate_payload(payload)

    assert response.status_code == 200
    assert response.body["ok"] is True
    orch = response.body["orchestration"]
    assert orch["execution"]["answer"] == "orchestrated answer"
    assert orch["state_machine"]["current_state"] == ExecutionState.COMPLETED.value


async def test_orchestrate_with_b14_unbound_fails_503() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=False,
    )
    payload = make_valid_payload()
    response = await service.orchestrate_payload(payload)

    assert response.status_code == 503
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "b14_service_unavailable"


async def test_orchestrate_resume_success() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(answer="resumed answer"),
        b14_service_bound=True,
        approval_decision_verifier=TestApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    payload = make_valid_payload()
    payload["continuation_ref"] = make_server_continuation(service)
    payload["decision"] = make_decision_payload("approved")

    response = await service.resume_payload(payload)
    assert response.status_code == 200
    assert response.body["ok"] is True
    orch = response.body["orchestration"]
    assert orch["execution"]["answer"] == "resumed answer"
    assert orch["state_machine"]["current_state"] == ExecutionState.COMPLETED.value


async def test_orchestrate_resume_denied_fails_409() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
        approval_decision_verifier=TestApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    payload = make_valid_payload()
    payload["continuation_ref"] = make_server_continuation(service)
    payload["decision"] = make_decision_payload("denied")

    response = await service.resume_payload(payload)
    assert response.status_code == 409
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "approval_denied"


async def test_resume_without_trusted_verifier_fails_closed() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
        continuation_store=InMemoryContinuationStore(),
    )
    payload = make_valid_payload()
    payload["continuation_ref"] = make_server_continuation(service)
    payload["decision"] = make_decision_payload("approved")

    response = await service.resume_payload(payload)
    assert response.status_code == 503
    assert response.body["error"]["code"] == "approval_verification_unavailable"


async def test_resume_rejects_cross_app_continuation_ref() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
        approval_decision_verifier=TestApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    continuation_ref = make_server_continuation(service)
    payload = make_valid_payload(app_id="other-app")
    payload["continuation_ref"] = continuation_ref
    payload["decision"] = make_decision_payload("approved")

    response = await service.resume_payload(payload)
    assert response.status_code == 409
    assert response.body["error"]["code"] == "invalid_continuation"


async def test_resume_rejects_unknown_or_tampered_continuation_ref() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
        approval_decision_verifier=TestApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    payload = make_valid_payload()
    payload["continuation_ref"] = "cont_not_server_issued"
    payload["decision"] = make_decision_payload("approved")

    response = await service.resume_payload(payload)
    assert response.status_code == 409
    assert response.body["error"]["code"] == "invalid_continuation"


async def test_resume_continuation_is_one_time() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(answer="resumed answer"),
        b14_service_bound=True,
        approval_decision_verifier=TestApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    payload = make_valid_payload()
    payload["continuation_ref"] = make_server_continuation(service)
    payload["decision"] = make_decision_payload("approved")

    first = await service.resume_payload(payload)
    second = await service.resume_payload(payload)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.body["error"]["code"] == "continuation_consumed"


async def test_orchestrate_cancel_pause() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
        continuation_store=InMemoryContinuationStore(),
    )
    payload = {
        "app_id": "b62",
        "continuation_ref": make_server_continuation(service),
        "reason": "user_cancelled",
    }
    response = await service.cancel_payload(payload)
    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["status"] == "cancelled"
    assert len(response.body["events"]) == 1


async def test_resume_without_explicit_store_fails_closed() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
        approval_decision_verifier=TestApprovalDecisionVerifier(),
    )
    response = await service.resume_payload({"app_id": "b62", "continuation_ref": "cont_unknown"})
    assert response.status_code == 503
    assert response.body["error"]["code"] == "continuation_store_unavailable"


async def test_orchestrate_http_routing() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
    )
    # Test POST to /internal/v1/orchestrate
    raw_body = json.dumps(make_valid_payload()).encode("utf-8")
    resp = await service.handle(
        method="POST",
        path=ORCHESTRATE_PATH,
        content_type="application/json",
        body=raw_body,
    )
    assert resp.status_code == 200
    assert resp.body["ok"] is True

    # Test GET rejected with 405
    resp_get = await service.handle(
        method="GET",
        path=ORCHESTRATE_PATH,
        content_type="application/json",
        body=b"",
    )
    assert resp_get.status_code == 405

    # Test invalid path returns 404
    resp_404 = await service.handle(
        method="POST",
        path="/internal/v1/unknown",
        content_type="application/json",
        body=raw_body,
    )
    assert resp_404.status_code == 404


async def test_orchestrate_stream_route_is_explicitly_deferred_not_routed() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
    )
    raw_body = json.dumps(make_valid_payload()).encode("utf-8")

    response = await service.handle(
        method="POST",
        path="/internal/v1/orchestrate/stream",
        content_type="application/json",
        body=raw_body,
    )

    assert response.status_code == 404
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "not_found"
