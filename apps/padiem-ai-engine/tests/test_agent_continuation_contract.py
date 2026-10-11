"""Continuation contract tests (#2786 S13-4 Phase 1, Resume).

Coverage in this file:

  * projection contract: the continuation block a resumed run publishes (fields,
    sources, what must never be exposed)
  * coordinator guards that fail *before* Core resume: unavailable store, missing
    identity, malformed decision, decision/continuation mismatch

A genuine Core approval pause (happy-path resume, completed-task resume, duplicate
resume, invalid transition) needs a real paused run; those are tracked as remaining
work rather than asserted here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
)
from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

import app.agent_skill_service as skill_service_module
from app.agent_skill_authority import (
    EngineAgentSkillBinding,
    build_agent_skill_binding_resolver,
)
from app.agent_skill_continuation_projection import (
    ENGINE_AGENT_CONTINUATION_CONTRACT_VERSION,
    project_agent_continuation_result,
)
from app.agent_skill_continuation_service import AgentSkillContinuationCoordinator
from app.agent_skill_projection import project_agent_skill_result
from app.agent_skill_service import AgentSkillEngineService
from app.orchestration_continuation import ContinuationRecord
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from agent_pause_fixture import SUBJECT_ID as PAUSED_SUBJECT_ID  # noqa: E402
from agent_pause_fixture import PausedRunFixture  # noqa: E402

APP_ID = "s13cont"
SUBJECT_ID = "actor:s13-cont"
OTHER_SUBJECT_ID = "actor:s13-other"
AGENT_ID = "agent:core:cont@1"
CANONICAL_TOOL = "tool:core:cont-read@1"
RUNTIME_TOOL = "cont-read.tool"
REQUIRED_CAPABILITY = "agent_task_execution"
OUTPUT_CONTRACT_REF = "output:cont@1"
CONTINUATION_REF = "cont_ref_0123456789abcdef"
PAUSE_ID = "pause_0123456789abcdef"
RUN_ID = "orch_run_0123456789abcdef"
TRACE_ID = "agtr_0123456789abcdef01234567"


class NoProviderRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _request: Any) -> Any:
        self.calls += 1
        raise AssertionError("the continuation test must not call a provider runtime")


class _ToolProxy:
    async def __call__(self, _arguments: Any) -> dict[str, Any]:
        return {"probe": "ok"}


class _Verifier:
    def verify(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the guard tests never reach approval verification")


class _Store:
    """Minimal store surface: only what the guard tests need."""

    def __init__(self, record: ContinuationRecord | None) -> None:
        self._record = record
        self.calls: list[str] = []

    def issue(self, **_kwargs: Any) -> str:  # pragma: no cover - not used here
        raise AssertionError("issue is not exercised in the guard tests")

    def resolve(self, **_kwargs: Any) -> ContinuationRecord:
        self.calls.append("resolve")
        if self._record is None:
            raise RuntimeError("no continuation")
        return self._record

    def claim(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("claim must not be reached in the guard tests")

    def commit(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("commit must not be reached in the guard tests")

    def release(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("release must not be reached in the guard tests")

    # Present so the coordinator recognises atomic cancellation; the unsupported
    # field check must then run before any of these are reached.
    def claim_cancel(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("claim_cancel must not be reached for a rejected payload")

    def commit_cancel(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("commit_cancel must not be reached for a rejected payload")

    def release_cancel(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("release_cancel must not be reached for a rejected payload")


def _pause(*, pause_id: str = PAUSE_ID, trace_id: str | None = TRACE_ID) -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id=pause_id,
        run_id=RUN_ID,
        agent_runtime_id=AGENT_ID,
        tool_id=CANONICAL_TOOL,
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        trace_id=trace_id,
        plan_id=None,
        approval_scope=(),
    )


def _record(*, pause_id: str = PAUSE_ID, state: str = "active") -> ContinuationRecord:
    return ContinuationRecord(
        app_id=APP_ID,
        pause=_pause(pause_id=pause_id),
        continuation_ref=CONTINUATION_REF,
        plan_id=None,
        state=state,
    )


def _binding(app_id: str = APP_ID, subject_id: str = SUBJECT_ID) -> EngineAgentSkillBinding:
    tool_runtime = ToolRuntime()
    spec = ToolSpec(
        id=RUNTIME_TOOL,
        title="Continuation read",
        description="Deterministic read tool",
        owner="core",
        side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        timeout_seconds=5,
    )
    tool_runtime.register(spec, _ToolProxy())
    registry = ToolRegistrySnapshot.from_entries(
        (RegisteredTool.from_spec(canonical_tool_id=CANONICAL_TOOL, runtime_spec=spec),)
    )
    definition = BoundedAgentDefinition(
        agent_id=AGENT_ID,
        publisher_id="core",
        title="Continuation agent",
        description="Bounded agent for continuation contract tests",
        instruction="Execute the bounded read step.",
        output_contract_ref=OUTPUT_CONTRACT_REF,
        skill_package_ids=(),
        allowed_tool_ids=(CANONICAL_TOOL,),
        required_capabilities=(REQUIRED_CAPABILITY,),
        execution_budget=AgentExecutionBudget(max_steps=2, max_tool_calls=1, max_skill_calls=0),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref=OUTPUT_CONTRACT_REF,
        task_type="general",
        optimize_for="balanced",
        max_tokens=256,
        max_steps_cap=2,
        context_policy={},
        model_policy={},
        output_contract={},
        available_capabilities=frozenset({REQUIRED_CAPABILITY}),
        tool_bindings=(ToolRuntimeBinding(CANONICAL_TOOL, RUNTIME_TOOL),),
    )
    compiled = compile_agent_profile(definition, policy)
    authority = TrustedToolAuthority(
        canonical_agent_id=AGENT_ID,
        definition=definition,
        compiled=compiled,
        authorization=ToolAuthorizationContext(
            app_id=app_id,
            agent_id=compiled.runtime_profile.id,
        ),
    )
    return EngineAgentSkillBinding(
        app_id=app_id,
        subject_id=subject_id,
        tool_binding=EngineToolBinding(
            app_id=app_id,
            tool_runtime=tool_runtime,
            registry=registry,
            authorities={AGENT_ID: authority},
        ),
    )


def _run_payload() -> dict[str, Any]:
    return {
        "app_id": APP_ID,
        "agent_id": AGENT_ID,
        "messages": [{"role": "user", "content": "bounded task"}],
        "agent_plan": {
            "agent_id": AGENT_ID,
            "steps": [
                {"step_id": "read", "objective": "Run the bounded read", "tool_id": RUNTIME_TOOL}
            ],
        },
        "tool_arguments": {"read": {"query": "bounded"}},
    }


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _capture_result_and_selection(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Run one agent task and capture the real (result, selection) pair."""

    captured: dict[str, Any] = {}
    original = skill_service_module.project_agent_skill_result

    def _capture(result: Any, *, selection: Any) -> dict[str, Any]:
        captured["result"] = result
        captured["selection"] = selection
        return original(result, selection=selection)

    monkeypatch.setattr(skill_service_module, "project_agent_skill_result", _capture)
    runtime = NoProviderRuntime()
    service = AgentSkillEngineService(
        runtime_factory=lambda _app_id: runtime,
        binding_resolver=lambda requested: _binding() if requested == APP_ID else None,
    )
    response = _run(service.run_payload(_run_payload()))
    assert response.status_code == 200, response.body
    captured["runtime"] = runtime
    return captured


