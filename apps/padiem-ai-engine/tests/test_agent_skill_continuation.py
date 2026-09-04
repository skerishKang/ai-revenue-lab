"""Focused E4B conformance for server-issued Agent/Skill continuation (#1749)."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from padiem_ai_core.agent_approval import VerifiedApprovalDecision
from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep
from padiem_ai_core.agent_profile_adapter import ToolRuntimeBinding, TrustedAgentRuntimePolicy, compile_agent_profile
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

from app.agent_skill_authority import EngineAgentSkillBinding
from app.agent_skill_service import AgentSkillEngineService
from app.orchestration_continuation import InMemoryContinuationStore
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

APP_ID = "e4continuation"
SUBJECT_ID = "user_1749"
AGENT_ID = "agent:acme:approval@1"
CANONICAL_TOOL = "tool:acme:confirm@1"
RUNTIME_TOOL = "confirm.tool"
PRIVATE_ARGUMENT = "PRIVATE-CONTINUATION-ARG-1749"
PRIVATE_OUTPUT = "PRIVATE-CONTINUATION-OUTPUT-1749"


class NoProviderRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request):
        self.calls += 1
        raise AssertionError("E4B Tool plan must not call Provider/B14 runtime")


class EchoTrustedVerifier:
    def __init__(self) -> None:
        self.calls = 0

    async def verify(self, submission, *, pause, app_id):
        self.calls += 1
        assert app_id == APP_ID
        assert submission.pause_id == pause.pause_id
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


class ContinuationFixture:
    def __init__(self, *, with_continuation: bool = True) -> None:
        self.handler_calls = 0
        self.provider = NoProviderRuntime()
        self.verifier = EchoTrustedVerifier()
        self.store = InMemoryContinuationStore()
        self.tool_runtime = ToolRuntime()

        spec = ToolSpec(
            id=RUNTIME_TOOL,
            title="Confirmation Tool",
            description="Network-free approval continuation fixture",
            owner="core",
            side_effect=ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.USER_CONFIRMATION,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            timeout_seconds=5,
        )

        async def handler(arguments: dict) -> dict:
            self.handler_calls += 1
            assert arguments == {"query": PRIVATE_ARGUMENT}
            return {"ok": True, "private_output": PRIVATE_OUTPUT, "api_key": "sk-continuation-secret"}

        self.tool_runtime.register(spec, handler)
        self.registry = ToolRegistrySnapshot.from_entries(
            (RegisteredTool.from_spec(canonical_tool_id=CANONICAL_TOOL, runtime_spec=spec),)
        )
        self.definition = BoundedAgentDefinition(
            agent_id=AGENT_ID,
            publisher_id="publisher:acme",
            title="Approval Agent",
            description="Trusted continuation Agent fixture",
            instruction="Use only server-authorized Tool runtime.",
            output_contract_ref="io:approval@1",
            allowed_tool_ids=(CANONICAL_TOOL,),
            execution_budget=AgentExecutionBudget(max_steps=2, max_tool_calls=1, max_skill_calls=1, max_wall_seconds=20),
        )
        policy = TrustedAgentRuntimePolicy(
            context_policy_ref="context:default",
            model_policy_ref="model:auto",
            output_contract_ref="io:approval@1",
            task_type="general",
            optimize_for="balanced",
            max_tokens=512,
            max_steps_cap=2,
            context_policy={},
            model_policy={},
            output_contract={},
            tool_bindings=(ToolRuntimeBinding(canonical_tool_id=CANONICAL_TOOL, runtime_tool_id=RUNTIME_TOOL),),
        )
        self.compiled = compile_agent_profile(self.definition, policy)
        self.plan = AgentPlan(
            agent_id=AGENT_ID,
            steps=(AgentPlanStep(step_id="confirm1", objective="private planner objective must not project", tool_id=RUNTIME_TOOL),),
        )
        self.current_binding = self._binding(user_confirmed=())
        self.service = AgentSkillEngineService(
            runtime_factory=lambda app_id: self.provider,
            binding_resolver=lambda app_id: self.current_binding if app_id == APP_ID else None,
            approval_decision_verifier=self.verifier if with_continuation else None,
            continuation_store=self.store if with_continuation else None,
        )

    def _binding(self, *, user_confirmed: tuple[str, ...]) -> EngineAgentSkillBinding:
        authority = TrustedToolAuthority(
            canonical_agent_id=AGENT_ID,
            definition=self.definition,
            compiled=self.compiled,
            authorization=ToolAuthorizationContext(
                app_id=APP_ID,
                agent_id=self.compiled.runtime_profile.id,
                user_confirmed_tools=user_confirmed,
            ),
        )
        return EngineAgentSkillBinding(
            app_id=APP_ID,
            subject_id=SUBJECT_ID,
            tool_binding=EngineToolBinding(
                app_id=APP_ID,
                tool_runtime=self.tool_runtime,
                registry=self.registry,
                authorities={AGENT_ID: authority},
            ),
            agent_plans={AGENT_ID: self.plan},
        )

    def approve_pause_tool(self, *extra_tools: str) -> None:
        self.current_binding = self._binding(user_confirmed=tuple(sorted({RUNTIME_TOOL, *extra_tools})))

    def payload(self, **overrides):
        value = {
            "app_id": APP_ID,
            "agent_id": AGENT_ID,
            "messages": [{"role": "user", "content": "Execute approved action."}],
            "tool_arguments": {"confirm1": {"query": PRIVATE_ARGUMENT}},
        }
        value.update(overrides)
        return value

    @staticmethod
    def decision(continuation_id: str, *, outcome: str = "approved") -> dict:
        return {
            "decision_id": "decision_1749",
            "pause_id": continuation_id,
            "outcome": outcome,
            "authority_ref": "user:trusted",
            "evidence_ref": "evidence:session",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }


async def _pause(fx: ContinuationFixture):
    response = await fx.service.run_payload(fx.payload())
    assert response.status_code == 202
    assert response.body["ok"] is True
    assert response.body["agent_skill"]["run_status"] == "paused"
    pause = response.body["agent_skill"]["approval_pause"]
    assert pause["tool_id"] == RUNTIME_TOOL
    assert pause["continuation_id"]
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0
    serialized = json.dumps(response.body, ensure_ascii=False, sort_keys=True)
    assert PRIVATE_ARGUMENT not in serialized
    assert PRIVATE_OUTPUT not in serialized
    return response.body["continuation_ref"], pause["continuation_id"]


@pytest.mark.asyncio
async def test_pause_then_exact_approval_delta_resumes_real_core_tool_runtime() -> None:
    fx = ContinuationFixture()
    continuation_ref, continuation_id = await _pause(fx)
    fx.approve_pause_tool()

    response = await fx.service.resume_payload(
        fx.payload(continuation_ref=continuation_ref, decision=fx.decision(continuation_id))
    )

    assert response.status_code == 200
    assert response.body["agent_skill"]["run_status"] == "completed"
    assert fx.handler_calls == 1
    assert fx.provider.calls == 0
    assert fx.verifier.calls == 1
    serialized = json.dumps(response.body, ensure_ascii=False, sort_keys=True)
    for forbidden in (PRIVATE_ARGUMENT, PRIVATE_OUTPUT, "sk-continuation-secret"):
        assert forbidden not in serialized
    with pytest.raises(Exception) as exc_info:
        fx.store.resolve(app_id=APP_ID, continuation_ref=continuation_ref)
    assert getattr(exc_info.value, "code", None) == "continuation_consumed"


@pytest.mark.asyncio
async def test_resume_rejects_unrelated_permission_widening_before_claim() -> None:
    fx = ContinuationFixture()
    continuation_ref, continuation_id = await _pause(fx)
    fx.approve_pause_tool("rogue.tool")

    response = await fx.service.resume_payload(
        fx.payload(continuation_ref=continuation_ref, decision=fx.decision(continuation_id))
    )

    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_authority_mismatch"
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0
    active = fx.store.resolve(app_id=APP_ID, continuation_ref=continuation_ref)
    assert active.state == "active"
    assert active.claim_token is None


@pytest.mark.asyncio
async def test_resume_rejects_changed_input_and_tool_arguments_before_claim() -> None:
    fx = ContinuationFixture()
    continuation_ref, continuation_id = await _pause(fx)
    fx.approve_pause_tool()

    for changed in (
        {"messages": [{"role": "user", "content": "changed intent"}]},
        {"tool_arguments": {"confirm1": {"query": "changed argument"}}},
    ):
        response = await fx.service.resume_payload(
            fx.payload(**changed, continuation_ref=continuation_ref, decision=fx.decision(continuation_id))
        )
        assert response.status_code == 409
        assert response.body["error"]["code"] == "continuation_identity_mismatch"
        active = fx.store.resolve(app_id=APP_ID, continuation_ref=continuation_ref)
        assert active.state == "active"
        assert active.claim_token is None
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0


@pytest.mark.asyncio
async def test_cancel_is_terminal_and_never_executes_tool_or_provider() -> None:
    fx = ContinuationFixture()
    continuation_ref, continuation_id = await _pause(fx)

    cancelled = await fx.service.cancel_payload(
        {"app_id": APP_ID, "continuation_ref": continuation_ref, "reason": "user_cancelled"}
    )
    assert cancelled.status_code == 200
    assert cancelled.body["status"] == "cancelled"
    assert cancelled.body["events"][0]["kind"] == "run_cancelled"
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0

    fx.approve_pause_tool()
    resumed = await fx.service.resume_payload(
        fx.payload(continuation_ref=continuation_ref, decision=fx.decision(continuation_id))
    )
    assert resumed.status_code == 409
    assert resumed.body["error"]["code"] == "continuation_cancelled"
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0


@pytest.mark.asyncio
async def test_approval_pause_fails_closed_without_trusted_store_and_verifier() -> None:
    fx = ContinuationFixture(with_continuation=False)
    response = await fx.service.run_payload(fx.payload())
    assert response.status_code == 503
    assert response.body["error"]["code"] == "approval_verification_unavailable"
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0
