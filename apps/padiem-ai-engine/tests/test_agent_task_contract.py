"""Bounded Agent task contract tests (#2786 S13-3b).

The agent task contract is additive: it names the task identity, owner identity,
capability requirement, execution status, result reference and in-response audit
evidence a caller previously had to infer. It mints no identifier, widens no
authority and projects no new Core data.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec
from padiem_ai_core.orchestration import OrchestrationError
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolAuthorizationContext, ToolRuntime

import app.agent_skill_service as service_module
from app.agent_skill_authority import (
    EngineAgentSkillBinding,
    build_agent_skill_binding_resolver,
)
from app.agent_skill_projection import (
    ENGINE_AGENT_TASK_CONTRACT_VERSION,
    project_agent_skill_result,
)
from app.agent_skill_service import AgentSkillEngineService
from app.tool_projection import EngineToolBinding, TrustedToolAuthority

APP_ID = "s13task"
SUBJECT_ID = "actor:s13-task"
AGENT_ID = "agent:core:task@1"
CANONICAL_TOOL = "tool:core:task-read@1"
RUNTIME_TOOL = "task-read.tool"
REQUIRED_CAPABILITY = "agent_task_execution"
OUTPUT_CONTRACT_REF = "output:task@1"


class NoProviderRuntime:
    """Provider-free sentinel: the agent-only plan must never call a runtime."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _request: Any) -> Any:
        self.calls += 1
        raise AssertionError("the bounded agent task must not call a provider runtime")


def _raise(error: Exception):
    class _Runner:
        def __init__(self, **_kwargs: Any) -> None:
            self._error = error

        async def run(self, _request: Any) -> Any:
            raise self._error

    return _Runner


class _ToolProxy:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _arguments: Any) -> dict[str, Any]:
        self.calls += 1
        return {"probe": "ok"}


class _TaskFixture:
    def __init__(self, *, app_id: str = APP_ID) -> None:
        self.app_id = app_id
        self.runtime = NoProviderRuntime()
        self.tool_proxy = _ToolProxy()
        self.binding = self._binding()
        self.service = AgentSkillEngineService(
            runtime_factory=lambda _app_id: self.runtime,
            binding_resolver=lambda requested: self.binding
            if requested == self.app_id
            else None,
        )

    def _binding(self) -> EngineAgentSkillBinding:
        tool_runtime = ToolRuntime()
        spec = ToolSpec(
            id=RUNTIME_TOOL,
            title="Task read",
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
        tool_runtime.register(spec, self.tool_proxy)
        registry = ToolRegistrySnapshot.from_entries(
            (RegisteredTool.from_spec(canonical_tool_id=CANONICAL_TOOL, runtime_spec=spec),)
        )
        definition = BoundedAgentDefinition(
            agent_id=AGENT_ID,
            publisher_id="core",
            title="Bounded task agent",
            description="Bounded single-step agent task",
            instruction="Execute the bounded read step.",
            output_contract_ref=OUTPUT_CONTRACT_REF,
            skill_package_ids=(),
            allowed_tool_ids=(CANONICAL_TOOL,),
            required_capabilities=(REQUIRED_CAPABILITY,),
            execution_budget=AgentExecutionBudget(
                max_steps=2, max_tool_calls=1, max_skill_calls=0
            ),
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
                app_id=self.app_id,
                agent_id=compiled.runtime_profile.id,
            ),
        )
        return EngineAgentSkillBinding(
            app_id=self.app_id,
            subject_id=SUBJECT_ID,
            tool_binding=EngineToolBinding(
                app_id=self.app_id,
                tool_runtime=tool_runtime,
                registry=registry,
                authorities={AGENT_ID: authority},
            ),
        )

    def payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "app_id": self.app_id,
            "agent_id": AGENT_ID,
            "messages": [{"role": "user", "content": "bounded task"}],
            "agent_plan": {
                "agent_id": AGENT_ID,
                "steps": [
                    {
                        "step_id": "read",
                        "objective": "Run the bounded read",
                        "tool_id": RUNTIME_TOOL,
                    }
                ],
            },
            "tool_arguments": {"read": {"query": "bounded"}},
        }
        payload.update(overrides)
        return payload


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _task_block(fixture: _TaskFixture) -> dict[str, Any]:
    response = _run(fixture.service.run_payload(fixture.payload()))
    assert response.status_code == 200, response.body
    return response.body["agent_skill"]


# --- T1 contract fields ---------------------------------------------------


