"""E9 A5-Agent activation-readiness gate (#2754).

This is an Agent-only, network-free readiness record. It never deploys,
mutates configuration, calls a provider, or changes manifest truth. Skill
runtime is deliberately absent from the synthetic authority and remains
deferred until a separate trusted registry/install/policy source exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping

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

from app.agent_skill_authority import EngineAgentSkillAuthorityError, EngineAgentSkillBinding
from app.agent_skill_service import AgentSkillEngineService
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

CONFIRMATION_TOKEN = "ACTIVATE_ENGINE_A5_AGENT_ONLY"
DEPLOYMENT_TARGET = "Cloudflare Workers (padiem-ai-engine)"
AGENT_REFERENCE_CONSUMERS = ("b54-padiem-claw", "b62-padiem-chat")
UNRESOLVED_FOR_LIVE_AUTHORITY = "UNRESOLVED_FOR_LIVE_AUTHORITY"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AGENT_ID = "agent:engine:a5-probe@1"
_CANONICAL_TOOL = "tool:engine:a5-agent-probe@1"
_RUNTIME_TOOL = "a5-agent-probe.tool"
_APP_ID = "engine-a5-agent-synthetic"
_SUBJECT_ID = "actor:a5-synthetic"
_SKILL_ID = "skill:engine:deferred@1"


class ActivationError(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _ID_RE.fullmatch(code):
            raise ValueError("activation error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


class EvidenceState(str, Enum):
    UNRESOLVED_FOR_LIVE_AUTHORITY = "UNRESOLVED_FOR_LIVE_AUTHORITY"
    NONE = "NONE"
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True, slots=True)
class RollbackReadinessMetadata:
    current_deployed_version: str = UNRESOLVED_FOR_LIVE_AUTHORITY
    rollback_version: str = UNRESOLVED_FOR_LIVE_AUTHORITY
    rollback_config: EvidenceState = EvidenceState.UNRESOLVED_FOR_LIVE_AUTHORITY
    config_binding_diff: EvidenceState = EvidenceState.UNRESOLVED_FOR_LIVE_AUTHORITY
    secret_name_diff: EvidenceState = EvidenceState.UNRESOLVED_FOR_LIVE_AUTHORITY

    def __post_init__(self) -> None:
        for name in ("current_deployed_version", "rollback_version"):
            value = getattr(self, name)
            if value != UNRESOLVED_FOR_LIVE_AUTHORITY and (
                not isinstance(value, str) or not _SHA_RE.fullmatch(value)
            ):
                raise ActivationError(
                    "invalid_readiness_metadata",
                    f"{name} must be a commit SHA or unresolved sentinel.",
                )
        for name in ("rollback_config", "config_binding_diff", "secret_name_diff"):
            if not isinstance(getattr(self, name), EvidenceState):
                raise ActivationError(
                    "invalid_readiness_metadata",
                    f"{name} must use the closed evidence-state vocabulary.",
                )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "current_deployed_version": self.current_deployed_version,
            "rollback_version": self.rollback_version,
            "rollback_config": self.rollback_config.value,
            "config_binding_diff": self.config_binding_diff.value,
            "secret_name_diff": self.secret_name_diff.value,
        }


@dataclass(frozen=True, slots=True)
class ProbeResult:
    case: str
    ok: bool
    error_code: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {"case": self.case, "ok": self.ok, "error_code": self.error_code}


@dataclass(frozen=True, slots=True)
class ReferenceParityResult:
    consumer: str
    ok: bool
    error_code: str | None
    finding: str
    rejected_authority_keys: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "consumer": self.consumer,
            "ok": self.ok,
            "error_code": self.error_code,
            "finding": self.finding,
            "rejected_authority_keys": list(self.rejected_authority_keys),
        }


@dataclass(frozen=True, slots=True)
class AgentActivationEvidence:
    current_main: str
    accepted_source_head: str
    deployment_target: str
    metadata: RollbackReadinessMetadata
    reference_consumers: tuple[str, ...]
    synthetic_cases: tuple[ProbeResult, ...]
    reference_parity: tuple[ReferenceParityResult, ...]
    real_provider_call_count: int = 0
    real_user_data: int = 0
    mutation_scope: str = "A5-Agent activation only"
    final_disposition: str = "PENDING_PRODUCTION_AUTHORIZATION"
    skill_activation: str = "DEFERRED"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "current_main": self.current_main,
            "accepted_source_head": self.accepted_source_head,
            "deployment_target": self.deployment_target,
            **self.metadata.to_public_dict(),
            "reference_consumers": list(self.reference_consumers),
            "synthetic_cases": [case.to_public_dict() for case in self.synthetic_cases],
            "reference_parity": [result.to_public_dict() for result in self.reference_parity],
            "real_provider_call_count": self.real_provider_call_count,
            "real_user_data": self.real_user_data,
            "mutation_scope": self.mutation_scope,
            "final_disposition": self.final_disposition,
            "skill_activation": self.skill_activation,
        }


def verify_confirmation_token(token: str) -> None:
    if token != CONFIRMATION_TOKEN:
        raise ActivationError("activation_not_authorized", "A5-Agent readiness requires the exact owner token.")


def verify_exact_main(current_main: str) -> None:
    if not isinstance(current_main, str) or not _SHA_RE.fullmatch(current_main):
        raise ActivationError("invalid_sha", "current_main must be a 40-character lowercase commit SHA.")


def _verify_source_head(accepted_source_head: str) -> None:
    if not isinstance(accepted_source_head, str) or not _SHA_RE.fullmatch(accepted_source_head):
        raise ActivationError("invalid_sha", "accepted_source_head must be a 40-character lowercase commit SHA.")


class _NoProviderRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _request: Any) -> Any:
        self.calls += 1
        raise AssertionError("A5-Agent synthetic readiness must not call a Provider runtime")


class _Fixture:
    def __init__(self, app_id: str = _APP_ID) -> None:
        if not _ID_RE.fullmatch(app_id):
            raise ActivationError("invalid_probe_identity", "synthetic app identity is invalid.")
        self.app_id = app_id
        self.provider = _NoProviderRuntime()
        self.tool_calls = 0
        self.tool_runtime = ToolRuntime()
        spec = ToolSpec(
            id=_RUNTIME_TOOL,
            title="A5 synthetic read",
            description="Network-free Agent activation probe",
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

        async def handler(_arguments: dict[str, Any]) -> dict[str, Any]:
            self.tool_calls += 1
            return {"probe": "ok"}

        self.tool_runtime.register(spec, handler)
        registry = ToolRegistrySnapshot.from_entries(
            (RegisteredTool.from_spec(canonical_tool_id=_CANONICAL_TOOL, runtime_spec=spec),)
        )
        definition = BoundedAgentDefinition(
            agent_id=_AGENT_ID,
            publisher_id="engine",
            title="A5 synthetic Agent",
            description="Network-free Agent activation fixture",
            instruction="Execute only the bounded synthetic read step.",
            output_contract_ref="output:a5@1",
            skill_package_ids=(),
            allowed_tool_ids=(_CANONICAL_TOOL,),
            execution_budget=AgentExecutionBudget(max_steps=2, max_tool_calls=1, max_skill_calls=0),
        )
        policy = TrustedAgentRuntimePolicy(
            context_policy_ref="context:default",
            model_policy_ref="model:auto",
            output_contract_ref="output:a5@1",
            task_type="general",
            optimize_for="balanced",
            max_tokens=256,
            max_steps_cap=2,
            context_policy={},
            model_policy={},
            output_contract={},
            tool_bindings=(ToolRuntimeBinding(_CANONICAL_TOOL, _RUNTIME_TOOL),),
        )
        compiled = compile_agent_profile(definition, policy)
        authority = TrustedToolAuthority(
            canonical_agent_id=_AGENT_ID,
            definition=definition,
            compiled=compiled,
            authorization=ToolAuthorizationContext(app_id=app_id, agent_id=compiled.runtime_profile.id),
        )
        self.binding = EngineAgentSkillBinding(
            app_id=app_id,
            subject_id=_SUBJECT_ID,
            tool_binding=EngineToolBinding(
                app_id=app_id,
                tool_runtime=self.tool_runtime,
                registry=registry,
                authorities={_AGENT_ID: authority},
            ),
        )
        self.plan = AgentPlan(
            agent_id=_AGENT_ID,
            steps=(AgentPlanStep(step_id="read", objective="Run synthetic read", tool_id=_RUNTIME_TOOL),),
        )
        self.service = AgentSkillEngineService(
            runtime_factory=lambda _app_id: self.provider,
            binding_resolver=lambda requested_app_id: self.binding if requested_app_id == app_id else None,
        )

    def payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "app_id": self.app_id,
            "agent_id": _AGENT_ID,
            "messages": [{"role": "user", "content": "synthetic"}],
            "agent_plan": self.plan.to_public_dict(),
            "tool_arguments": {"read": {"query": "synthetic"}},
        }
        payload.update(overrides)
        return payload


async def run_synthetic_probes() -> tuple[ProbeResult, ...]:
    fixture = _Fixture()
    results: list[ProbeResult] = []
    response = await fixture.service.run_payload(fixture.payload())
    body = response.body if isinstance(response.body, Mapping) else {}
    results.append(ProbeResult("agent_only_run", response.status_code == 200 and body.get("ok") is True,
                               None if response.status_code == 200 else _error_code(body)))
    results.append(ProbeResult("unknown_agent", await _is_rejected(fixture, fixture.payload(agent_id="agent:engine:unknown@1"), "tool_agent_not_bound")))
    results.append(ProbeResult("plan_agent_mismatch", await _is_rejected(fixture, fixture.payload(agent_plan={**fixture.plan.to_public_dict(), "agent_id": "agent:engine:other@1"}), "agent_plan_identity_mismatch")))
    rogue = {**fixture.plan.to_public_dict(), "steps": [{"step_id": "read", "objective": "rogue", "tool_id": "rogue.tool"}]}
    results.append(ProbeResult("plan_tool_outside_profile", await _is_rejected(fixture, fixture.payload(agent_plan=rogue), "agent_plan_tool_not_allowed")))
    results.append(ProbeResult("caller_subject_id", await _is_rejected(fixture, fixture.payload(subject_id="caller.subject"), "caller_agent_authority_not_allowed")))
    results.append(ProbeResult("caller_authority_fields", await _is_rejected(fixture, fixture.payload(provider_route="caller"), "caller_agent_authority_not_allowed")))
    results.append(ProbeResult("unsafe_subject", _unsafe_subject_fails_closed(fixture), "invalid_agent_skill_binding" if not _unsafe_subject_fails_closed(fixture) else None))
    results.append(ProbeResult("skill_runtime_deferred", await _is_rejected(fixture, fixture.payload(skill_id=_SKILL_ID), "skill_not_allowed")))
    return tuple(results)


async def _is_rejected(fixture: _Fixture, payload: dict[str, Any], expected: str) -> bool:
    response = await fixture.service.run_payload(payload)
    body = response.body if isinstance(response.body, Mapping) else {}
    return _error_code(body) == expected


def _unsafe_subject_fails_closed(fixture: _Fixture) -> bool:
    try:
        EngineAgentSkillBinding(
            app_id=_APP_ID,
            subject_id="unsafe subject",
            tool_binding=fixture.binding.tool_binding,
        )
    except EngineAgentSkillAuthorityError as exc:
        return exc.code == "invalid_agent_skill_binding"
    return False


def _error_code(body: Mapping[str, Any]) -> str | None:
    error = body.get("error")
    return error.get("code") if isinstance(error, Mapping) else None


_AUTHORITY_PROBE_KEYS = (
    "subject_id",
    "tool_authorization",
    "authorization",
    "connector_grants",
    "provider",
    "provider_route",
    "policy",
    "model_policy",
    "entitlement",
    "skill_registry",
    "skill_installations",
    "skill_runtime_policy",
    "skill_id",
)


async def _run_reference_parity(consumer: str) -> ReferenceParityResult:
    fixture = _Fixture(f"{consumer}-a5-parity")
    response = await fixture.service.run_payload(fixture.payload())
    body = response.body if isinstance(response.body, Mapping) else {}
    if response.status_code != 200 or body.get("ok") is not True:
        return ReferenceParityResult(
            consumer=consumer,
            ok=False,
            error_code=_error_code(body) or "unexpected_status",
            finding="bounded Agent contract did not complete for consumer identity",
        )

    rejected: list[str] = []
    for key in _AUTHORITY_PROBE_KEYS:
        payload = fixture.payload(**{key: _APP_ID if key != "skill_id" else _SKILL_ID})
        response = await fixture.service.run_payload(payload)
        body = response.body if isinstance(response.body, Mapping) else {}
        expected = "skill_not_allowed" if key == "skill_id" else "caller_agent_authority_not_allowed"
        if _error_code(body) == expected:
            rejected.append(key)
        else:
            return ReferenceParityResult(
                consumer=consumer,
                ok=False,
                error_code=_error_code(body) or "authority_probe_not_rejected",
                finding=f"caller authority key was not rejected: {key}",
                rejected_authority_keys=tuple(rejected),
            )
    return ReferenceParityResult(
        consumer=consumer,
        ok=True,
        error_code=None,
        finding="bounded Agent contract completed and caller authority was rejected",
        rejected_authority_keys=tuple(rejected),
    )


async def run_reference_parity_probe() -> tuple[ReferenceParityResult, ...]:
    return tuple([await _run_reference_parity(consumer) for consumer in AGENT_REFERENCE_CONSUMERS])


async def evaluate_activation(
    *,
    confirmation_token: str,
    current_main: str,
    accepted_source_head: str,
    readiness_metadata: RollbackReadinessMetadata,
) -> AgentActivationEvidence:
    verify_confirmation_token(confirmation_token)
    verify_exact_main(current_main)
    _verify_source_head(accepted_source_head)
    synthetic = await run_synthetic_probes()
    parity = await run_reference_parity_probe()
    failed = [probe for probe in synthetic if not probe.ok]
    if failed:
        raise ActivationError("synthetic_probe_failed", "A5-Agent synthetic probes must all pass.")
    if any(not result.ok for result in parity):
        raise ActivationError(
            "reference_parity_failed",
            "A5-Agent reference parity probes must all pass.",
        )
    return AgentActivationEvidence(
        current_main=current_main,
        accepted_source_head=accepted_source_head,
        deployment_target=DEPLOYMENT_TARGET,
        metadata=readiness_metadata,
        reference_consumers=AGENT_REFERENCE_CONSUMERS,
        synthetic_cases=synthetic,
        reference_parity=parity,
        real_provider_call_count=0,
        real_user_data=0,
        skill_activation="DEFERRED",
    )