# --- T1 contract fields ---------------------------------------------------


def test_continuation_contract_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_result_and_selection(monkeypatch)

    block = project_agent_continuation_result(
        captured["result"],
        selection=captured["selection"],
        record=_record(),
        approval_delta_applied=True,
    )

    assert block["continuation_contract_version"] == ENGINE_AGENT_CONTINUATION_CONTRACT_VERSION
    assert block["continuation_id"] == CONTINUATION_REF
    assert block["task_id"] == RUN_ID
    assert block["owner_identity"] == {"subject_id": SUBJECT_ID}
    assert block["current_state"] == "active"
    assert block["resume_target_state"] == "completed"
    assert block["resume_authority"] == {
        "approval_delta_applied": True,
        "capability_required": [REQUIRED_CAPABILITY],
    }
    assert block["audit_event"]["trace_id"] == TRACE_ID
    assert block["audit_event"]["event_count"] >= 1
    assert isinstance(block["audit_event"]["terminal_kind"], str)


def test_continuation_contract_uses_trusted_owner_not_other_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_result_and_selection(monkeypatch)
    selection = captured["selection"]

    block = project_agent_continuation_result(
        captured["result"],
        selection=selection,
        record=_record(),
        approval_delta_applied=True,
    )

    # Owner comes from the binding the Engine resolved, never from a request field.
    assert block["owner_identity"]["subject_id"] == selection.subject_id
    assert OTHER_SUBJECT_ID not in repr(block)


