"""Provider-free canonical approval-pause smoke binding (#3317).

This is a disabled-by-default test fixture for proving the existing
ToolRuntime -> AgentBridge -> ApprovalPause -> continuation lifecycle in a
future owner-authorized Production smoke.

It is not a second approval protocol and has no provider/network adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from padiem_ai_core import (
    AgentExecutionBudget,
    ApprovalPolicy,
    BoundedAgentDefinition,
    ToolAuthorizationContext,
    ToolRegistrySnapshot,
    ToolResourcePolicy,
    ToolRuntime,
    ToolRuntimeBinding,
    ToolSideEffect,
    ToolSpec,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.tool_registry import RegisteredTool

from app.tool_projection import EngineToolBinding, TrustedToolAuthority


APPROVAL_SMOKE_ENABLE_ENV = "PADIEM_ENGINE_APPROVAL_SMOKE_ENABLED"
APPROVAL_SMOKE_APP_ID = "b54-engine-approval-smoke"
APPROVAL_SMOKE_AGENT_ID = "agent:padiem:approval_smoke@1"
APPROVAL_SMOKE_CANONICAL_TOOL_ID = "tool:padiem:approval_smoke@1"
APPROVAL_SMOKE_RUNTIME_TOOL_ID = "approval_smoke.confirm"
APPROVAL_SMOKE_AUTH_SCOPE = "approval.smoke"


async def _confirmed_handler(arguments: dict) -> dict:
    """Zero-side-effect handler reached only after canonical confirmation."""
    return {
        "confirmed": True,
        "nonce": arguments["nonce"],
        "side_effect": False,
    }


def approval_smoke_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=APPROVAL_SMOKE_RUNTIME_TOOL_ID,
        title="Approval continuation smoke confirmation",
        description=(
            "Synthetic zero-side-effect tool used only to prove the canonical "
            "approval continuation lifecycle."
        ),
        owner="core",
        side_effect=ToolSideEffect.NONE,
        approval_policy=ApprovalPolicy.USER_CONFIRMATION,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "nonce": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                }
            },
            "required": ["nonce"],
        },
        output_contract={
            "type": "object",
            "fields": ["confirmed", "nonce", "side_effect"],
        },
        auth_scope=(APPROVAL_SMOKE_AUTH_SCOPE,),
        timeout_seconds=1.0,
        user_visible=False,
    )


def build_approval_smoke_binding() -> EngineToolBinding:
    """Build the fixture exclusively from existing Core authority primitives."""
    spec = approval_smoke_tool_spec()
    runtime = ToolRuntime()
    runtime.register(spec, _confirmed_handler)

    registry = ToolRegistrySnapshot.from_entries(
        (
            RegisteredTool.from_spec(
                canonical_tool_id=APPROVAL_SMOKE_CANONICAL_TOOL_ID,
                runtime_spec=spec,
            ),
        )
    )
    definition = BoundedAgentDefinition(
        agent_id=APPROVAL_SMOKE_AGENT_ID,
        publisher_id="padiem",
        title="Approval smoke agent",
        description="Provider-free approval continuation smoke agent",
        instruction="Run only the synthetic approval confirmation tool.",
        output_contract_ref="output:text@1",
        allowed_tool_ids=(APPROVAL_SMOKE_CANONICAL_TOOL_ID,),
        execution_budget=AgentExecutionBudget(),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=128,
        max_steps_cap=2,
        context_policy={},
        model_policy={},
        output_contract={},
        tool_bindings=(
            ToolRuntimeBinding(
                canonical_tool_id=APPROVAL_SMOKE_CANONICAL_TOOL_ID,
                runtime_tool_id=APPROVAL_SMOKE_RUNTIME_TOOL_ID,
            ),
        ),
    )
    compiled = compile_agent_profile(definition, policy)
    authorization = ToolAuthorizationContext(
        app_id=APPROVAL_SMOKE_APP_ID,
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=(APPROVAL_SMOKE_AUTH_SCOPE,),
    )
    authority = TrustedToolAuthority(
        canonical_agent_id=APPROVAL_SMOKE_AGENT_ID,
        definition=definition,
        compiled=compiled,
        authorization=authorization,
    )
    return EngineToolBinding(
        app_id=APPROVAL_SMOKE_APP_ID,
        tool_runtime=runtime,
        registry=registry,
        authorities={APPROVAL_SMOKE_AGENT_ID: authority},
        authorization_provider=None,
        resource_policy=ToolResourcePolicy(),
    )


def approval_smoke_enabled_for_env(env: object) -> bool:
    """Only deployment-owned env state can enable the fixture."""
    return getattr(env, APPROVAL_SMOKE_ENABLE_ENV, None) == "1"


def with_approval_smoke_binding(
    env: object,
    base_resolver: Callable[[str], EngineToolBinding | None] | None,
) -> Callable[[str], EngineToolBinding | None] | None:
    """Return the original resolver byte-for-byte by identity while disabled."""
    if not approval_smoke_enabled_for_env(env):
        return base_resolver

    smoke_binding = build_approval_smoke_binding()

    def resolver(app_id: str) -> EngineToolBinding | None:
        if app_id == APPROVAL_SMOKE_APP_ID:
            return smoke_binding
        if base_resolver is None:
            return None
        return base_resolver(app_id)

    subject_for_app = getattr(base_resolver, "subject_for_app", None)
    if callable(subject_for_app):
        setattr(resolver, "subject_for_app", subject_for_app)
    return resolver



APPROVAL_SMOKE_PROVIDER_CALLS = 0
APPROVAL_SMOKE_EXTERNAL_SIDE_EFFECTS = 0
APPROVAL_SMOKE_DEFAULT_ENABLED = False
