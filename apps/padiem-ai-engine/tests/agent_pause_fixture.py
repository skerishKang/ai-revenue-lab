"""Paused-run fixture: a genuine Core approval pause plus Engine wiring.

Every continuation lifecycle case needs the same basis — a real approval pause
produced by Core, not a hand-made record — so the scenario lives here once and is
reused by the resume and cancel contract tests (#2786 S13-4 Phase 2).

It is a test support module, not a test file: no ``test_`` prefix, no assertions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from padiem_ai_core.agent_approval import ApprovalOutcome, VerifiedApprovalDecision
from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

from app.agent_skill_authority import (
    EngineAgentSkillBinding,
    build_agent_skill_binding_resolver,
)
from app.agent_skill_service import AgentSkillEngineService
from app.orchestration_continuation import InMemoryContinuationStore
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

APP_ID = "s13pause"
SUBJECT_ID = "actor:s13-pause"
AGENT_ID = "agent:core:pause@1"
CANONICAL_TOOL = "tool:core:pause-write@1"
RUNTIME_TOOL = "pause-write.tool"
REQUIRED_CAPABILITY = "agent_task_execution"
OUTPUT_CONTRACT_REF = "output:pause@1"


class NoProviderRuntime:
    """Provider-free sentinel: a paused write never calls the provider."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _request: Any) -> Any:
        self.calls += 1
        raise AssertionError("the paused-run fixture must not call a provider runtime")


class ToolCallRecorder:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _arguments: Any) -> dict[str, Any]:
        self.calls += 1
        return {"written": True}


class DecisionVerifierStub:
    """Mirrors the submitted decision, as a trusted control plane would."""

    def __init__(self) -> None:
        self.verifications = 0

    def verify(self, submission: Any, *, pause: Any, app_id: str) -> VerifiedApprovalDecision:
        self.verifications += 1
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


def _binding(
    *, app_id: str = APP_ID, subject_id: str = SUBJECT_ID, pre_confirmed: bool = False
) -> EngineAgentSkillBinding:
    tool_runtime = ToolRuntime()
    spec = ToolSpec(
        id=RUNTIME_TOOL,
        title="Continuation write",
        description="Write tool that requires user confirmation",
        owner="core",
        side_effect=ToolSideEffect.WRITE,
        approval_policy=ApprovalPolicy.USER_CONFIRMATION,
        input_schema={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
            "additionalProperties": False,
        },
        timeout_seconds=5,
    )
    tool_runtime.register(spec, ToolCallRecorder())
    registry = ToolRegistrySnapshot.from_entries(
        (RegisteredTool.from_spec(canonical_tool_id=CANONICAL_TOOL, runtime_spec=spec),)
    )
    definition = BoundedAgentDefinition(
        agent_id=AGENT_ID,
        publisher_id="core",
        title="Paused continuation agent",
        description="Agent whose only step needs user confirmation",
        instruction="Execute the confirmation-gated write.",
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
    # The trusted control plane, not the fixture, owns the approval delta: a run
    # with no confirmation pauses; the same tool appears in user_confirmed_tools
    # only when the control plane decided. That models the resume precondition.
    # Core matches ``pause.tool_id`` (the runtime tool id) against this tuple, so
    # the trusted control plane confirms the runtime tool, not the canonical id.
    authorization = ToolAuthorizationContext(
        app_id=app_id,
        agent_id=compiled.runtime_profile.id,
        user_confirmed_tools=(RUNTIME_TOOL,) if pre_confirmed else (),
    )
    authority = TrustedToolAuthority(
        canonical_agent_id=AGENT_ID,
        definition=definition,
        compiled=compiled,
        authorization=authorization,
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


class PausedRunFixture:
    """Run once into an approval pause, then drive resume/cancel from that state."""

    def __init__(self) -> None:
        self.store = InMemoryContinuationStore()
        self.verifier = DecisionVerifierStub()
        self.runtime = NoProviderRuntime()
        self.pre_confirmed = False
        self.binding = _binding(pre_confirmed=False)
        self.service = AgentSkillEngineService(
            runtime_factory=lambda _app_id: self.runtime,
            binding_resolver=lambda requested: _binding(
                pre_confirmed=self.pre_confirmed
            )
            if requested == APP_ID
            else None,
            approval_decision_verifier=self.verifier,
            continuation_store=self.store,
        )

    # -- request builders -------------------------------------------------

    def run_payload(self) -> dict[str, Any]:
        return {
            "app_id": APP_ID,
            "agent_id": AGENT_ID,
            "messages": [{"role": "user", "content": "write something"}],
            "agent_plan": {
                "agent_id": AGENT_ID,
                "steps": [
                    {
                        "step_id": "write",
                        "objective": "Run the confirmation-gated write",
                        "tool_id": RUNTIME_TOOL,
                    }
                ],
            },
            "tool_arguments": {"write": {"target": "fixture"}},
        }

    def decision(self, *, pause_id: str, outcome: ApprovalOutcome = ApprovalOutcome.APPROVED) -> dict[str, Any]:
        return {
            "decision_id": "decision_fixture_1",
            "pause_id": pause_id,
            "outcome": outcome.value,
            "authority_ref": "authority_fixture_1",
            "evidence_ref": "evidence_fixture_1",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }

    def resume_payload(self, continuation_ref: str, pause_id: str, **overrides: Any) -> dict[str, Any]:
        payload = self.run_payload()
        payload["continuation_ref"] = continuation_ref
        payload["decision"] = self.decision(pause_id=pause_id)
        payload.update(overrides)
        return payload

    def cancel_payload(self, continuation_ref: str, reason: str = "user_cancelled") -> dict[str, Any]:
        return {
            "app_id": APP_ID,
            "continuation_ref": continuation_ref,
            "reason": reason,
        }
