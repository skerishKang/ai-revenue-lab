import pytest

from padiem_ai_core.agent_definition import AgentExecutionBudget, BoundedAgentDefinition
from padiem_ai_core.agent_delegation import (
    AgentDelegationError,
    AgentDelegationRequest,
    authorize_agent_delegation,
)
from padiem_ai_core.agent_events import AgentEventError, AgentEventKind, public_agent_event
from padiem_ai_core.agent_profile_adapter import (
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
)


def definition(agent_id, *, tools=("tool:padiem:search@1",), caps=("search",), max_steps=6, max_tool_calls=3, max_wall_seconds=120):
    return BoundedAgentDefinition(
        agent_id=agent_id,
        publisher_id="publisher:padiem",
        title="Agent",
        description="Bounded test agent.",
        instruction="Stay bounded.",
        output_contract_ref="io:test@1",
        allowed_tool_ids=tools,
        required_capabilities=caps,
        context_policy_ref="context:test@1",
        model_policy_ref="model:auto@1",
        execution_budget=AgentExecutionBudget(
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            max_skill_calls=0,
            max_wall_seconds=max_wall_seconds,
        ),
    )


def compiled(defn):
    return compile_agent_profile(
        defn,
        TrustedAgentRuntimePolicy(
            context_policy_ref="context:test@1",
            model_policy_ref="model:auto@1",
            output_contract_ref="io:test@1",
            task_type="general",
            optimize_for="balanced",
            max_tokens=1024,
            max_steps_cap=defn.execution_budget.max_steps,
            context_policy={"bounded": True},
            model_policy={"profile": "auto"},
            output_contract={"type": "object"},
            tool_bindings=(ToolRuntimeBinding(canonical_tool_id="tool:padiem:search@1", runtime_tool_id="search"),),
            available_capabilities=frozenset({"search"}),
        ),
    )


def request(parent, child, *, depth=1):
    return AgentDelegationRequest(
        delegation_id="delegation:test:1",
        parent_agent_id=parent.agent_id,
        child_agent_id=child.agent_id,
        reason="Delegate a bounded research subtask.",
        allowed_tools=("search",),
        capabilities=("search",),
        max_steps=3,
        max_tool_calls=2,
        max_wall_seconds=60,
        depth=depth,
    )


def test_delegation_is_inherited_or_narrower() -> None:
    parent = definition("agent:padiem:parent@1")
    child = definition("agent:padiem:child@1", max_steps=3, max_tool_calls=2, max_wall_seconds=60)
    authority = authorize_agent_delegation(
        request(parent, child),
        parent_definition=parent,
        parent_profile=compiled(parent),
        child_definition=child,
        child_profile=compiled(child),
    )
    assert authority.authorized_tool_ids == ("search",)
    assert authority.delegation.fingerprint


def test_delegation_rejects_tool_widening() -> None:
    parent = definition("agent:padiem:parent@1")
    child = definition("agent:padiem:child@1")
    delegated = AgentDelegationRequest(
        delegation_id="delegation:test:2",
        parent_agent_id=parent.agent_id,
        child_agent_id=child.agent_id,
        reason="Attempt widening.",
        allowed_tools=("filesystem:write",),
        capabilities=(),
        max_steps=1,
        max_tool_calls=0,
        max_wall_seconds=30,
    )
    with pytest.raises(AgentDelegationError) as exc_info:
        authorize_agent_delegation(
            delegated,
            parent_definition=parent,
            parent_profile=compiled(parent),
            child_definition=child,
            child_profile=compiled(child),
        )
    assert exc_info.value.code == "delegation_tool_widening"


def test_delegation_rejects_capability_widening() -> None:
    parent = definition("agent:padiem:parent@1")
    child = definition("agent:padiem:child@1")
    delegated = AgentDelegationRequest(
        delegation_id="delegation:test:3",
        parent_agent_id=parent.agent_id,
        child_agent_id=child.agent_id,
        reason="Attempt capability widening.",
        allowed_tools=("search",),
        capabilities=("admin",),
        max_steps=1,
        max_tool_calls=0,
        max_wall_seconds=30,
    )
    with pytest.raises(AgentDelegationError) as exc_info:
        authorize_agent_delegation(
            delegated,
            parent_definition=parent,
            parent_profile=compiled(parent),
            child_definition=child,
            child_profile=compiled(child),
        )
    assert exc_info.value.code == "delegation_capability_widening"


