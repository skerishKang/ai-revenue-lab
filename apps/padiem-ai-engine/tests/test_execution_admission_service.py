"""Regression coverage for #1241 orchestration.run admission enforcement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionRequest,
    ExecutionResult,
    RunMetadata,
    RunStatus,
)

from app.execution_admission import TrustedExecutionAdmission
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService


class CountingRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer="admitted",
            route=B14RouteMetadata(
                selected_provider="mock_provider",
                selected_model="mock_model",
            ),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_admission",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class AllowingAdapter:
    def __init__(self) -> None:
        self.calls = []

    def resolve_admission(self, request):
        self.calls.append(request)
        now = datetime.now(timezone.utc)
        return TrustedExecutionAdmission(
            decision_id="adm_run_1",
            app_id=request.app_id,
            subject_id=request.subject_id,
            capability=request.capability,
            allowed=True,
            authority_ref="control-plane:entitlement:run",
            policy_revision="policy:run:1",
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
            request_fingerprint=request.request_fingerprint,
        )


class DenyingAdapter(AllowingAdapter):
    def resolve_admission(self, request):
        self.calls.append(request)
        now = datetime.now(timezone.utc)
        return TrustedExecutionAdmission(
            decision_id="adm_run_deny",
            app_id=request.app_id,
            subject_id=request.subject_id,
            capability=request.capability,
            allowed=False,
            authority_ref="control-plane:entitlement:run",
            policy_revision="policy:run:1",
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
            request_fingerprint=request.request_fingerprint,
        )


class UnboundAdapter(AllowingAdapter):
    def resolve_admission(self, request):
        self.calls.append(request)
        now = datetime.now(timezone.utc)
        return TrustedExecutionAdmission(
            decision_id="adm_run_unbound",
            app_id=request.app_id,
            subject_id=request.subject_id,
            capability=request.capability,
            allowed=True,
            authority_ref="control-plane:entitlement:run",
            policy_revision="policy:run:1",
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
            request_fingerprint=None,
        )


def _payload() -> dict:
    return {
        "app_id": "b62",
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks safely",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
            "required_capabilities": ["chat"],
            "model_policy": {"mode": "balanced"},
        },
        "messages": [{"role": "user", "content": "Run admitted work"}],
        "session_id": "session:admission_1",
        "additional_system_context": "Trusted product context",
        "trace_id": "tr_admission_run",
        "execution_context": {
            "trace_id": "tr_admission_run",
            "timeout_seconds": 15.0,
        },
        "subject_id": "subject:owner",
        "max_retries": 2,
        "require_evidence": False,
        "require_verification": False,
    }


def _service(adapter):
    runtime = CountingRuntime()
    service = AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        admission_adapter=adapter,
    )
    return service, runtime


async def test_valid_trusted_run_admission_executes_core_once() -> None:
    adapter = AllowingAdapter()
    service, runtime = _service(adapter)

    response = await service.orchestrate_payload(_payload())

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert runtime.call_count == 1
    assert len(adapter.calls) == 1
    request = adapter.calls[0]
    assert request.app_id == "b62"
    assert request.subject_id == "subject:owner"
    assert request.capability == "orchestration.run"
    assert isinstance(request.request_fingerprint, str)
    assert len(request.request_fingerprint) == 64


async def test_missing_trusted_run_admission_fails_closed_before_core() -> None:
    service, runtime = _service(None)

    response = await service.orchestrate_payload(_payload())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "entitlement_unavailable"
    assert runtime.call_count == 0


async def test_denied_trusted_run_admission_fails_before_core() -> None:
    adapter = DenyingAdapter()
    service, runtime = _service(adapter)

    response = await service.orchestrate_payload(_payload())

    assert response.status_code == 403
    assert response.body["error"]["code"] == "entitlement_denied"
    assert runtime.call_count == 0
    assert len(adapter.calls) == 1


async def test_unbound_trusted_run_admission_is_not_execution_authority() -> None:
    adapter = UnboundAdapter()
    service, runtime = _service(adapter)

    response = await service.orchestrate_payload(_payload())

    assert response.status_code == 403
    assert response.body["error"]["code"] == "entitlement_request_mismatch"
    assert runtime.call_count == 0
    assert len(adapter.calls) == 1


async def test_client_entitlement_assertions_are_rejected_before_admission_lookup() -> None:
    adapter = AllowingAdapter()
    service, runtime = _service(adapter)
    payload = _payload()
    payload["entitlement"] = {"allow": True, "plan": "pro", "credit_balance": 999999}

    response = await service.orchestrate_payload(payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "unsupported_orchestration_field"
    assert adapter.calls == []
    assert runtime.call_count == 0


async def test_material_execution_change_changes_server_admission_request_identity() -> None:
    adapter = AllowingAdapter()
    service, runtime = _service(adapter)
    first = _payload()
    second = _payload()
    second["additional_system_context"] = "Different material context"

    first_response = await service.orchestrate_payload(first)
    second_response = await service.orchestrate_payload(second)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert runtime.call_count == 2
    assert len(adapter.calls) == 2
    assert adapter.calls[0].request_fingerprint != adapter.calls[1].request_fingerprint
