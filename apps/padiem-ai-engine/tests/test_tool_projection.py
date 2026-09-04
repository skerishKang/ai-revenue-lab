"""Focused tests for the #1746 Engine tool projection layer.

Covers the projection-owned invariants only:
- caller JSON and provider wire vocabulary can never mint tool authority;
- bindings must reuse the Core ToolRuntime/ToolRegistrySnapshot (no second runtime);
- authority resolution fails closed for unknown agents and mismatched grants;
- public output projection is bounded and secret-redacted;
- lifecycle events can only come from a genuine Core ToolEvent.
"""

from __future__ import annotations

import pytest

from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)
from padiem_ai_core.contracts import (
    ApprovalPolicy,
    RunStatus,
    ToolEvent,
    ToolSideEffect,
    ToolSpec,
)
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_resource_policy import ToolResourcePolicy
from padiem_ai_core.tool_runtime import (
    MAX_TOOL_ARGUMENT_BYTES,
    ToolAuthorizationContext,
    ToolRuntime,
)

from app.tool_projection import (
    ENGINE_TOOL_CONTRACT_VERSION,
    REDACTED_TOOL_VALUE,
    EngineToolBinding,
    EngineToolProjectionError,
    TrustedToolAuthority,
    json_size,
    parse_tool_continuation_ref,
    parse_tool_execution_request,
    project_core_tool_lifecycle,
    project_redacted_tool_output,
)

APP_ID = "t1746"
CANONICAL_AGENT = "agent:acme:assistant@1"
CANONICAL_SEARCH = "tool:acme:search@1"
RUNTIME_SEARCH = "search.tool"


async def _noop_handler(arguments: dict) -> dict:
    return {"ok": True}


def make_search_spec() -> ToolSpec:
    return ToolSpec(
        id=RUNTIME_SEARCH,
        title="Search",
        description="Read-only bounded search",
        owner="core",
        side_effect=ToolSideEffect.READ,
        approval_policy=ApprovalPolicy.NOT_REQUIRED,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        auth_scope=("search",),
        timeout_seconds=5,
    )


def make_authority(
    *,
    app_id: str = APP_ID,
    agent_id: str = CANONICAL_AGENT,
    scopes: tuple[str, ...] = ("search",),
) -> TrustedToolAuthority:
    definition = BoundedAgentDefinition(
        agent_id=agent_id,
        publisher_id="acme",
        title="Assistant",
        description="Trusted test assistant",
        instruction="Answer safely",
        output_contract_ref="output:text@1",
        allowed_tool_ids=(CANONICAL_SEARCH,),
        execution_budget=AgentExecutionBudget(),
    )
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=1024,
        max_steps_cap=8,
        context_policy={},
        model_policy={},
        output_contract={},
        tool_bindings=(ToolRuntimeBinding(CANONICAL_SEARCH, RUNTIME_SEARCH),),
    )
    compiled = compile_agent_profile(definition, policy)
    authorization = ToolAuthorizationContext(
        app_id=app_id,
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=scopes,
    )
    return TrustedToolAuthority(
        canonical_agent_id=agent_id,
        definition=definition,
        compiled=compiled,
        authorization=authorization,
    )


def make_registry() -> ToolRegistrySnapshot:
    return ToolRegistrySnapshot.from_entries(
        [RegisteredTool.from_spec(canonical_tool_id=CANONICAL_SEARCH, runtime_spec=make_search_spec())]
    )


def make_binding(
    *,
    runtime: ToolRuntime | None = None,
    registry: ToolRegistrySnapshot | None = None,
    authorities: dict | None = None,
    authorization_provider=None,
    resource_policy: ToolResourcePolicy | None = None,
) -> EngineToolBinding:
    if runtime is None:
        runtime = ToolRuntime()
        runtime.register(make_search_spec(), _noop_handler)
    return EngineToolBinding(
        app_id=APP_ID,
        tool_runtime=runtime,
        registry=registry if registry is not None else make_registry(),
        authorities=(
            authorities if authorities is not None else {CANONICAL_AGENT: make_authority()}
        ),
        authorization_provider=authorization_provider,
        resource_policy=resource_policy,
    )


