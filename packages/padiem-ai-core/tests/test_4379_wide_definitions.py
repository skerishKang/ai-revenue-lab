"""#4379 focused: no PADIEM count, length or byte ceiling on a definition or a Tool.

Network-free. No provider call, no production mutation, no secret.
"""
from __future__ import annotations

import pytest

from padiem_ai_core.agent_definition import (
    AgentApprovalCheckpoint,
    AgentDefinitionError,
    AgentExecutionBudget,
    BoundedAgentDefinition,
)
from padiem_ai_core.skill_package import SkillPackageError
from padiem_ai_core.tool_runtime import ToolExecutionResult, ToolInvocation


def _definition(**overrides):
    values = {
        "agent_id": "agent:padiem:wide@1",
        "publisher_id": "publisher:padiem",
        "title": "Wide agent",
        "description": "An agent with a large definition.",
        "instruction": "Work on the task.",
        "output_contract_ref": "io:answer@1",
        "allowed_tool_ids": (),
        "required_capabilities": ("chat",),
        "context_policy_ref": "context:default@1",
        "model_policy_ref": "model:auto@1",
        "execution_budget": AgentExecutionBudget(),
    }
    values.update(overrides)
    return BoundedAgentDefinition(**values)


def test_a_long_agent_instruction_is_accepted() -> None:
    instruction = "자" * 40_000
    definition = _definition(instruction=instruction, description="설명" * 5_000)
    assert definition.instruction == instruction
    assert len(definition.description) == 10_000


def test_a_large_agent_item_list_is_accepted() -> None:
    tool_ids = tuple(
        f"tool:padiem:tool_{index}@1" for index in range(200)
    )
    skill_ids = tuple(
        f"skill:padiem:skill_{index}@1" for index in range(100)
    )
    connector_ids = tuple(
        f"connector:padiem:connector_{index}@1" for index in range(100)
    )
    capabilities = tuple(f"capability_{index}" for index in range(100))
    definition = _definition(
        allowed_tool_ids=tool_ids,
        skill_package_ids=skill_ids,
        connector_requirement_ids=connector_ids,
        required_capabilities=capabilities,
    )
    assert len(definition.allowed_tool_ids) == 200
    assert len(definition.skill_package_ids) == 100
    assert len(definition.required_capabilities) == 100


def test_the_agent_definition_shape_is_still_validated() -> None:
    # The grammar, the duplicate check and the non-empty rule still fail closed.
    with pytest.raises(AgentDefinitionError):
        _definition(title="")
    with pytest.raises(AgentDefinitionError):
        _definition(allowed_tool_ids=("tool:padiem:same@1", "tool:padiem:same@1"))
    with pytest.raises(AgentDefinitionError):
        _definition(allowed_tool_ids=("not-a-canonical-tool-id",))
    with pytest.raises(AgentDefinitionError):
        _definition(required_capabilities=("chat", "chat"))


def test_a_large_tool_argument_and_result_are_kept() -> None:
    # #4379: a Tool argument or result is not refused for its size. The JSON
    # shape and the identifier grammar still apply.
    payload = {"value": "x" * 500_000}
    invocation = ToolInvocation("core.echo", payload)
    assert invocation.arguments_copy() == payload
    result = ToolExecutionResult(
        tool_id="core.echo",
        output=payload,
        event=_completed_event("core.echo"),
    )
    assert result.output_copy() == payload


def _completed_event(tool_id: str):
    from padiem_ai_core.contracts import RunStatus, ToolEvent

    return ToolEvent(tool_id=tool_id, status=RunStatus.COMPLETED)


def test_the_skill_package_text_is_not_length_capped() -> None:
    from padiem_ai_core.skill_package import ReusableSkillPackage

    instruction = "지" * 40_000
    package = ReusableSkillPackage(
        skill_id="skill:padiem:wide@1",
        publisher_id="publisher:padiem",
        description="설명" * 5_000,
        instruction=instruction,
        input_contract_ref="io:input@1",
        output_contract_ref="io:output@1",
        allowed_tool_ids=(),
        required_capabilities=(),
    )
    assert package.instruction == instruction
    with pytest.raises(SkillPackageError):
        ReusableSkillPackage(
            skill_id="skill:padiem:wide@1",
            publisher_id="publisher:padiem",
            description="",
            instruction="지",
            input_contract_ref="io:input@1",
            output_contract_ref="io:output@1",
            allowed_tool_ids=(),
            required_capabilities=(),
        )


def test_a_durable_lease_accepts_a_checkpoint_step_beyond_the_old_ceiling() -> None:
    # #4379: the durable lease checkpoint step is a progress record, not a
    # PADIEM ceiling. A long run may reach any step number.
    from padiem_ai_core.agent_durable_lease import (
        AgentDurableLeaseError,
        AgentRunLease,
        SQLiteAgentDurableRunLedger,
    )

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteAgentDurableRunLedger(
            database_path=Path(directory) / "lease.sqlite3",
        )
        handle = AgentRunLease(
            run_id="run_" + "a" * 24,
            owner_scope="scope_" + "b" * 64,
            request_fingerprint="c" * 64,
            worker_id="worker_local",
            epoch=1,
        )
        ledger.begin_execution(handle)
        # A step beyond the old ceiling is accepted, not refused: the run keeps
        # going and the recorded progress is capped at what the column holds.
        ledger.checkpoint(handle, completed_step=101)
        with pytest.raises(AgentDurableLeaseError):
            ledger.checkpoint(handle, completed_step=-1)
