"""Bounded Agent execution loop for Padiem AI Core.

This module coordinates a provider-neutral Agent step driver with the existing
fail-closed ToolRuntime. The step driver may be backed by B14 later, but this
contract does not invent a Provider/tool-calling wire schema before Business 14
freezes that surface.

The runtime is intentionally bounded:
- no sub-agent delegation;
- explicit step/tool/wall-time budgets;
- tools execute only through ToolRuntime + trusted ToolAuthorizationContext;
- approval-required ToolRuntime errors become a pause checkpoint;
- raw pending tool arguments are server-state only and are omitted from the
  public result projection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
import time
from typing import Protocol
import uuid

from .agent_approval import ApprovalPause, approval_pause_from_tool_error
from .agent_definition import AgentTerminalReason, BoundedAgentDefinition
from .agent_profile_adapter import CompiledAgentProfile
from .contracts import RunStatus, ToolEvent
from .tool_runtime import (
    ToolAuthorizationContext,
    ToolExecutionResult,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeError,
)


MAX_AGENT_INPUT_CHARS = 32_000
MAX_AGENT_ANSWER_CHARS = 65_536
MAX_APPROVAL_PAUSE_SECONDS = 86_400
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


class AgentRuntimeError(RuntimeError):
    """Safe Agent runtime contract failure."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ValueError("agent runtime error code must be a safe identifier")
        self.code = code
        self.safe_message = safe_message

    def to_public_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.safe_message}


class AgentStepKind(str, Enum):
    COMPLETE = "complete"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class AgentStepDecision:
    kind: AgentStepKind
    answer: str | None = None
    invocation: ToolInvocation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AgentStepKind):
            raise AgentRuntimeError(
                "invalid_agent_step",
                "Agent step kind is invalid.",
            )
        if self.kind is AgentStepKind.COMPLETE:
            if self.invocation is not None:
                raise AgentRuntimeError(
                    "invalid_agent_step",
                    "Completed Agent step cannot contain a tool invocation.",
                )
            if not isinstance(self.answer, str) or not self.answer.strip():
                raise AgentRuntimeError(
                    "invalid_agent_step",
                    "Completed Agent step requires an answer.",
                )
            answer = self.answer.strip()
            if len(answer) > MAX_AGENT_ANSWER_CHARS:
                raise AgentRuntimeError(
                    "agent_answer_too_large",
                    "Agent answer exceeded the bounded output limit.",
                )
            object.__setattr__(self, "answer", answer)
            return

        if self.answer is not None:
            raise AgentRuntimeError(
                "invalid_agent_step",
                "Tool Agent step cannot contain a completed answer.",
            )
        if not isinstance(self.invocation, ToolInvocation):
            raise AgentRuntimeError(
                "invalid_agent_step",
                "Tool Agent step requires a ToolInvocation.",
            )

    @classmethod
    def complete(cls, answer: str) -> "AgentStepDecision":
        return cls(kind=AgentStepKind.COMPLETE, answer=answer)

    @classmethod
    def use_tool(cls, invocation: ToolInvocation) -> "AgentStepDecision":
        return cls(kind=AgentStepKind.TOOL, invocation=invocation)


@dataclass(frozen=True, slots=True)
class AgentStepContext:
    run_id: str
    step_index: int
    input_text: str
    tool_results: tuple[ToolExecutionResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _IDENTIFIER_RE.fullmatch(
            self.run_id
        ):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "run_id must be a bounded safe identifier.",
            )
        if (
            isinstance(self.step_index, bool)
            or not isinstance(self.step_index, int)
            or not 1 <= self.step_index <= 64
        ):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "step_index must be between 1 and 64.",
            )
        if not isinstance(self.input_text, str) or not self.input_text.strip():
            raise AgentRuntimeError(
                "invalid_agent_run",
                "Agent input must be a non-empty string.",
            )
        text = self.input_text.strip()
        if len(text) > MAX_AGENT_INPUT_CHARS:
            raise AgentRuntimeError(
                "invalid_agent_run",
                "Agent input exceeded the bounded input limit.",
            )
        object.__setattr__(self, "input_text", text)
        if not isinstance(self.tool_results, tuple):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "tool_results must be a tuple.",
            )
        if any(not isinstance(item, ToolExecutionResult) for item in self.tool_results):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "tool_results must contain ToolExecutionResult values.",
            )