def test_delegation_rejects_budget_widening() -> None:
    parent = definition("agent:padiem:parent@1", max_steps=2, max_tool_calls=1, max_wall_seconds=30)
    child = definition("agent:padiem:child@1", max_steps=2, max_tool_calls=1, max_wall_seconds=30)
    delegated = AgentDelegationRequest(
        delegation_id="delegation:test:4",
        parent_agent_id=parent.agent_id,
        child_agent_id=child.agent_id,
        reason="Attempt budget widening.",
        allowed_tools=("search",),
        capabilities=("search",),
        max_steps=2,
        max_tool_calls=1,
        max_wall_seconds=31,
    )
    with pytest.raises(AgentDelegationError) as exc_info:
        authorize_agent_delegation(
            delegated,
            parent_definition=parent,
            parent_profile=compiled(parent),
            child_definition=child,
            child_profile=compiled(child),
        )
    assert exc_info.value.code == "delegation_budget_widening"


def test_delegation_rejects_depth_overflow() -> None:
    parent = definition("agent:padiem:parent@1")
    child = definition("agent:padiem:child@1")
    with pytest.raises(AgentDelegationError) as exc_info:
        authorize_agent_delegation(
            request(parent, child, depth=5),
            parent_definition=parent,
            parent_profile=compiled(parent),
            child_definition=child,
            child_profile=compiled(child),
        )
    assert exc_info.value.code == "delegation_budget_exceeded"


def test_delegation_rejects_child_count_overflow() -> None:
    parent = definition("agent:padiem:parent@1")
    child = definition("agent:padiem:child@1")
    with pytest.raises(AgentDelegationError) as exc_info:
        authorize_agent_delegation(
            request(parent, child),
            parent_definition=parent,
            parent_profile=compiled(parent),
            child_definition=child,
            child_profile=compiled(child),
            children_already_delegated=8,
        )
    assert exc_info.value.code == "delegation_budget_exceeded"


def test_event_is_normalized_and_redacts_non_scalar_payloads() -> None:
    event = public_agent_event(
        event_id="event:test:1",
        run_id="run:test:1",
        kind=AgentEventKind.TOOL_COMPLETED,
        sequence=2,
        metadata={"tool_id": "search", "approved": True, "bytes": 12},
    )
    assert event.to_public_dict() == {
        "event_id": "event:test:1",
        "run_id": "run:test:1",
        "kind": "tool_completed",
        "sequence": 2,
        "message": None,
        "metadata": {"tool_id": "search", "approved": True, "bytes": 12},
    }


def test_event_rejects_raw_nested_payload() -> None:
    with pytest.raises(AgentEventError):
        public_agent_event(
            event_id="event:test:2",
            run_id="run:test:1",
            kind=AgentEventKind.TOOL_REQUESTED,
            sequence=1,
            metadata={"arguments": {"secret": "x"}},
        )


@pytest.mark.parametrize(
    "valid_agent_id",
    [
        "agent:padiem:parent@1",
        "agent:owner:id@1",
        "agent:test-org:assistant-v2@42",
    ],
)
def test_delegation_accepts_canonical_agent_id(valid_agent_id: str) -> None:
    req = AgentDelegationRequest(
        delegation_id="delegation:test:valid",
        parent_agent_id=valid_agent_id,
        child_agent_id="agent:padiem:child@1",
        reason="Valid canonical identity test.",
        allowed_tools=("search",),
        capabilities=("search",),
    )
    assert req.parent_agent_id == valid_agent_id


@pytest.mark.parametrize(
    "invalid_agent_id",
    [
        "agent:owner:id",
        "agent:owner:id@",
        "agent:owner:id@x",
        "agent:owner:id@0",
        "agent::id@1",
        "agent:owner:@1",
    ],
)
def test_delegation_rejects_malformed_canonical_agent_id(invalid_agent_id: str) -> None:
    with pytest.raises(AgentDelegationError) as exc_info:
        AgentDelegationRequest(
            delegation_id="delegation:test:invalid",
            parent_agent_id=invalid_agent_id,
            child_agent_id="agent:padiem:child@1",
            reason="Invalid canonical identity test.",
            allowed_tools=("search",),
            capabilities=("search",),
        )
    assert exc_info.value.code == "invalid_agent_delegation"
