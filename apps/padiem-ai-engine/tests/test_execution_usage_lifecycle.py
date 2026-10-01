"""Regression coverage for #3287 Engine E7 usage lifecycle binding."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core import (
    ApprovalPause,
    ApprovalRequirement,
    B14RouteMetadata,
    ExecutionRequest,
    ExecutionResult,
    IdempotencyConflictError,
    RunMetadata,
    RunStatus,
    VerifiedApprovalDecision,
)

from app.continuation_binding import InMemoryIdentityBoundContinuationStore
from app.continuation_identity import build_continuation_execution_identity
from app.execution_admission import (
    ExecutionAdmissionError,
    TrustedExecutionAdmission,
    TrustedUsageReservation,
)
from app.execution_admission_resume import OriginalAdmissionBinding
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from app.orchestration_idempotency_service import _initial_execution_fingerprint
from app.service import build_execution_request


class Runtime:
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        if self.mode == "fail":
            raise RuntimeError("injected runtime failure")
        if self.mode == "cancel":
            raise asyncio.CancelledError()
        return ExecutionResult(
            answer="usage lifecycle result",
            route=B14RouteMetadata(
                selected_provider="mock_provider",
                selected_model="mock_model",
            ),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_usage",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class ReplayAdapter:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], tuple[str, ExecutionResult | None]] = {}

    async def begin(self, *, app_id: str, idempotency_key: str, request_fingerprint: str):
        key = (app_id, idempotency_key)
        current = self.records.get(key)
        if current is None:
            self.records[key] = (request_fingerprint, None)
            return None
        existing_fingerprint, result = current
        if existing_fingerprint != request_fingerprint:
            raise IdempotencyConflictError("conflicting logical execution")
        return result

    async def complete(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        result,
    ) -> None:
        assert isinstance(result, ExecutionResult)
        self.records[(app_id, idempotency_key)] = (request_fingerprint, result)

    async def commit(self, **kwargs) -> None:
        await self.complete(**kwargs)

    async def abort(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        reason: str | None = None,
    ) -> None:
        del reason
        self.records.pop((app_id, idempotency_key), None)


class UsageAwareAdapter:
    """Server-side authority double with idempotent CP event persistence."""

    def __init__(
        self,
        *,
        deny: bool = False,
        fail_receipt: bool = False,
    ) -> None:
        self.deny = deny
        self.fail_receipt = fail_receipt
        self.admission_calls = []
        self.receipt_calls = []
        self.events: dict[str, dict] = {}
        self._reserved_at: dict[str, datetime] = {}

    def _reservation(self, request) -> TrustedUsageReservation:
        assert request.request_fingerprint is not None
        reserved_at = self._reserved_at.setdefault(
            request.request_fingerprint,
            datetime.now(timezone.utc),
        )
        return TrustedUsageReservation(
            reservation_ref=f"cp_res_{request.request_fingerprint[:16]}",
            idempotency_key=f"res-{request.request_fingerprint}",
            billing_semantic_id="orchestration.run",
            product_id=request.app_id,
            subject_type="user" if request.subject_id is not None else "account",
            subject_id=request.subject_id or request.app_id,
            request_fingerprint=request.request_fingerprint,
            reserved_at=reserved_at,
            expires_at=reserved_at + timedelta(minutes=10),
        )

    def resolve_admission(self, request):
        self.admission_calls.append(request)
        now = datetime.now(timezone.utc)
        allowed = not self.deny
        reservation = None
        if allowed and request.capability == "orchestration.run":
            reservation = self._reservation(request)
        return TrustedExecutionAdmission(
            decision_id=(
                "adm_run_usage_1"
                if request.capability == "orchestration.run"
                else "adm_resume_usage_1"
            ),
            app_id=request.app_id,
            subject_id=request.subject_id,
            capability=request.capability,
            allowed=allowed,
            authority_ref="control-plane:entitlement:e7",
            policy_revision="policy:e7:1",
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
            request_fingerprint=request.request_fingerprint,
            usage_reservation=reservation,
        )

    async def record_usage_receipt(self, receipt):
        self.receipt_calls.append(receipt)
        if self.fail_receipt:
            raise ExecutionAdmissionError(
                "entitlement_unavailable",
                "Control Plane usage receipt authority is unavailable.",
                status_code=503,
            )
        payload = receipt.to_public_dict()
        existing = self.events.get(receipt.event_id)
        if existing is not None and existing != payload:
            raise AssertionError("same event id changed payload")
        self.events[receipt.event_id] = payload
        return {"accepted": True, "event_id": receipt.event_id}


class Verifier:
    def verify(self, submission, *, pause, app_id):
        del app_id
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=pause.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


def _payload(*, with_idempotency: bool = False) -> dict:
    context = {
        "trace_id": "tr_usage",
        "timeout_seconds": 15.0,
    }
    if with_idempotency:
        context["idempotency_key"] = "idem_usage_1"
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
            "model_policy": {"model": "test/route"},
        },
        "messages": [{"role": "user", "content": "Run admitted work"}],
        "session_id": "session:usage_1",
        "additional_system_context": "Trusted product context",
        "trace_id": "tr_usage",
        "execution_context": context,
        "subject_id": "subject:owner",
        "max_retries": 2,
        "require_evidence": False,
        "require_verification": False,
    }


def _service(
    adapter: UsageAwareAdapter,
    *,
    runtime: Runtime | None = None,
    idempotency_adapter=None,
    continuation_store=None,
):
    runtime = runtime or Runtime()
    service = AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        admission_adapter=adapter,
        idempotency_adapter=idempotency_adapter,
        continuation_store=continuation_store,
        approval_decision_verifier=Verifier() if continuation_store is not None else None,
    )
    return service, runtime


async def test_success_dispatch_records_exactly_one_bounded_usage_receipt() -> None:
    adapter = UsageAwareAdapter()
    service, runtime = _service(adapter)

    response = await service.orchestrate_payload(_payload())

    assert response.status_code == 200
    assert runtime.call_count == 1
    assert len(adapter.receipt_calls) == 1
    assert len(adapter.events) == 1
    event = next(iter(adapter.events.values()))
    assert event["outcome"] == "succeeded"
    assert event["billing_disposition"] == "billable"
    assert event["route"] == {"status": "unknown"}
    assert event["cost"] is None
    assert event["billing_semantic_id"] == "orchestration.run"


async def test_failed_after_dispatch_records_bounded_terminal_receipt() -> None:
    adapter = UsageAwareAdapter()
    service, runtime = _service(adapter, runtime=Runtime("fail"))

    response = await service.orchestrate_payload(_payload())

    assert response.status_code >= 400
    assert runtime.call_count == 1
    assert len(adapter.events) == 1
    event = next(iter(adapter.events.values()))
    assert event["outcome"] == "failed"
    assert event["billing_disposition"] == "non_billable"
    assert event["route"] == {"status": "unknown"}
    assert event["cost"] is None


async def test_cancelled_after_dispatch_records_bounded_terminal_receipt() -> None:
    adapter = UsageAwareAdapter()
    service, runtime = _service(adapter, runtime=Runtime("cancel"))

    with pytest.raises(asyncio.CancelledError):
        await service.orchestrate_payload(_payload())

    assert runtime.call_count == 1
    assert len(adapter.events) == 1
    event = next(iter(adapter.events.values()))
    assert event["outcome"] == "cancelled"
    assert event["billing_disposition"] == "non_billable"


async def test_pre_dispatch_rejection_creates_no_false_usage_event() -> None:
    adapter = UsageAwareAdapter(deny=True)
    service, runtime = _service(adapter)

    response = await service.orchestrate_payload(_payload())

    assert response.status_code == 403
    assert runtime.call_count == 0
    assert adapter.receipt_calls == []
    assert adapter.events == {}


async def test_idempotent_replay_does_not_create_second_usage_event() -> None:
    adapter = UsageAwareAdapter()
    service, runtime = _service(
        adapter,
        idempotency_adapter=ReplayAdapter(),
    )
    payload = _payload(with_idempotency=True)

    first = await service.orchestrate_payload(payload)
    second = await service.orchestrate_payload(deepcopy(payload))

    assert first.status_code == 200
    assert second.status_code == 200
    assert runtime.call_count == 1
    # The replay re-submits the same deterministic receipt so a lost CP
    # acknowledgement can recover, but CP idempotency creates no second event.
    assert len(adapter.receipt_calls) == 2
    assert adapter.receipt_calls[0].event_id == adapter.receipt_calls[1].event_id
    assert adapter.receipt_calls[0].to_public_dict() == adapter.receipt_calls[1].to_public_dict()
    assert len(adapter.events) == 1
    assert second.body["orchestration"]["events"][-1]["metadata"]["replay"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("tokens", {"total_tokens": 999999}),
        ("cost", {"amount": "999.00"}),
        ("route", {"status": "observed", "provider": "forged"}),
        ("billing_disposition", "billable"),
        ("usage_event", {"outcome": "succeeded"}),
    ],
)
async def test_client_usage_fields_are_never_authority(field, value) -> None:
    adapter = UsageAwareAdapter()
    service, runtime = _service(adapter)
    payload = _payload()
    payload[field] = value

    response = await service.orchestrate_payload(payload)

    assert response.status_code == 400
    assert runtime.call_count == 0
    assert adapter.admission_calls == []
    assert adapter.receipt_calls == []


async def test_control_plane_receipt_failure_is_not_silently_dropped() -> None:
    adapter = UsageAwareAdapter(fail_receipt=True)
    service, runtime = _service(adapter)

    response = await service.orchestrate_payload(_payload())

    assert runtime.call_count == 1
    assert response.status_code == 503
    assert response.body["error"]["code"] == "entitlement_unavailable"
    assert len(adapter.receipt_calls) == 1
    assert adapter.events == {}


async def test_resume_uses_original_run_reservation_without_duplicate_accounting() -> None:
    adapter = UsageAwareAdapter()
    store = InMemoryIdentityBoundContinuationStore()
    runtime = Runtime()
    service, _ = _service(adapter, runtime=runtime, continuation_store=store)
    payload = _payload()

    fingerprint = _initial_execution_fingerprint(payload)
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    original_request = type("Request", (), {
        "request_fingerprint": fingerprint,
        "app_id": "b62",
        "subject_id": "subject:owner",
    })()
    original = OriginalAdmissionBinding(
        decision_id="adm_run_usage_original",
        app_id="b62",
        subject_id="subject:owner",
        authority_ref="control-plane:entitlement:e7",
        policy_revision="policy:e7:1",
        request_fingerprint=fingerprint,
        usage_reservation=adapter._reservation(original_request),
    )

    _, execution_request, context = build_execution_request(
        {
            key: payload[key]
            for key in (
                "app_id",
                "agent",
                "messages",
                "session_id",
                "additional_system_context",
                "trace_id",
                "execution_context",
            )
            if key in payload
        }
    )
    assert context is not None
    identity = build_continuation_execution_identity(
        app_id="b62",
        request=execution_request,
        context=context,
        subject_id="subject:owner",
        plan=None,
        recovery_policy=None,
        max_retries=2,
        require_evidence=False,
        require_verification=False,
    )
    now = datetime.now(timezone.utc)
    pause = ApprovalPause(
        pause_id="pause_usage_1",
        run_id="run_usage_1",
        agent_runtime_id="agent:padiem:orchestrator_1",
        tool_id="calc",
        invocation_sha256="0" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        trace_id=context.trace_id,
    )
    continuation_ref = store.issue(
        app_id="b62",
        pause=pause,
        execution_identity=identity,
        original_admission=original,
    )

    resume = deepcopy(payload)
    resume["continuation_ref"] = continuation_ref
    resume["decision"] = {
        "decision_id": "dec_usage_1",
        "pause_id": "pause_usage_1",
        "outcome": "approved",
        "authority_ref": "user:admin",
        "evidence_ref": "session:auth",
        "decided_at": (now - timedelta(milliseconds=100)).isoformat(),
    }

    response = await service.resume_payload(resume)

    assert response.status_code == 200
    assert runtime.call_count == 1
    assert len(adapter.admission_calls) == 1
    assert adapter.admission_calls[0].capability == "orchestration.resume"
    assert len(adapter.receipt_calls) == 1
    assert len(adapter.events) == 1
    event = next(iter(adapter.events.values()))
    assert event["billing_semantic_id"] == "orchestration.run"
    assert event["outcome"] == "succeeded"
    assert event["route"] == {"status": "unknown"}
    assert event["cost"] is None


def test_e7_usage_lifecycle_does_not_claim_billing_or_provider_authority() -> None:
    import app.usage_lifecycle as usage_lifecycle

    assert usage_lifecycle.ENGINE_BILLING_LEDGER is False
    assert usage_lifecycle.B14_PROVIDER_AUTHORITY_WIDENED is False
