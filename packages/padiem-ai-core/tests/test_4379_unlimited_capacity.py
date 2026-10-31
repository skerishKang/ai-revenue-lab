"""#4379: PADIEM must not refuse or shorten a model result by size.

Network-free. No provider call, no production mutation, no secret.

The Engine used to refuse any B14 request body larger than 256 KB, used the
completed-response byte budget as the streaming budget too, and cut every tool
result string at 2,048 characters. Chat refused a B66 model answer longer than
2,000 characters, cut the B66 conversation prompt, and refused a local run
result larger than 768 bytes. The agent runtime stopped at a fixed step count
and the execution context rejected a timeout above one hour.
"""
from __future__ import annotations

import pytest

from padiem_ai_core.agent_definition import AgentExecutionBudget
from padiem_ai_core.agent_profile_adapter import (
    TrustedAgentRuntimePolicy,
    effective_max_steps,
    effective_max_tokens,
)
from padiem_ai_core.execution_context import ExecutionContext


def test_execution_context_accepts_a_long_running_timeout():
    # #4379: the declared execution timeout had a one-hour PADIEM ceiling.
    context = ExecutionContext(trace_id="trace", timeout_seconds=86_400.0)
    assert context.timeout_seconds == 86_400.0


def test_execution_budget_has_no_step_or_tool_count_ceiling():
    budget = AgentExecutionBudget()
    assert budget.max_steps is None
    assert budget.max_tool_calls is None
    assert budget.max_skill_calls is None
    # The inactivity window stays: it ends a run that stops making progress.
    assert budget.max_wall_seconds == 1800
    assert budget.max_total_seconds is None


def test_effective_budget_prefers_the_explicit_ceiling_when_one_exists():
    # An explicit opt-in ceiling still applies; the tighter of two wins.
    assert effective_max_steps(None, None) is None
    assert effective_max_steps(None, 5) == 5
    assert effective_max_steps(4, None) == 4
    assert effective_max_steps(4, 9) == 4
    assert effective_max_steps(9, 4) == 4
    assert effective_max_tokens(None, None) is None
    assert effective_max_tokens(None, 128) == 128
    assert effective_max_tokens(64, None) == 64
    assert effective_max_tokens(64, 128) == 64


def test_profile_policy_accepts_no_step_cap_and_no_output_budget():
    policy = TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=None,
        max_steps_cap=None,
        context_policy={},
        model_policy={},
        output_contract={},
    )
    assert policy.max_tokens is None
    assert policy.max_steps_cap is None
