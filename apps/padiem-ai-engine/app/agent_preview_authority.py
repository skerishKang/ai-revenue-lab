"""Preview-only synthetic Agent authority for a non-production pilot lane.

This module exists so a *non-production* Engine deployment can exercise the
bounded Agent/Skill runtime end to end with no real authority at all: no
provider runtime, no D1, no session or caller registry, no secret, no user data.
Everything it builds is synthetic and in-memory.

Three guards must all hold before any authority exists. A missing or malformed
value is never a partial authority: the builder returns ``None`` and the caller
keeps its fail-closed composition.

1. ``ENGINE_DEPLOY_ENV`` is present and is not a production marker;
2. ``ENGINE_AGENT_PREVIEW_ENABLED`` equals the exact pilot marker;
3. the identities are fixed constants of this module -- a caller can never
   inject an app, agent, tool or subject identity into the pilot lane.

The synthetic identities deliberately mirror the provider-free A5 readiness
fixture so the pilot exercises the same bounded contract the gate records.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep
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
from app.capability_manifest import CapabilityState
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

DEPLOY_ENV_NAME = "ENGINE_DEPLOY_ENV"
ENABLE_ENV_NAME = "ENGINE_AGENT_PREVIEW_ENABLED"
PREVIEW_ENABLE_MARKER = "ENABLE_PREVIEW_AGENT_PILOT"
FORBIDDEN_DEPLOY_ENVS = frozenset({"production", "prod", "prd"})
_DEPLOY_ENV_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

# Fixed synthetic identities. Nothing here is read from the environment.
PREVIEW_APP_ID = "engine-a5-agent-synthetic"
PREVIEW_AGENT_ID = "agent:engine:a5-probe@1"
PREVIEW_CANONICAL_TOOL_ID = "tool:engine:a5-agent-probe@1"
PREVIEW_RUNTIME_TOOL_ID = "a5-agent-probe.tool"
PREVIEW_SUBJECT_ID = "actor:a5-synthetic"
PREVIEW_OUTPUT_CONTRACT_REF = "output:a5@1"

#: The only capability this lane may raise, and only from DEFERRED to AVAILABLE.
PREVIEW_CAPABILITY_IDS: tuple[str, ...] = ("agent_skill_runtime",)


def _env_value(env: Any, name: str) -> str | None:
    """Read one bounded string from a worker env without ever raising."""
    if env is None:
        return None
    try:
        if isinstance(env, Mapping):
            raw = env.get(name)
        else:
            raw = getattr(env, name, None)
    except Exception:
        return None
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    return raw or None


def deploy_environment(env: Any) -> str | None:
    """Return the declared deployment environment marker, when it is well formed."""
    value = _env_value(env, DEPLOY_ENV_NAME)
    if value is None:
        return None
    lowered = value.lower()
    if not _DEPLOY_ENV_RE.fullmatch(lowered):
        return None
    return lowered


def preview_lane_enabled(env: Any) -> bool:
    """True only for an explicitly marked, explicitly non-production isolate."""
    marker = deploy_environment(env)
    if marker is None or marker in FORBIDDEN_DEPLOY_ENVS:
        return False
    return _env_value(env, ENABLE_ENV_NAME) == PREVIEW_ENABLE_MARKER


def preview_capability_overrides(env: Any) -> dict[str, CapabilityState] | None:
    """The posture override this lane may install, or ``None`` when disabled."""
    if not preview_lane_enabled(env):
        return None
    return {capability_id: CapabilityState.AVAILABLE for capability_id in PREVIEW_CAPABILITY_IDS}


class ProviderFreePreviewRuntime:
    """A runtime that must never be invoked: the synthetic task is agent-only."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _request: Any) -> Any:
        self.calls += 1
        raise AssertionError("the preview Agent pilot must not call a provider runtime")