# --- T2 backward compatibility -------------------------------------------


def test_task_contract_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_result_and_selection(monkeypatch)

    task_block = project_agent_skill_result(
        captured["result"], selection=captured["selection"]
    )

    assert task_block["task_id"] == RUN_ID or task_block["task_id"].startswith("orch_run_")
    assert task_block["owner_identity"] == {"subject_id": SUBJECT_ID}
    assert task_block["execution_status"] == "completed"
    assert "continuation_id" not in task_block


# --- T9 authority summary -------------------------------------------------


def test_authority_summary_exposes_no_authority_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_result_and_selection(monkeypatch)

    block = project_agent_continuation_result(
        captured["result"],
        selection=captured["selection"],
        record=_record(),
        approval_delta_applied=True,
    )

    assert set(block["resume_authority"]) == {"approval_delta_applied", "capability_required"}
    serialized = repr(block)
    for forbidden in (
        "claim_token",
        "decision_id",
        "evidence_ref",
        "invocation_sha256",
        "request_fingerprint",
        "authorization_source",
        "caller",
    ):
        assert forbidden not in serialized


def test_approval_delta_flag_reflects_the_caller_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_result_and_selection(monkeypatch)

    block = project_agent_continuation_result(
        captured["result"],
        selection=captured["selection"],
        record=_record(),
        approval_delta_applied=False,
    )

    assert block["resume_authority"]["approval_delta_applied"] is False


# --- T10 schema / input guards -------------------------------------------


def test_projection_rejects_non_core_inputs() -> None:
    with pytest.raises(TypeError):
        project_agent_continuation_result(
            "not a result", selection="not a selection", record="not a record",
            approval_delta_applied=True,
        )


# --- T11 provider independence -------------------------------------------