def test_task_contract_fields_are_present() -> None:
    fixture = _TaskFixture()

    block = _task_block(fixture)

    assert block["task_contract_version"] == ENGINE_AGENT_TASK_CONTRACT_VERSION
    assert isinstance(block["task_id"], str) and block["task_id"].startswith("orch_run_")
    assert block["owner_identity"] == {"subject_id": SUBJECT_ID}
    assert block["capability_required"] == [REQUIRED_CAPABILITY]
    assert block["execution_status"] == "completed"
    reference = block["result_reference"]
    assert reference["run_id"] == block["task_id"]
    assert reference["answer_present"] is True
    assert reference["resolved_tool_ids"] == [RUNTIME_TOOL]
    assert reference["tool_event_count"] == 1
    audit = block["audit_event"]
    assert isinstance(audit["trace_id"], str) and audit["trace_id"].startswith("agtr_")
    assert audit["event_count"] >= 1
    assert isinstance(audit["terminal_kind"], str)


def test_task_contract_does_not_project_caller_identity_or_raw_inputs() -> None:
    fixture = _TaskFixture()

    block = _task_block(fixture)

    assert "caller_id" not in block["owner_identity"]
    serialized = repr(block)
    assert "bounded" not in serialized.lower() or "query" not in serialized
    assert "HIDDEN" not in serialized


# --- T2 backward compatibility -------------------------------------------


def test_existing_projection_keys_keep_their_meaning() -> None:
    fixture = _TaskFixture()

    block = _task_block(fixture)

    assert block["contract_version"] == "padiem.engine.agent-skill/1.0"
    assert block["agent_id"] == AGENT_ID
    assert block["run_status"] == "completed"
    assert block["execution_state"] == "completed"
    assert block["resolved_tool_ids"] == [RUNTIME_TOOL]
    assert isinstance(block["events"], list) and block["events"]
    assert isinstance(block["state_transitions"], list)
    assert block["approval_pause"] is None
    assert fixture.tool_proxy.calls == 1


def test_projection_rejects_non_core_inputs() -> None:
    with pytest.raises(TypeError):
        project_agent_skill_result("not a result", selection="not a selection")


# --- T3 authority injection ----------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    (
        {"subject_id": "actor:caller"},
        {"provider_route": "caller"},
        {"authorization": "caller"},
        {"connector_grants": "caller"},
    ),
)
def test_caller_authority_injection_is_rejected(overrides: dict[str, Any]) -> None:
    fixture = _TaskFixture()

    response = _run(fixture.service.run_payload(fixture.payload(**overrides)))

    assert response.body["error"]["code"] == "caller_agent_authority_not_allowed"
    assert fixture.runtime.calls == 0


# --- T4 missing binding ---------------------------------------------------


def test_unbound_application_fails_closed() -> None:
    fixture = _TaskFixture(app_id=APP_ID)
    payload = fixture.payload()
    payload["app_id"] = "unbound-app"

    response = _run(fixture.service.run_payload(payload))

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_skill_runtime_unavailable"
    assert fixture.runtime.calls == 0


# --- T5 capability requirement -------------------------------------------


def test_missing_capability_maps_to_403(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _TaskFixture()
    monkeypatch.setattr(
        service_module,
        "OrchestrationRunner",
        _raise(OrchestrationError("capability_missing", "capability not trusted")),
    )

    response = _run(fixture.service.run_payload(fixture.payload()))

    assert response.status_code == 403
    assert response.body["error"]["code"] == "capability_missing"
    assert "agent_skill" not in response.body


# --- T6 idempotency -------------------------------------------------------


def test_idempotency_conflict_maps_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _TaskFixture()
    conflict = service_module.IdempotencyConflictError("duplicate execution request")
    monkeypatch.setattr(service_module, "OrchestrationRunner", _raise(conflict))

    response = _run(fixture.service.run_payload(fixture.payload()))

    assert response.status_code == 409
    assert response.body["error"]["code"] == "idempotency_conflict"


# --- T7 provider independence --------------------------------------------


def test_task_contract_is_provider_free() -> None:
    fixture = _TaskFixture()

    block = _task_block(fixture)
    second = _run(fixture.service.run_payload(fixture.payload())).body["agent_skill"]

    assert fixture.runtime.calls == 0
    # Two executions are two tasks: task_id remains the canonical run id.
    assert second["task_id"] != block["task_id"]
    assert second["owner_identity"] == block["owner_identity"]