class AgentStepDriver(Protocol):
    """Provider-neutral next-step driver.

    A future B14-backed implementation may produce these decisions after the
    model-native tool/structured-step wire contract is frozen. The Core loop
    itself does not parse Provider-specific tool-call payloads.
    """

    async def next_step(
        self,
        context: AgentStepContext,
        compiled_profile: CompiledAgentProfile,
    ) -> AgentStepDecision: ...


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    definition: BoundedAgentDefinition
    compiled_profile: CompiledAgentProfile
    authorization: ToolAuthorizationContext
    input_text: str
    run_id: str | None = None
    initial_step_index: int = 1
    initial_tool_results: tuple[ToolExecutionResult, ...] = ()
    initial_tool_events: tuple[ToolEvent, ...] = ()
    trace_id: str | None = None
    plan_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.definition, BoundedAgentDefinition):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "definition must be BoundedAgentDefinition.",
            )
        if not isinstance(self.compiled_profile, CompiledAgentProfile):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "compiled_profile must be CompiledAgentProfile.",
            )
        if self.compiled_profile.canonical_agent_id != self.definition.agent_id:
            raise AgentRuntimeError(
                "agent_profile_mismatch",
                "Compiled profile does not belong to the requested Agent.",
            )
        if not isinstance(self.authorization, ToolAuthorizationContext):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "authorization must be ToolAuthorizationContext.",
            )
        if self.authorization.agent_id != self.compiled_profile.runtime_profile.id:
            raise AgentRuntimeError(
                "agent_authorization_mismatch",
                "Authorization does not match the compiled Agent runtime profile.",
            )
        if not isinstance(self.input_text, str) or not self.input_text.strip():
            raise AgentRuntimeError(
                "invalid_agent_run",
                "Agent input must be a non-empty string.",
            )
        text = self.input_text.strip()
        if len(text) > MAX_AGENT_INPUT_CHARS:
            raise AgentRuntimeError(
                "invalid_agent_run",
                "Agent input exceeded the bounded input limit.",
            )
        object.__setattr__(self, "input_text", text)
        if self.run_id is not None and (
            not isinstance(self.run_id, str)
            or not _IDENTIFIER_RE.fullmatch(self.run_id)
        ):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "run_id must be a bounded safe identifier.",
            )
        if isinstance(self.initial_step_index, bool) or not isinstance(self.initial_step_index, int) or self.initial_step_index < 1:
            raise AgentRuntimeError(
                "invalid_agent_run",
                "initial_step_index must be an integer >= 1.",
            )
        if self.trace_id is not None and (
            not isinstance(self.trace_id, str) or not _IDENTIFIER_RE.fullmatch(self.trace_id)
        ):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "trace_id must be a bounded safe identifier.",
            )
        if self.plan_id is not None and (
            not isinstance(self.plan_id, str) or not _IDENTIFIER_RE.fullmatch(self.plan_id)
        ):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "plan_id must be a bounded safe identifier.",
            )


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run_id: str
    terminal_reason: AgentTerminalReason
    steps_executed: int
    tool_calls: int
    tool_events: tuple[ToolEvent, ...] = ()
    answer: str | None = None
    approval_pause: ApprovalPause | None = None
    pending_invocation: ToolInvocation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not _IDENTIFIER_RE.fullmatch(
            self.run_id
        ):
            raise AgentRuntimeError(
                "invalid_agent_result",
                "run_id must be a bounded safe identifier.",
            )
        if not isinstance(self.terminal_reason, AgentTerminalReason):
            raise AgentRuntimeError(
                "invalid_agent_result",
                "terminal_reason must be AgentTerminalReason.",
            )
        for name in ("steps_executed", "tool_calls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AgentRuntimeError(
                    "invalid_agent_result",
                    f"{name} must be a non-negative integer.",
                )
        if not isinstance(self.tool_events, tuple) or any(
            not isinstance(event, ToolEvent) for event in self.tool_events
        ):
            raise AgentRuntimeError(
                "invalid_agent_result",
                "tool_events must contain ToolEvent values.",
            )

        if self.terminal_reason is AgentTerminalReason.COMPLETED:
            if not isinstance(self.answer, str) or not self.answer.strip():
                raise AgentRuntimeError(
                    "invalid_agent_result",
                    "Completed Agent result requires an answer.",
                )
            if self.approval_pause is not None or self.pending_invocation is not None:
                raise AgentRuntimeError(
                    "invalid_agent_result",
                    "Completed Agent result cannot contain approval state.",
                )
            object.__setattr__(self, "answer", self.answer.strip())
        elif self.terminal_reason is AgentTerminalReason.APPROVAL_REQUIRED:
            if not isinstance(self.approval_pause, ApprovalPause):
                raise AgentRuntimeError(
                    "invalid_agent_result",
                    "Approval-required result requires ApprovalPause.",
                )
            if not isinstance(self.pending_invocation, ToolInvocation):
                raise AgentRuntimeError(
                    "invalid_agent_result",
                    "Approval-required result requires pending invocation state.",
                )
            if self.answer is not None:
                raise AgentRuntimeError(
                    "invalid_agent_result",
                    "Approval-required result cannot contain a completed answer.",
                )
        elif (
            self.answer is not None
            or self.approval_pause is not None
            or self.pending_invocation is not None
        ):
            raise AgentRuntimeError(
                "invalid_agent_result",
                "Non-completed Agent result contains incompatible payload.",
            )

    def to_public_dict(self) -> dict[str, object]:
        pause = None
        if self.approval_pause is not None:
            pause = {
                "pause_id": self.approval_pause.pause_id,
                "run_id": self.approval_pause.run_id,
                "tool_id": self.approval_pause.tool_id,
                "requirement": self.approval_pause.requirement.value,
                "step_index": self.approval_pause.step_index,
                "expires_at": self.approval_pause.expires_at.isoformat(),
            }
        return {
            "run_id": self.run_id,
            "terminal_reason": self.terminal_reason.value,
            "steps_executed": self.steps_executed,
            "tool_calls": self.tool_calls,
            "tool_events": [event.to_public_dict() for event in self.tool_events],
            "answer": self.answer,
            "approval_pause": pause,
        }


