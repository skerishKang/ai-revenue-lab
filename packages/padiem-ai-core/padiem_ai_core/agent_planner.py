"""Bounded, non-authoritative planning contract for P01 Agent Runtime.

A plan is descriptive orchestration data. It is not a permission document and
cannot grant tools, connectors, entitlement, approval, or execution authority.
Actual execution remains in the existing bounded Agent Runtime + ToolRuntime.

The planner contract deliberately carries no private chain-of-thought field and
no executable tool arguments. A planner may propose only a bounded objective and
an already-compiled runtime tool id for a step.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from .agent_definition import BoundedAgentDefinition
from .agent_profile_adapter import CompiledAgentProfile


MAX_AGENT_PLAN_STEPS = 32
MAX_AGENT_PLAN_OBJECTIVE_CHARS = 1_000
MAX_AGENT_PLAN_INPUT_CHARS = 32_000
MAX_AGENT_PLAN_DEPENDENCIES = 16
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class AgentPlannerError(ValueError):
    """Safe validation failure at the planner contract boundary."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("agent planner error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message


def _identifier(name: str, value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise AgentPlannerError(
            "invalid_agent_plan",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _objective(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentPlannerError(
            "invalid_agent_plan",
            "plan step objective must be a non-empty string",
        )
    result = value.strip()
    if len(result) > MAX_AGENT_PLAN_OBJECTIVE_CHARS:
        raise AgentPlannerError(
            "agent_plan_budget_exceeded",
            "plan step objective exceeds the bounded planner limit",
        )
    return result


@dataclass(frozen=True, slots=True)
class AgentPlanStep:
    """One descriptive plan step; it contains no executable arguments."""

    step_id: str
    objective: str
    tool_id: str | None = None
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _identifier("step_id", self.step_id))
        object.__setattr__(self, "objective", _objective(self.objective))
        if self.tool_id is not None:
            object.__setattr__(self, "tool_id", _identifier("tool_id", self.tool_id))
        if isinstance(self.depends_on, (str, bytes)):
            raise AgentPlannerError(
                "invalid_agent_plan",
                "depends_on must be a tuple of step ids",
            )
        dependencies = tuple(_identifier("dependency step id", item) for item in self.depends_on)
        if len(dependencies) > MAX_AGENT_PLAN_DEPENDENCIES:
            raise AgentPlannerError(
                "agent_plan_budget_exceeded",
                "plan step has too many dependencies",
            )
        if len(set(dependencies)) != len(dependencies):
            raise AgentPlannerError(
                "invalid_agent_plan",
                "plan step dependencies must not contain duplicates",
            )
        if self.step_id in dependencies:
            raise AgentPlannerError(
                "invalid_agent_plan",
                "plan step cannot depend on itself",
            )
        object.__setattr__(self, "depends_on", dependencies)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "objective": self.objective,
            "tool_id": self.tool_id,
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True, slots=True)
class AgentPlan:
    """Validated finite plan tied to one canonical Agent definition."""

    agent_id: str
    steps: tuple[AgentPlanStep, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_id", _identifier("agent_id", self.agent_id))
        if not isinstance(self.steps, tuple):
            raise AgentPlannerError(
                "invalid_agent_plan",
                "steps must be a tuple",
            )
        if not 1 <= len(self.steps) <= MAX_AGENT_PLAN_STEPS:
            raise AgentPlannerError(
                "agent_plan_budget_exceeded",
                f"plan must contain 1 to {MAX_AGENT_PLAN_STEPS} steps",
            )
        if any(not isinstance(step, AgentPlanStep) for step in self.steps):
            raise AgentPlannerError(
                "invalid_agent_plan",
                "steps must contain AgentPlanStep values",
            )
        step_ids = tuple(step.step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise AgentPlannerError(
                "invalid_agent_plan",
                "plan step ids must be unique",
            )

        seen: set[str] = set()
        for step in self.steps:
            if any(dependency not in seen for dependency in step.depends_on):
                raise AgentPlannerError(
                    "invalid_agent_plan",
                    "plan dependencies must refer only to earlier steps",
                )
            seen.add(step.step_id)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "steps": [step.to_public_dict() for step in self.steps],
        }


class AgentPlanner(Protocol):
    """Provider-neutral planner seam; implementations cannot authorize execution."""

    async def plan(
        self,
        *,
        input_text: str,
        definition: BoundedAgentDefinition,
        compiled_profile: CompiledAgentProfile,
    ) -> AgentPlan: ...


def validate_agent_plan(
    plan: AgentPlan,
    *,
    definition: BoundedAgentDefinition,
    compiled_profile: CompiledAgentProfile,
) -> AgentPlan:
    """Validate a proposed plan against trusted compiled runtime authority.

    Plan validation is intentionally narrow: it proves finite structure and
    allowed tool references. It does not authorize a tool invocation; the
    existing ToolRuntime must re-check every actual invocation independently.
    """

    if not isinstance(plan, AgentPlan):
        raise AgentPlannerError(
            "invalid_agent_plan",
            "plan must be AgentPlan",
        )
    if not isinstance(definition, BoundedAgentDefinition):
        raise AgentPlannerError(
            "invalid_agent_plan_context",
            "definition must be BoundedAgentDefinition",
        )
    if not isinstance(compiled_profile, CompiledAgentProfile):
        raise AgentPlannerError(
            "invalid_agent_plan_context",
            "compiled_profile must be CompiledAgentProfile",
        )
    if plan.agent_id != definition.agent_id:
        raise AgentPlannerError(
            "agent_plan_identity_mismatch",
            "plan does not belong to the requested Agent",
        )
    if compiled_profile.canonical_agent_id != definition.agent_id:
        raise AgentPlannerError(
            "agent_plan_identity_mismatch",
            "compiled profile does not belong to the requested Agent",
        )

    max_steps = min(
        MAX_AGENT_PLAN_STEPS,
        definition.execution_budget.max_steps,
        compiled_profile.runtime_profile.max_steps,
    )
    if len(plan.steps) > max_steps:
        raise AgentPlannerError(
            "agent_plan_budget_exceeded",
            "plan exceeds the trusted Agent step budget",
        )

    allowed_runtime_tools = frozenset(compiled_profile.runtime_profile.allowed_tools)
    planned_tool_calls = 0
    for step in plan.steps:
        if step.tool_id is None:
            continue
        planned_tool_calls += 1
        if step.tool_id not in allowed_runtime_tools:
            raise AgentPlannerError(
                "agent_plan_tool_not_allowed",
                "plan references a tool outside the trusted compiled profile",
            )

    if planned_tool_calls > definition.execution_budget.max_tool_calls:
        raise AgentPlannerError(
            "agent_plan_budget_exceeded",
            "plan exceeds the trusted Agent tool-call budget",
        )

    return plan


def validate_agent_plan_input(input_text: str) -> str:
    """Bound planner input without storing or exposing hidden reasoning."""

    if not isinstance(input_text, str) or not input_text.strip():
        raise AgentPlannerError(
            "invalid_agent_plan_input",
            "planner input must be a non-empty string",
        )
    result = input_text.strip()
    if len(result) > MAX_AGENT_PLAN_INPUT_CHARS:
        raise AgentPlannerError(
            "agent_plan_budget_exceeded",
            "planner input exceeds the bounded input limit",
        )
    return result
