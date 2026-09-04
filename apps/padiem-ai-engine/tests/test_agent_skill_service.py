"""Focused conformance tests for #1749 E4A trusted Agent/Skill projection.

The fixture executes the real Core AgentPlanExecutor/BoundedAgentRuntime and
ToolRuntime with a network-free local handler. It proves caller identity
selection cannot mint runtime authority, Skill enablement cannot widen Tool
authority, inactive/missing Skill state fails closed, and Product output omits
hidden planning text, raw Tool arguments/results and server policy/grant state.
"""

from __future__ import annotations

import json

import pytest

from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.skill_package import ReusableSkillPackage
from padiem_ai_core.skill_registry import (
    SkillInstallation,
    SkillInstallationSnapshot,
    SkillInstallStatus,
    SkillRegistrySnapshot,
)
from padiem_ai_core.skill_runtime_adapter import TrustedSkillRuntimePolicy
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

from app.agent_skill_authority import EngineAgentSkillBinding
from app.agent_skill_service import AgentSkillEngineService
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

APP_ID = "e4test"
SUBJECT_ID = "user_1"
AGENT_ID = "agent:acme:assistant@1"
SKILL_ID = "skill:acme:research@1"
CANONICAL_SEARCH = "tool:acme:search@1"
RUNTIME_SEARCH = "search.tool"
HIDDEN_PLAN_OBJECTIVE = "HIDDEN-PLAN-OBJECTIVE-1749"
PRIVATE_ARGUMENT = "PRIVATE-TOOL-ARGUMENT-1749"
PRIVATE_TOOL_OUTPUT = "PRIVATE-TOOL-OUTPUT-1749"


