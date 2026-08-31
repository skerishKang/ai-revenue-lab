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
    )
    payload = make_valid_payload()
    payload["pause"] = make_pause_payload()
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
    )
    payload = make_valid_payload()
    payload["pause"] = make_pause_payload()
    payload["decision"] = make_decision_payload("denied")

    response = await service.resume_payload(payload)
    assert response.status_code == 409
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "approval_denied"


async def test_orchestrate_cancel_pause() -> None:
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: MockEngineRuntime(),
        b14_service_bound=True,
    )
    payload = {
        "app_id": "b62",
        "pause": make_pause_payload(),
        "reason": "user_cancelled",
    }
    response = await service.cancel_payload(payload)
    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["status"] == "cancelled"
    assert len(response.body["events"]) == 1


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