def make_wire(**overrides) -> dict:
    payload = {
        "app_id": APP_ID,
        "agent_id": CANONICAL_AGENT,
        "tool_id": CANONICAL_SEARCH,
        "arguments": {"query": "hello"},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# request parsing: CALLER_JSON != TOOL_AUTHORITY, PROVIDER_FUNCTION_CALL_WIRE_IN_ENGINE = NO
# ---------------------------------------------------------------------------


def test_contract_version_is_stable():
    assert ENGINE_TOOL_CONTRACT_VERSION == "padiem.engine.tools/1.0"


def test_parse_accepts_minimal_canonical_wire():
    wire = parse_tool_execution_request(make_wire())
    assert wire.app_id == APP_ID
    assert wire.agent_id == CANONICAL_AGENT
    assert wire.tool_id == CANONICAL_SEARCH
    assert dict(wire.arguments) == {"query": "hello"}


@pytest.mark.parametrize(
    "key",
    ["tool_calls", "function_call", "tools", "parameters", "allowed_tools", "tool_choice"],
)
def test_provider_wire_vocabulary_is_rejected(key: str):
    with pytest.raises(EngineToolProjectionError) as excinfo:
        parse_tool_execution_request(make_wire(**{key: [{"id": "x"}]}))
    assert excinfo.value.code == "provider_tool_wire_rejected"
    assert excinfo.value.status_code == 400


@pytest.mark.parametrize(
    "key",
    ["authorization", "granted_auth_scopes", "user_confirmed_tools", "approved", "registry"],
)
def test_caller_minted_authority_keys_are_rejected(key: str):
    with pytest.raises(EngineToolProjectionError) as excinfo:
        parse_tool_execution_request(make_wire(**{key: ["anything"]}))
    assert excinfo.value.code == "caller_minted_tool_authority_rejected"


def test_provider_wire_rejected_even_inside_arguments_is_not_scanned():
    # Rejection is top-level wire vocabulary; nested arguments remain caller data
    # that Core schema validation governs.
    wire = parse_tool_execution_request(make_wire(arguments={"query": "tools"}))
    assert dict(wire.arguments) == {"query": "tools"}


def test_unknown_field_fails_closed():
    with pytest.raises(EngineToolProjectionError) as excinfo:
        parse_tool_execution_request(make_wire(extra="x"))
    assert excinfo.value.code == "invalid_tool_request"


@pytest.mark.parametrize(
    "agent_id",
    ["acme:assistant@1", "agent:acme:assistant", "agent:acme:assistant@0", "runtime-profile-id"],
)
def test_non_canonical_agent_id_rejected(agent_id: str):
    with pytest.raises(EngineToolProjectionError) as excinfo:
        parse_tool_execution_request(make_wire(agent_id=agent_id))
    assert excinfo.value.code == "invalid_tool_request"


@pytest.mark.parametrize(
    "tool_id",
    ["tool:acme:search", "tool:acme:search@1.2", "search.tool", "tool:ACME:search@1"],
)
def test_non_canonical_tool_id_rejected(tool_id: str):
    with pytest.raises(EngineToolProjectionError) as excinfo:
        parse_tool_execution_request(make_wire(tool_id=tool_id))
    assert excinfo.value.code == "invalid_tool_request"


def test_oversized_arguments_rejected_before_core():
    big = "x" * (MAX_TOOL_ARGUMENT_BYTES + 10)
    with pytest.raises(EngineToolProjectionError) as excinfo:
        parse_tool_execution_request(make_wire(arguments={"query": big}))
    assert excinfo.value.code == "tool_arguments_too_large"


def test_non_json_arguments_rejected():
    with pytest.raises(EngineToolProjectionError) as excinfo:
        parse_tool_execution_request(make_wire(arguments={"bad": {1, 2}}))
    assert excinfo.value.code == "invalid_tool_arguments"


def test_continuation_ref_grammar():
    assert parse_tool_continuation_ref("cont_abc123") == "cont_abc123"
    for bad in ["abc", "cont_" + "x" * 200, None, 5]:
        with pytest.raises(EngineToolProjectionError) as excinfo:
            parse_tool_continuation_ref(bad)
        assert excinfo.value.code == "invalid_continuation"


# ---------------------------------------------------------------------------
# binding gates: ENGINE_TOOL_RUNTIME_DUPLICATION = NO
# ---------------------------------------------------------------------------


class FakeSecondRuntime(ToolRuntime):
    pass


def test_binding_rejects_tool_runtime_subclass():
    with pytest.raises(EngineToolProjectionError) as excinfo:
        make_binding(runtime=FakeSecondRuntime())
    assert excinfo.value.code == "invalid_tool_binding"
    assert excinfo.value.status_code == 503


def test_binding_rejects_registry_lookalike():
    with pytest.raises(EngineToolProjectionError) as excinfo:
        EngineToolBinding(
            app_id=APP_ID,
            tool_runtime=ToolRuntime(),
            registry={"entries": []},
            authorities={},
        )
    assert excinfo.value.code == "invalid_tool_binding"


def test_binding_rejects_authority_key_mismatch():
    with pytest.raises(EngineToolProjectionError) as excinfo:
        make_binding(authorities={"agent:other:x@1": make_authority()})
    assert excinfo.value.code == "invalid_tool_binding"


def test_binding_rejects_cross_app_authority():
    foreign = make_authority(app_id="other-app")
    with pytest.raises(EngineToolProjectionError) as excinfo:
        make_binding(authorities={CANONICAL_AGENT: foreign})
    assert excinfo.value.code == "invalid_tool_binding"


def test_resolve_authority_unknown_agent_fails_closed():
    binding = make_binding()
    with pytest.raises(EngineToolProjectionError) as excinfo:
        binding.resolve_authority("agent:acme:ghost@1")
    assert excinfo.value.code == "tool_agent_not_bound"
    assert excinfo.value.status_code == 403


def test_resolve_authority_provider_cross_app_grant_rejected():
    def provider(agent_id: str) -> ToolAuthorizationContext:
        return ToolAuthorizationContext(app_id="other-app", agent_id="agent-runtime:x")

    binding = make_binding(authorization_provider=provider)
    with pytest.raises(EngineToolProjectionError) as excinfo:
        binding.resolve_authority(CANONICAL_AGENT)
    assert excinfo.value.code == "tool_authorization_mismatch"
    assert excinfo.value.status_code == 403


def test_resolve_authority_provider_wrong_agent_rejected():
    def provider(agent_id: str) -> ToolAuthorizationContext:
        return ToolAuthorizationContext(app_id=APP_ID, agent_id="agent-runtime:impersonation")

    binding = make_binding(authorization_provider=provider)
    with pytest.raises(EngineToolProjectionError) as excinfo:
        binding.resolve_authority(CANONICAL_AGENT)
    assert excinfo.value.code == "tool_authorization_mismatch"


def test_resolve_authority_provider_grant_is_applied():
    granted = make_authority()

    def provider(agent_id: str) -> ToolAuthorizationContext:
        return granted.authorization

    binding = make_binding(authorization_provider=provider)
    authority = binding.resolve_authority(CANONICAL_AGENT)
    assert authority.authorization is granted.authorization


def test_resolve_tool_unregistered_canonical_fails_closed():
    binding = make_binding()
    with pytest.raises(EngineToolProjectionError) as excinfo:
        binding.resolve_tool("tool:acme:ghost@1")
    assert excinfo.value.code == "tool_not_registered"
    assert excinfo.value.status_code == 403


def test_resolve_tool_maps_to_runtime_spec():
    entry = make_binding().resolve_tool(CANONICAL_SEARCH)
    assert entry.runtime_tool_id == RUNTIME_SEARCH


def test_effective_resources_narrows_only():
    binding = make_binding(resource_policy=ToolResourcePolicy(max_timeout_seconds=2))
    entry = binding.resolve_tool(CANONICAL_SEARCH)
    effective = binding.effective_resources(entry)
    assert effective.timeout_seconds == 2
    assert effective.argument_bytes <= MAX_TOOL_ARGUMENT_BYTES


# ---------------------------------------------------------------------------
# output projection: TOOL_RESULT_SECRET_LEAK = NO
# ---------------------------------------------------------------------------


def test_redaction_hides_secret_shaped_keys():
    output = {
        "result": "visible",
        "api_key": "sk-live-abcdef",
        "nested": {"access_token": "tok", "ok": "still visible"},
        "cookies": ["session=abc"],
    }
    projected, truncated = project_redacted_tool_output(output)
    assert projected["result"] == "visible"
    assert projected["api_key"] == REDACTED_TOOL_VALUE
    assert projected["nested"]["access_token"] == REDACTED_TOOL_VALUE
    assert projected["nested"]["ok"] == "still visible"
    assert "sk-live-abcdef" not in repr(projected)
    assert "tok" not in repr(projected["nested"]["access_token"])
    assert truncated is False


def test_redaction_bounds_strings_lists_and_nodes():
    output = {
        "long": "z" * 5_000,
        "many": list(range(500)),
        "deep": {f"k{i}": {f"j{i}": i} for i in range(600)},
    }
    projected, truncated = project_redacted_tool_output(output)
    assert truncated is True
    assert all(len(value) <= 2_048 + len("[truncated]") for value in [projected["long"]])
    assert len(projected["many"]) == 64


def test_redaction_drops_oversized_projection_to_none():
    # 400 keys x ~2KB strings stay under the 512-node ceiling but blow past the
    # 32KB public byte ceiling after per-string truncation -> whole projection
    # is dropped, never partially leaked.
    output = {f"field_{i}": "y" * 2_000 for i in range(400)}
    projected, truncated = project_redacted_tool_output(output)
    assert projected is None
    assert truncated is True


def test_json_size_matches_core_encoding():
    assert json_size({"a": 1}) == len('{"a":1}'.encode("utf-8"))


# ---------------------------------------------------------------------------
# lifecycle projection: TOOL_EVENT_AUTHORITY = Core ToolRuntime only
# ---------------------------------------------------------------------------


def make_event(status: RunStatus = RunStatus.COMPLETED) -> ToolEvent:
    return ToolEvent(tool_id=RUNTIME_SEARCH, status=status, duration_ms=7)


def test_lifecycle_projects_genuine_core_event():
    lifecycle = project_core_tool_lifecycle(
        make_event(),
        run_id="torun:x",
        event_id="evt:x",
        sequence=1,
        canonical_tool_id=CANONICAL_SEARCH,
    )
    public = lifecycle.to_public_dict()
    assert public["kind"] == "completed"
    assert public["tool_id"] == CANONICAL_SEARCH


@pytest.mark.parametrize(
    "status,kind",
    [
        (RunStatus.TOOL_RUNNING, "started"),
        (RunStatus.FAILED, "failed"),
        (RunStatus.TIMEOUT, "timed_out"),
        (RunStatus.POLICY_BLOCKED, "unavailable"),
    ],
)
def test_lifecycle_status_mapping(status: RunStatus, kind: str):
    lifecycle = project_core_tool_lifecycle(
        make_event(status),
        run_id="torun:x",
        event_id="evt:x",
        sequence=2,
        canonical_tool_id=CANONICAL_SEARCH,
    )
    assert lifecycle.kind.value == kind


def test_lifecycle_rejects_model_output_source():
    fake = {"tool_id": RUNTIME_SEARCH, "status": "completed", "duration_ms": 1}
    with pytest.raises(EngineToolProjectionError) as excinfo:
        project_core_tool_lifecycle(
            fake,
            run_id="torun:x",
            event_id="evt:x",
            sequence=1,
            canonical_tool_id=CANONICAL_SEARCH,
        )
    assert excinfo.value.code == "invalid_tool_event_source"
    assert excinfo.value.status_code == 500


def test_lifecycle_rejects_non_canonical_tool_id():
    with pytest.raises(EngineToolProjectionError) as excinfo:
        project_core_tool_lifecycle(
            make_event(),
            run_id="torun:x",
            event_id="evt:x",
            sequence=1,
            canonical_tool_id="bad tool id!",
        )
    assert excinfo.value.code == "invalid_tool_event_source"
