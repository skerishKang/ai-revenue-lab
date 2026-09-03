"""Continuation-flow integration for #1241 trusted admission.

Proves that a validated ``orchestration.run`` admission automatically travels
into any approval continuation issued by that admitted execution, and that
resume requires fresh non-widening ``orchestration.resume`` admission before
any continuation claim or Core resume. Network-free and product-neutral.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core import (
    ApprovalRequirement,
    ApprovalPause,
    B14RouteMetadata,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    OrchestrationError,
    OrchestrationResult,
    RunMetadata,
    RunStatus,
    VerifiedApprovalDecision,
)

import app.execution_admission_service as adm_mod
import app.orchestration_identity_service as ident_mod
from app.continuation_binding import InMemoryIdentityBoundContinuationStore
from app.continuation_identity import build_continuation_execution_identity
from app.execution_admission import TrustedExecutionAdmission
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from app.service import build_execution_request


class PausingRunner:
    """Fake Core runner: run pauses once, resume completes (or pauses again)."""

    resume_count = 0
    fail_next: str | None = None
    pause_again = False

    def __init__(self, runtime=None, idempotency=None) -> None:
        self._runtime = runtime

    async def run(self, request) -> OrchestrationResult:
        now = datetime.now(timezone.utc)
        pause = ApprovalPause(
            pause_id="pause_flow_1",
            run_id="run_flow_1",
            agent_runtime_id="agent:padiem:orchestrator_1",
            tool_id="calc",
            invocation_sha256="0" * 64,
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
            trace_id=request.context.trace_id,
            plan_id=None,
            approval_scope=("tool:calc",),
        )
        exec_res = ExecutionResult(
            answer="paused for approval",
            route=B14RouteMetadata(selected_provider="mock", selected_model="mock"),
            metadata=RunMetadata(
                trace_id=request.context.trace_id,
                app_id="b62",
                agent_id=request.execution_request.agent.id,
                status=RunStatus.PAUSED,
            ),
        )
        return OrchestrationResult(
            execution_result=exec_res,
            context=request.context,
            app_id=request.app_id,
            subject_id=request.subject_id,
            plan=request.agent_plan,
            activated_skill=None,
            resolved_tool_ids=(),
            evidence_graph=None,
            claim_assessments=(),
            grounded_citations=(),
            events=(),
            approval_pause=pause,
        )

    async def resume(self, request) -> OrchestrationResult:
        if type(self).fail_next is not None:
            code = type(self).fail_next
            type(self).fail_next = None
            raise OrchestrationError(code, "injected resume failure")
        type(self).resume_count += 1
        if type(self).pause_again:
            now = datetime.now(timezone.utc)
            pause = ApprovalPause(
                pause_id="pause_flow_2",
                run_id="run_flow_1",
                agent_runtime_id="agent:padiem:orchestrator_1",
                tool_id="calc2",
                invocation_sha256="1" * 64,
                requirement=ApprovalRequirement.USER_CONFIRMATION,
                step_index=2,
                created_at=now,
                expires_at=now + timedelta(minutes=10),
                trace_id=request.context.trace_id,
                plan_id=None,
                approval_scope=("tool:calc2",),
            )
            exec_res = ExecutionResult(
                answer="paused again",
                route=B14RouteMetadata(selected_provider="mock", selected_model="mock"),
                metadata=RunMetadata(
                    trace_id=request.context.trace_id,
                    app_id="b62",
                    agent_id=request.execution_request.agent.id,
                    status=RunStatus.PAUSED,
                ),
            )
            return OrchestrationResult(
                execution_result=exec_res,
                context=request.context,
                app_id=request.app_id,
                subject_id=request.subject_id,
                plan=request.agent_plan,
                activated_skill=None,
                resolved_tool_ids=(),
                evidence_graph=None,
                claim_assessments=(),
                grounded_citations=(),
                events=(),
                approval_pause=pause,
            )
        exec_res = ExecutionResult(
            answer="resumed",
            route=B14RouteMetadata(selected_provider="mock", selected_model="mock"),
            metadata=RunMetadata(
                trace_id=request.context.trace_id,
                app_id="b62",
                agent_id=request.execution_request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )
        return OrchestrationResult(
            execution_result=exec_res,
            context=request.context,
            app_id=request.app_id,
            subject_id=request.subject_id,
            plan=request.agent_plan,
            activated_skill=None,
            resolved_tool_ids=(),
            evidence_graph=None,
            claim_assessments=(),
            grounded_citations=(),
            events=(),
            approval_pause=None,
        )


@pytest.fixture
def patch_runner(monkeypatch):
    PausingRunner.resume_count = 0
    PausingRunner.fail_next = None
    PausingRunner.pause_again = False
    monkeypatch.setattr(ident_mod, "OrchestrationRunner", PausingRunner)
    monkeypatch.setattr(adm_mod, "OrchestrationRunner", PausingRunner)
    return PausingRunner


class DualAdapter:
    """Trusted server adapter: run and resume decisions bound to the request."""

    def __init__(
        self,
        *,
        resume_allowed: bool = True,
        resume_policy: str = "policy:resume:1",
        resume_authority: str = "control-plane:entitlement:resume",
        resume_fingerprint_override: str | None = None,
    ) -> None:
        self.calls: list = []
        self.resume_allowed = resume_allowed
        self.resume_policy = resume_policy
        self.resume_authority = resume_authority
        self.resume_fingerprint_override = resume_fingerprint_override

    def resolve_admission(self, request):
        self.calls.append(request)
        now = datetime.now(timezone.utc)
        if request.capability == "orchestration.run":
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
        fingerprint = (
            self.resume_fingerprint_override
            if self.resume_fingerprint_override is not None
            else request.request_fingerprint
        )
        return TrustedExecutionAdmission(
            decision_id="adm_resume_1",
            app_id=request.app_id,
            subject_id=request.subject_id,
            capability=request.capability,
            allowed=self.resume_allowed,
            authority_ref=self.resume_authority,
            policy_revision=self.resume_policy,
            issued_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
            request_fingerprint=fingerprint,
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
        "session_id": "session:admission_flow_1",
        "additional_system_context": "Trusted product context",
        "trace_id": "tr_admission_flow",
        "execution_context": {
            "trace_id": "tr_admission_flow",
            "timeout_seconds": 15.0,
        },
        "subject_id": "subject:owner",
        "max_retries": 2,
        "require_evidence": False,
        "require_verification": False,
    }


def _service(adapter, store=None):
    store = store or InMemoryIdentityBoundContinuationStore()
    service = AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: object(),
        b14_service_bound=True,
        admission_adapter=adapter,
        continuation_store=store,
        approval_decision_verifier=Verifier(),
    )
    return service, store


def _decision(pause_id: str = "pause_flow_1") -> dict:
    return {
        "decision_id": "dec_flow_1",
        "pause_id": pause_id,
        "outcome": "approved",
        "authority_ref": "user:admin",
        "evidence_ref": "session:auth",
        "decided_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }


async def _run_to_pause(service, payload=None):
    response = await service.orchestrate_payload(payload or _payload())
    assert response.status_code == 200
    ref = response.body["orchestration"].get("continuation_ref")
    assert isinstance(ref, str) and ref.startswith("cont_")
    return ref


async def test_valid_run_admission_travels_into_pause_continuation(patch_runner) -> None:
    adapter = DualAdapter()
    service, store = _service(adapter)

    ref = await _run_to_pause(service)

    assert len(adapter.calls) == 1
    run_request = adapter.calls[0]
    assert run_request.capability == "orchestration.run"
    assert run_request.app_id == "b62"
    assert run_request.subject_id == "subject:owner"

    record = store.resolve(app_id="b62", continuation_ref=ref)
    binding = record.original_admission
    assert binding is not None
    assert binding.decision_id == "adm_run_1"
    assert binding.authority_ref == "control-plane:entitlement:run"
    assert binding.policy_revision == "policy:run:1"
    assert binding.app_id == "b62"
    assert binding.subject_id == "subject:owner"
    assert binding.request_fingerprint == run_request.request_fingerprint
    assert len(binding.request_fingerprint) == 64


async def test_client_cannot_provide_original_admission(patch_runner) -> None:
    adapter = DualAdapter()
    service, _ = _service(adapter)
    payload = _payload()
    payload["original_admission"] = {"decision_id": "adm_forged"}

    response = await service.orchestrate_payload(payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "unsupported_orchestration_field"
    assert adapter.calls == []


@pytest.mark.parametrize(
    "field",
    ["entitlement", "allow", "plan", "credit_balance", "credit"],
)
async def test_client_entitlement_fields_rejected_before_admission_lookup(
    patch_runner, field
) -> None:
    adapter = DualAdapter()
    service, _ = _service(adapter)
    payload = _payload()
    payload[field] = {"allow": True} if field not in ("allow",) else True

    response = await service.orchestrate_payload(payload)

    assert response.status_code == 400
    assert adapter.calls == []


async def test_resume_lookup_uses_server_derived_identity_only(patch_runner) -> None:
    adapter = DualAdapter()
    service, store = _service(adapter)
    ref = await _run_to_pause(service)

    resume = _payload()
    resume["continuation_ref"] = ref
    resume["decision"] = _decision()
    # Client-shaped authority must be ignored: unknown fields are rejected and
    # the trusted lookup still uses only server-parsed app/subject/fingerprint.
    response = await service.resume_payload(resume)

    assert response.status_code == 200
    assert len(adapter.calls) == 2
    resume_request = adapter.calls[1]
    assert resume_request.capability == "orchestration.resume"
    assert resume_request.app_id == "b62"
    assert resume_request.subject_id == "subject:owner"
    assert resume_request.request_fingerprint == adapter.calls[0].request_fingerprint


async def test_valid_resume_executes_core_exactly_once(patch_runner) -> None:
    adapter = DualAdapter()
    service, store = _service(adapter)
    ref = await _run_to_pause(service)

    resume = _payload()
    resume["continuation_ref"] = ref
    resume["decision"] = _decision()

    PausingRunner.resume_count = 0
    response = await service.resume_payload(resume)

    assert response.status_code == 200
    assert PausingRunner.resume_count == 1
    with pytest.raises(Exception) as excinfo:
        store.resolve(app_id="b62", continuation_ref=ref)
    assert getattr(excinfo.value, "code", None) == "continuation_consumed"


async def test_missing_original_admission_fails_closed_before_claim(patch_runner) -> None:
    adapter = DualAdapter()
    service, store = _service(adapter)

    payload = _payload()
    _, exec_req, ctx = build_execution_request(
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
    assert ctx is not None
    identity = build_continuation_execution_identity(
        app_id="b62",
        request=exec_req,
        context=ctx,
        subject_id="subject:owner",
        plan=None,
        recovery_policy=None,
        max_retries=2,
        require_evidence=False,
        require_verification=False,
    )
    now = datetime.now(timezone.utc)
    pause = ApprovalPause(
        pause_id="pause_flow_1",
        run_id="run_flow_1",
        agent_runtime_id="agent:padiem:orchestrator_1",
        tool_id="calc",
        invocation_sha256="0" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        trace_id=ctx.trace_id,
    )
    ref = store.issue(app_id="b62", pause=pause, execution_identity=identity)

    resume = _payload()
    resume["continuation_ref"] = ref
    resume["decision"] = _decision()

    PausingRunner.resume_count = 0
    response = await service.resume_payload(resume)

    assert response.status_code == 403
    assert response.body["error"]["code"] == "missing_entitlement"
    assert PausingRunner.resume_count == 0
    record = store.resolve(app_id="b62", continuation_ref=ref)
    assert record.state == "active"
    assert record.claim_token is None


async def test_revoked_current_admission_fails_before_claim(patch_runner) -> None:
    adapter = DualAdapter(resume_allowed=False)
    service, store = _service(adapter)
    ref = await _run_to_pause(service)

    resume = _payload()
    resume["continuation_ref"] = ref
    resume["decision"] = _decision()

    PausingRunner.resume_count = 0
    response = await service.resume_payload(resume)

    assert response.status_code == 403
    assert response.body["error"]["code"] == "entitlement_denied"
    assert PausingRunner.resume_count == 0
    record = store.resolve(app_id="b62", continuation_ref=ref)
    assert record.state == "active"
    assert record.claim_token is None


async def test_newer_policy_revision_with_same_execution_is_allowed(patch_runner) -> None:
    adapter = DualAdapter(resume_policy="policy:expanded:2")
    service, store = _service(adapter)
    ref = await _run_to_pause(service)
    original = store.resolve(app_id="b62", continuation_ref=ref).original_admission
    assert original is not None and original.policy_revision == "policy:run:1"

    resume = _payload()
    resume["continuation_ref"] = ref
    resume["decision"] = _decision()

    PausingRunner.resume_count = 0
    response = await service.resume_payload(resume)

    assert response.status_code == 200
    assert PausingRunner.resume_count == 1


async def test_wider_authority_cannot_widen_paused_execution(patch_runner) -> None:
    adapter = DualAdapter(
        resume_policy="policy:expanded:99",
        resume_authority="control-plane:entitlement:expanded",
    )
    service, store = _service(adapter)
    ref = await _run_to_pause(service)
    before = store.resolve(app_id="b62", continuation_ref=ref)
    assert before.original_admission is not None

    PausingRunner.pause_again = True
    try:
        resume = _payload()
        resume["continuation_ref"] = ref
        resume["decision"] = _decision()
        response = await service.resume_payload(resume)
    finally:
        PausingRunner.pause_again = False

    assert response.status_code == 200
    second_ref = response.body["orchestration"].get("continuation_ref")
    assert isinstance(second_ref, str)
    after = store.resolve(app_id="b62", continuation_ref=second_ref)
    # The paused work remains bound to the original admitted execution.
    assert after.original_admission == before.original_admission


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.__setitem__("subject_id", "subject:other"),
        lambda p: p.__setitem__("app_id", "b62_other"),
        lambda p: p["messages"].__setitem__(0, {"role": "user", "content": "Changed"}),
    ],
)
async def test_app_subject_fingerprint_mutation_fails_before_claim(patch_runner, mutate) -> None:
    adapter = DualAdapter()
    service, store = _service(adapter)
    ref = await _run_to_pause(service)
    calls_after_run = len(adapter.calls)

    resume = _payload()
    mutate(resume)
    resume["continuation_ref"] = ref
    # app mismatch resolves against the wrong app namespace on purpose.
    app_id = resume.get("app_id", "b62")
    resume["decision"] = _decision()

    PausingRunner.resume_count = 0
    response = await service.resume_payload(resume)

    assert response.status_code in (403, 409)
    assert PausingRunner.resume_count == 0
    if app_id == "b62":
        # Same-app mutations must leave the stored continuation ACTIVE.
        record = store.resolve(app_id="b62", continuation_ref=ref)
        assert record.state == "active"
        assert record.claim_token is None
    else:
        # Cross-app mismatch must not touch the original continuation.
        record = store.resolve(app_id="b62", continuation_ref=ref)
        assert record.state == "active"
    # Mutations fail at identity/resolve before a fresh resume lookup, or at
    # the non-widening gate without ever reaching Core.
    assert len(adapter.calls) <= calls_after_run + 1


async def test_failed_resume_preserves_claim_release_semantics(patch_runner) -> None:
    adapter = DualAdapter()
    service, store = _service(adapter)
    ref = await _run_to_pause(service)

    resume = _payload()
    resume["continuation_ref"] = ref
    resume["decision"] = _decision()

    PausingRunner.fail_next = "transient_failure"
    PausingRunner.resume_count = 0
    response = await service.resume_payload(resume)

    assert response.status_code == 422
    assert PausingRunner.resume_count == 0
    record = store.resolve(app_id="b62", continuation_ref=ref)
    assert record.state == "active"
    assert record.claim_token is None
