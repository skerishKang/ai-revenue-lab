"""Reuse PC evidence and delegation guards before a composite dispatch.

Actions are normalized existing file-tool invocations, never shell commands or
nested batch wrappers. A question means that no batch/job step may be dispatched.
Planned reads are marked as planned tool IDs, not fabricated result observations.
"""
from __future__ import annotations

from collections.abc import Mapping

from kagent.pc_query_adapter import (
    PC_FILE_WRITE_TOOL_IDS, PC_READ_FAMILY_TOOL_IDS, PC_FILE_TOOL_ARGUMENT_KEYS,
    pc_file_arguments_acceptable,
)


def preflight_pc_actions(
    actions, *, harness, delegation=None, observations=(), device_id=None, context=None,
) -> str | None:
    """Return the first existing guard question, or admit all validated actions.

    The caller must still enforce the run's tool scope, device ownership and
    dispatch-time authorization. This helper adds no grants and performs no I/O.
    """
    normalized = []
    for action in actions:
        if (not isinstance(action, (tuple, list)) or len(action) != 2
                or not isinstance(action[0], str) or not isinstance(action[1], Mapping)):
            raise ValueError("Invalid PC composite action")
        tool_id, arguments = action[0], dict(action[1])
        if (tool_id not in PC_READ_FAMILY_TOOL_IDS | PC_FILE_WRITE_TOOL_IDS
                or set(arguments) != PC_FILE_TOOL_ARGUMENT_KEYS[tool_id]
                or not pc_file_arguments_acceptable(tool_id, arguments)):
            raise ValueError("Invalid PC composite action")
        normalized.append((tool_id, arguments))
    if not normalized:
        raise ValueError("A PC composite action requires at least one operation")

    preceding = []
    for tool_id, arguments in normalized:
        question = harness.question(
            tool_id, arguments, observations=observations,
            preceding_tool_ids=tuple(preceding),
        )
        if question is not None:
            return question
        if delegation is not None:
            question = delegation.question(
                tool_id, arguments, records=harness.records,
                device_id=device_id, context=context,
            )
            if question is not None:
                return question
        preceding.append(tool_id)
    return None