class NoProviderRuntime:
    """Sentinel proving the plan bridge performs no Provider/B14 execution."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request):
        self.calls += 1
        raise AssertionError("Agent/Skill conformance must not call a real Provider runtime")


class Fixture:
    def __init__(
        self,
        *,
        install_status: SkillInstallStatus | None = SkillInstallStatus.ENABLED,
        register_skill: bool = True,
        skill_runtime_tool_id: str = RUNTIME_SEARCH,
    ) -> None:
        self.handler_calls = 0
        self.provider = NoProviderRuntime()
        self.tool_runtime = ToolRuntime()

        spec = ToolSpec(
            id=RUNTIME_SEARCH,
            title="Search",
            description="Network-free search fixture",
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

        async def handler(arguments: dict) -> dict:
            self.handler_calls += 1
            assert arguments["query"] == PRIVATE_ARGUMENT
            return {
                "visible": "ok",
                "private_tool_output": PRIVATE_TOOL_OUTPUT,
                "api_key": "sk-test-secret-must-not-project",
            }

        self.tool_runtime.register(spec, handler)
        self.tool_registry = ToolRegistrySnapshot.from_entries(
            (
                RegisteredTool.from_spec(
                    canonical_tool_id=CANONICAL_SEARCH,
                    runtime_spec=spec,
                ),
            )
        )

        self.definition = BoundedAgentDefinition(
            agent_id=AGENT_ID,
            publisher_id="publisher:acme",
            title="Assistant",
            description="Trusted bounded Agent fixture",
            instruction="Use only trusted runtime authority.",
            output_contract_ref="io:output@1",
            skill_package_ids=(SKILL_ID,),
            allowed_tool_ids=(CANONICAL_SEARCH,),
            execution_budget=AgentExecutionBudget(
                max_steps=4,
                max_tool_calls=2,
                max_skill_calls=2,
                max_wall_seconds=30,
            ),
        )
        self.agent_policy = TrustedAgentRuntimePolicy(
            context_policy_ref="context:default",
            model_policy_ref="model:auto",
            output_contract_ref="io:output@1",
            task_type="general",
            optimize_for="balanced",
            max_tokens=1024,
            max_steps_cap=4,
            context_policy={},
            model_policy={},
            output_contract={},
            tool_bindings=(
                ToolRuntimeBinding(
                    canonical_tool_id=CANONICAL_SEARCH,
                    runtime_tool_id=RUNTIME_SEARCH,
                ),
            ),
            active_skill_package_ids=frozenset({SKILL_ID}),
        )
        self.compiled = compile_agent_profile(self.definition, self.agent_policy)
        self.authority = TrustedToolAuthority(
            canonical_agent_id=AGENT_ID,
            definition=self.definition,
            compiled=self.compiled,
            authorization=ToolAuthorizationContext(
                app_id=APP_ID,
                agent_id=self.compiled.runtime_profile.id,
            ),
        )
        self.tool_binding = EngineToolBinding(
            app_id=APP_ID,
            tool_runtime=self.tool_runtime,
            registry=self.tool_registry,
            authorities={AGENT_ID: self.authority},
        )
        self.plan = AgentPlan(
            agent_id=AGENT_ID,
            steps=(
                AgentPlanStep(
                    step_id="search1",
                    objective=HIDDEN_PLAN_OBJECTIVE,
                    # Agent plans contain already-compiled runtime Tool ids.
                    tool_id=RUNTIME_SEARCH,
                ),
            ),
        )

        self.skill_package = ReusableSkillPackage(
            skill_id=SKILL_ID,
            publisher_id="publisher:acme",
            description="Trusted research Skill fixture.",
            instruction="Use only the trusted search Tool.",
            input_contract_ref="io:input@1",
            output_contract_ref="io:output@1",
            allowed_tool_ids=(CANONICAL_SEARCH,),
            context_policy_ref="context:default",
            model_policy_ref="model:auto",
        )
        self.skill_registry = SkillRegistrySnapshot.from_packages(
            (self.skill_package,) if register_skill else ()
        )
        if install_status is None:
            installations = ()
        else:
            installations = (
                SkillInstallation(
                    app_id=APP_ID,
                    subject_id=SUBJECT_ID,
                    skill_id=SKILL_ID,
                    status=install_status,
                ),
            )
        self.installations = SkillInstallationSnapshot.from_installations(installations)
        self.skill_policy = TrustedSkillRuntimePolicy(
            context_policy_ref="context:default",
            model_policy_ref="model:auto",
            output_contract_ref="io:output@1",
            task_type="general",
            optimize_for="balanced",
            max_tokens=512,
            max_steps_cap=4,
            context_policy={},
            model_policy={},
            output_contract={},
            tool_bindings=(
                ToolRuntimeBinding(
                    canonical_tool_id=CANONICAL_SEARCH,
                    runtime_tool_id=skill_runtime_tool_id,
                ),
            ),
        )
        self.binding = EngineAgentSkillBinding(
            app_id=APP_ID,
            subject_id=SUBJECT_ID,
            tool_binding=self.tool_binding,
            agent_plans={AGENT_ID: self.plan},
            skill_registry=self.skill_registry,
            skill_installations=self.installations,
            skill_runtime_policy_resolver=lambda skill_id: (
                self.skill_policy if skill_id == SKILL_ID else None
            ),
        )
        self.service = AgentSkillEngineService(
            runtime_factory=lambda app_id: self.provider,
            binding_resolver=lambda app_id: self.binding if app_id == APP_ID else None,
        )

    def payload(self, **overrides):
        value = {
            "app_id": APP_ID,
            "agent_id": AGENT_ID,
            "skill_id": SKILL_ID,
            "messages": [{"role": "user", "content": "Run the trusted Skill."}],
            "tool_arguments": {"search1": {"query": PRIVATE_ARGUMENT}},
        }
        value.update(overrides)
        return value


@pytest.mark.asyncio
async def test_trusted_agent_skill_selection_executes_real_core_tool_runtime_only() -> None:
    fx = Fixture()

    response = await fx.service.run_payload(fx.payload())

    assert response.status_code == 200
    assert response.body["ok"] is True
    public = response.body["agent_skill"]
    assert public["agent_id"] == AGENT_ID
    assert public["skill_id"] == SKILL_ID
    assert public["run_status"] == "completed"
    assert public["plan"] == {"agent_id": AGENT_ID, "step_count": 1}
    assert public["activated_skill"]["app_id"] == APP_ID
    assert public["activated_skill"]["subject_id"] == SUBJECT_ID
    assert public["activated_skill"]["skill_id"] == SKILL_ID
    assert fx.handler_calls == 1
    assert fx.provider.calls == 0

    serialized = json.dumps(response.body, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        HIDDEN_PLAN_OBJECTIVE,
        PRIVATE_ARGUMENT,
        PRIVATE_TOOL_OUTPUT,
        "sk-test-secret-must-not-project",
        "tool_bindings",
        "connected_connector_ids",
        "satisfied_entitlement_refs",
        "model_policy",
        "context_policy",
        "output_contract",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("agent", {"id": "caller-profile"}),
        ("agent_plan", {"steps": []}),
        ("compiled_profile", {"allowed_tools": [RUNTIME_SEARCH]}),
        ("tool_bindings", [{"tool_id": CANONICAL_SEARCH}]),
        ("tool_authorization", {"approved": True}),
        ("connector_grants", ["connector:fake:x@1"]),
        ("entitlement_ref", "entitlement:fake"),
        ("model_policy", {"provider": "caller"}),
        ("context_policy", {"widen": True}),
        ("provider_route", "caller-provider"),
        ("subject_id", "attacker_subject"),
        ("skill_runtime_policy", {"tool_bindings": []}),
    ),
)
async def test_caller_authority_shaped_fields_are_rejected(field: str, value) -> None:
    fx = Fixture()
    payload = fx.payload()
    payload[field] = value

    response = await fx.service.run_payload(payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "caller_agent_authority_not_allowed"
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0


@pytest.mark.asyncio
async def test_missing_live_binding_fails_closed_without_provider_or_tool_call() -> None:
    provider = NoProviderRuntime()
    service = AgentSkillEngineService(
        runtime_factory=lambda app_id: provider,
        binding_resolver=None,
    )

    response = await service.run_payload(
        {
            "app_id": APP_ID,
            "agent_id": AGENT_ID,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_skill_runtime_unavailable"
    assert provider.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("install_status", "expected_code"),
    (
        (SkillInstallStatus.DISABLED, "skill_not_enabled"),
        (None, "skill_not_installed"),
    ),
)
async def test_inactive_or_uninstalled_skill_fails_closed(
    install_status: SkillInstallStatus | None,
    expected_code: str,
) -> None:
    fx = Fixture(install_status=install_status)

    response = await fx.service.run_payload(fx.payload())

    assert response.status_code == 403
    assert response.body["error"]["code"] == expected_code
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0


@pytest.mark.asyncio
async def test_registry_missing_selected_package_fails_closed() -> None:
    fx = Fixture(register_skill=False)

    response = await fx.service.run_payload(fx.payload())

    assert response.status_code == 403
    assert response.body["error"]["code"] == "skill_not_registered"
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0


@pytest.mark.asyncio
async def test_skill_runtime_policy_cannot_widen_agent_tool_authority() -> None:
    # The declarative Skill still names the same canonical Tool, but a bad
    # trusted runtime policy attempts to map it to a runtime Tool id that the
    # compiled Agent did not receive. Core OrchestrationRunner must reject this
    # before ToolRuntime or Provider execution.
    fx = Fixture(skill_runtime_tool_id="rogue.tool")

    response = await fx.service.run_payload(fx.payload())

    assert response.status_code == 403
    assert response.body["error"]["code"] == "authority_widening_rejected"
    assert fx.handler_calls == 0
    assert fx.provider.calls == 0