def test_continuation_projection_is_provider_free(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_result_and_selection(monkeypatch)

    project_agent_continuation_result(
        captured["result"],
        selection=captured["selection"],
        record=_record(),
        approval_delta_applied=True,
    )

    assert captured["runtime"].calls == 0


# --- coordinator guards (fail before Core resume) ------------------------


def _coordinator(
    *, store: Any, verifier: Any = None, binding: EngineAgentSkillBinding | None = None
) -> AgentSkillContinuationCoordinator:
    runtime = NoProviderRuntime()
    resolved = binding or _binding()
    return AgentSkillContinuationCoordinator(
        runtime_factory=lambda _app_id: runtime,
        binding_resolver=lambda _requested: resolved,
        approval_decision_verifier=verifier or _Verifier(),
        continuation_store=store,
        idempotency_adapter=None,
    )


def test_store_unavailable_fails_closed() -> None:
    coordinator = _coordinator(store=None)

    response = _run(
        coordinator.resume_payload(
            {"app_id": APP_ID, "continuation_ref": CONTINUATION_REF, "decision": {}}
        )
    )

    assert response.status_code == 503
    assert response.body["error"]["code"] == "continuation_store_unavailable"


def test_missing_app_id_is_invalid_request() -> None:
    coordinator = _coordinator(store=_Store(_record()))

    response = _run(coordinator.resume_payload({"continuation_ref": CONTINUATION_REF}))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"


def test_unknown_continuation_fails_closed() -> None:
    coordinator = _coordinator(store=_Store(None))

    response = _run(
        coordinator.resume_payload(
            {"app_id": APP_ID, "continuation_ref": CONTINUATION_REF, "decision": {}}
        )
    )

    assert response.status_code == 503
    assert response.body["error"]["code"] == "continuation_store_unavailable"


def test_malformed_decision_is_rejected() -> None:
    coordinator = _coordinator(store=_Store(_record()))

    response = _run(
        coordinator.resume_payload(
            {
                "app_id": APP_ID,
                "continuation_ref": CONTINUATION_REF,
                "decision": {"decision_id": "d1"},
            }
        )
    )

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_decision"


def test_decision_for_another_continuation_is_rejected() -> None:
    coordinator = _coordinator(store=_Store(_record()))
    now = datetime.now(timezone.utc).isoformat()
    decision = {
        "decision_id": "decision_1",
        "pause_id": "pause_deadbeefdeadbeef",
        "outcome": ApprovalOutcome.APPROVED.value,
        "authority_ref": "authority_1",
        "evidence_ref": "evidence_1",
        "decided_at": now,
    }

    response = _run(
        coordinator.resume_payload(
            {"app_id": APP_ID, "continuation_ref": CONTINUATION_REF, "decision": decision}
        )
    )

    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_identity_mismatch"


def test_cancel_rejects_unsupported_fields() -> None:
    coordinator = _coordinator(store=_Store(_record()))

    response = _run(
        coordinator.cancel_payload(
            {
                "app_id": APP_ID,
                "continuation_ref": CONTINUATION_REF,
                "reason": "user_cancelled",
                "extra": "not allowed",
            }
        )
    )

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"


# --- paused-run lifecycle (S13-4 Phase 2 fixture) -------------------------


def _pause_run(fixture: PausedRunFixture) -> tuple[str, str]:
    response = _run(fixture.service.run_payload(fixture.run_payload()))
    assert response.status_code == 202, response.body
    ref = response.body["continuation_ref"]
    pause_id = response.body["agent_skill"]["approval_pause"]["continuation_id"]
    return ref, pause_id


def test_paused_run_publishes_a_continuation_reference() -> None:
    fixture = PausedRunFixture()

    response = _run(fixture.service.run_payload(fixture.run_payload()))

    assert response.status_code == 202
    assert response.body["continuation_ref"].startswith("cont_")
    pause = response.body["agent_skill"]["approval_pause"]
    assert pause["status"] == "paused"
    assert pause["requirement"] == "user_confirmation"
    assert "continuation_id" in pause


def test_resume_happy_path_publishes_the_continuation_contract() -> None:
    fixture = PausedRunFixture()
    ref, pause_id = _pause_run(fixture)
    fixture.pre_confirmed = True

    response = _run(fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)))

    assert response.status_code == 200, response.body
    block = response.body["continuation"]
    assert block["continuation_id"] == ref
    assert block["owner_identity"] == {"subject_id": PAUSED_SUBJECT_ID}
    assert block["current_state"] == "active"
    assert block["resume_target_state"] == "completed"
    assert block["resume_authority"]["approval_delta_applied"] is True
    assert response.body["agent_skill"]["task_id"] == block["task_id"]


def test_resume_without_the_trusted_delta_is_refused() -> None:
    fixture = PausedRunFixture()
    ref, pause_id = _pause_run(fixture)
    fixture.pre_confirmed = False

    response = _run(fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)))

    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_authority_mismatch"
    assert "continuation" not in response.body


def test_duplicate_resume_is_refused() -> None:
    fixture = PausedRunFixture()
    ref, pause_id = _pause_run(fixture)
    fixture.pre_confirmed = True
    first = _run(fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)))
    assert first.status_code == 200

    second = _run(fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)))

    assert second.status_code == 409
    assert second.body["error"]["code"] == "continuation_consumed"