class BoundedAgentRuntime:
    def __init__(
        self,
        *,
        step_driver: AgentStepDriver,
        tool_runtime: ToolRuntime,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        approval_pause_seconds: int = 900,
    ) -> None:
        next_step = getattr(step_driver, "next_step", None)
        if not callable(next_step):
            raise ValueError("step_driver must expose async next_step(...)")
        if not isinstance(tool_runtime, ToolRuntime):
            raise ValueError("tool_runtime must be ToolRuntime")
        if not callable(clock):
            raise ValueError("clock must be callable")
        if now is not None and not callable(now):
            raise ValueError("now must be callable")
        if id_factory is not None and not callable(id_factory):
            raise ValueError("id_factory must be callable")
        if (
            isinstance(approval_pause_seconds, bool)
            or not isinstance(approval_pause_seconds, int)
            or not 1 <= approval_pause_seconds <= MAX_APPROVAL_PAUSE_SECONDS
        ):
            raise ValueError(
                f"approval_pause_seconds must be between 1 and {MAX_APPROVAL_PAUSE_SECONDS}"
            )
        self._step_driver = step_driver
        self._tool_runtime = tool_runtime
        self._clock = clock
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._approval_pause_seconds = approval_pause_seconds

    def _new_identifier(self, prefix: str) -> str:
        raw = self._id_factory()
        if not isinstance(raw, str):
            raise AgentRuntimeError(
                "invalid_agent_runtime_id",
                "Agent runtime identifier source returned an invalid value.",
            )
        cleaned = re.sub(r"[^A-Za-z0-9._:-]", "", raw)
        value = f"{prefix}:{cleaned[:80]}"
        if not cleaned or not _IDENTIFIER_RE.fullmatch(value):
            raise AgentRuntimeError(
                "invalid_agent_runtime_id",
                "Agent runtime identifier source returned an invalid value.",
            )
        return value

    def _elapsed(self, started: float) -> float:
        return max(0.0, float(self._clock() - started))

    def _remaining_wall_seconds(
        self,
        *,
        started: float,
        budget_seconds: int,
    ) -> float:
        return max(0.0, float(budget_seconds) - self._elapsed(started))

    def _terminal(
        self,
        *,
        run_id: str,
        reason: AgentTerminalReason,
        steps: int,
        tool_calls: int,
        tool_events: list[ToolEvent],
    ) -> AgentRunResult:
        return AgentRunResult(
            run_id=run_id,
            terminal_reason=reason,
            steps_executed=steps,
            tool_calls=tool_calls,
            tool_events=tuple(tool_events),
        )

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        if not isinstance(request, AgentRunRequest):
            raise ValueError("request must be AgentRunRequest")

        run_id = request.run_id or self._new_identifier("run")
        started = self._clock()
        budget = request.definition.execution_budget
        max_steps = min(
            budget.max_steps,
            request.compiled_profile.runtime_profile.max_steps,
        )
        tool_results: list[ToolExecutionResult] = list(request.initial_tool_results)
        tool_events: list[ToolEvent] = list(request.initial_tool_events)
        tool_calls = len(tool_results)

        for step_index in range(request.initial_step_index, max_steps + 1):
            remaining = self._remaining_wall_seconds(
                started=started,
                budget_seconds=budget.max_wall_seconds,
            )
            if remaining <= 0:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index - 1,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )

            context = AgentStepContext(
                run_id=run_id,
                step_index=step_index,
                input_text=request.input_text,
                tool_results=tuple(tool_results),
            )
            try:
                decision = await asyncio.wait_for(
                    self._step_driver.next_step(
                        context,
                        request.compiled_profile,
                    ),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index - 1,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )
            except asyncio.CancelledError:
                raise
            except AgentRuntimeError:
                raise
            except Exception:
                raise AgentRuntimeError(
                    "agent_step_failed",
                    "Agent step execution failed.",
                ) from None

            if not isinstance(decision, AgentStepDecision):
                raise AgentRuntimeError(
                    "invalid_agent_step",
                    "Agent step driver returned an invalid decision.",
                )

            if self._remaining_wall_seconds(
                started=started,
                budget_seconds=budget.max_wall_seconds,
            ) <= 0:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )

            if decision.kind is AgentStepKind.COMPLETE:
                return AgentRunResult(
                    run_id=run_id,
                    terminal_reason=AgentTerminalReason.COMPLETED,
                    steps_executed=step_index,
                    tool_calls=tool_calls,
                    tool_events=tuple(tool_events),
                    answer=decision.answer,
                )

            invocation = decision.invocation
            assert isinstance(invocation, ToolInvocation)

            if tool_calls >= budget.max_tool_calls:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_TOOL_CALLS,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )
            tool_calls += 1

            remaining = self._remaining_wall_seconds(
                started=started,
                budget_seconds=budget.max_wall_seconds,
            )
            if remaining <= 0:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )

            try:
                tool_result = await asyncio.wait_for(
                    self._tool_runtime.execute(
                        invocation,
                        request.compiled_profile.runtime_profile,
                        request.authorization,
                    ),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )
            except asyncio.CancelledError:
                raise
            except ToolRuntimeError as exc:
                if exc.event is not None:
                    tool_events.append(exc.event)

                pause = None
                if exc.code in {
                    "tool_user_confirmation_required",
                    "tool_external_authorization_required",
                }:
                    created_at = self._now()
                    if (
                        not isinstance(created_at, datetime)
                        or created_at.tzinfo is None
                        or created_at.utcoffset() is None
                    ):
                        raise AgentRuntimeError(
                            "invalid_agent_clock",
                            "Agent approval clock returned an invalid timestamp.",
                        )
                    pause = approval_pause_from_tool_error(
                        exc,
                        pause_id=self._new_identifier("pause"),
                        run_id=run_id,
                        agent_runtime_id=request.compiled_profile.runtime_profile.id,
                        invocation=invocation,
                        step_index=step_index,
                        created_at=created_at,
                        expires_at=created_at
                        + timedelta(seconds=self._approval_pause_seconds),
                        trace_id=request.trace_id,
                        plan_id=request.plan_id,
                    )
                if pause is not None:
                    return AgentRunResult(
                        run_id=run_id,
                        terminal_reason=AgentTerminalReason.APPROVAL_REQUIRED,
                        steps_executed=step_index,
                        tool_calls=tool_calls,
                        tool_events=tuple(tool_events),
                        approval_pause=pause,
                        pending_invocation=invocation,
                    )

                if (
                    exc.event is not None
                    and exc.event.status is RunStatus.POLICY_BLOCKED
                ):
                    return self._terminal(
                        run_id=run_id,
                        reason=AgentTerminalReason.AUTHORIZATION_DENIED,
                        steps=step_index,
                        tool_calls=tool_calls,
                        tool_events=tool_events,
                    )
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.ERROR,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )

            tool_results.append(tool_result)
            tool_events.append(tool_result.event)
            if self._remaining_wall_seconds(
                started=started,
                budget_seconds=budget.max_wall_seconds,
            ) <= 0:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )

        return self._terminal(
            run_id=run_id,
            reason=AgentTerminalReason.MAX_STEPS,
            steps=max_steps,
            tool_calls=tool_calls,
            tool_events=tool_events,
        )