@dataclass
class _SyntheticToolProxy:
    calls: int = 0

    async def __call__(self, _arguments: Mapping[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {"probe": "ok"}


@dataclass
class PreviewAgentLane:
    """The composed preview lane: service plus the counters a test can assert."""

    service: AgentSkillEngineService
    binding: EngineAgentSkillBinding
    runtime: ProviderFreePreviewRuntime
    tool_proxy: _SyntheticToolProxy = field(default_factory=_SyntheticToolProxy)

    @property
    def provider_runtime_calls(self) -> int:
        return self.runtime.calls

    @property
    def tool_calls(self) -> int:
        return self.tool_proxy.calls


def _synthetic_binding(tool_proxy: _SyntheticToolProxy) -> EngineAgentSkillBinding:
    tool_runtime = ToolRuntime()
    spec = ToolSpec(
        id=PREVIEW_RUNTIME_TOOL_ID,
        title="Preview synthetic read",
        description="Network-free preview Agent pilot probe",
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
    tool_runtime.register(spec, tool_proxy)
    registry = ToolRegistrySnapshot.from_entries(
        (RegisteredTool.from_spec(canonical_tool_id=PREVIEW_CANONICAL_TOOL_ID, runtime_spec=spec),)
    )
    definition = BoundedAgentDefinition(
        agent_id=PREVIEW_AGENT_ID,
        publisher_id="engine",
        title="Preview synthetic Agent",
        description="Network-free preview Agent pilot fixture",
        instruction="Execute only the bounded synthetic read step.",
        output_contract_ref=PREVIEW_OUTPUT_CONTRACT_REF,
        skill_package_ids=(),
        allowed_tool_ids=(PREVIEW_CANONICAL_TOOL_ID,),
        execution_budget=AgentExecutionBudget(max_steps=2, max_tool_calls=1, max_skill_calls=0),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref=PREVIEW_OUTPUT_CONTRACT_REF,
        task_type="general",
        optimize_for="balanced",
        max_tokens=256,
        max_steps_cap=2,
        context_policy={},
        model_policy={},
        output_contract={},
        tool_bindings=(ToolRuntimeBinding(PREVIEW_CANONICAL_TOOL_ID, PREVIEW_RUNTIME_TOOL_ID),),
    )
    compiled = compile_agent_profile(definition, policy)
    authority = TrustedToolAuthority(
        canonical_agent_id=PREVIEW_AGENT_ID,
        definition=definition,
        compiled=compiled,
        authorization=ToolAuthorizationContext(
            app_id=PREVIEW_APP_ID,
            agent_id=compiled.runtime_profile.id,
        ),
    )
    return EngineAgentSkillBinding(
        app_id=PREVIEW_APP_ID,
        subject_id=PREVIEW_SUBJECT_ID,
        tool_binding=EngineToolBinding(
            app_id=PREVIEW_APP_ID,
            tool_runtime=tool_runtime,
            registry=registry,
            authorities={PREVIEW_AGENT_ID: authority},
        ),
    )


def build_preview_binding_resolver(
    env: Any,
) -> Callable[[str], EngineAgentSkillBinding | None] | None:
    """Build the synthetic resolver for the marked non-production lane only."""
    if not preview_lane_enabled(env):
        return None
    return build_agent_skill_binding_resolver(
        tool_binding_resolver=lambda _app_id: _synthetic_binding(_SyntheticToolProxy()).tool_binding,
        subject_resolver=lambda _app_id: PREVIEW_SUBJECT_ID,
    )


def build_preview_agent_lane(env: Any) -> PreviewAgentLane | None:
    """Compose the preview Agent lane, or ``None`` when any guard fails."""
    if not preview_lane_enabled(env):
        return None
    tool_proxy = _SyntheticToolProxy()
    binding = _synthetic_binding(tool_proxy)
    runtime = ProviderFreePreviewRuntime()
    service = AgentSkillEngineService(
        runtime_factory=lambda _app_id: runtime,
        binding_resolver=lambda requested_app_id: binding if requested_app_id == PREVIEW_APP_ID else None,
    )
    return PreviewAgentLane(service=service, binding=binding, runtime=runtime, tool_proxy=tool_proxy)


def preview_task_payload() -> dict[str, Any]:
    """The one synthetic task this lane runs: a bounded single-step read."""
    return {
        "app_id": PREVIEW_APP_ID,
        "agent_id": PREVIEW_AGENT_ID,
        "messages": [{"role": "user", "content": "synthetic"}],
        "agent_plan": {
            "agent_id": PREVIEW_AGENT_ID,
            "steps": [
                {
                    "step_id": "read",
                    "objective": "Run synthetic read",
                    "tool_id": PREVIEW_RUNTIME_TOOL_ID,
                }
            ],
        },
        "tool_arguments": {"read": {"query": "synthetic"}},
    }
