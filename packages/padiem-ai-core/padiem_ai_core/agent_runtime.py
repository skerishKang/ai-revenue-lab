"""Bounded Agent execution loop for Padiem AI Core.

This module coordinates a provider-neutral Agent step driver with the existing
fail-closed ToolRuntime. The step driver may be backed by B14 later, but this
contract does not invent a Provider/tool-calling wire schema before Business 14
freezes that surface.

The runtime is intentionally bounded:
- no sub-agent delegation;
- explicit step/tool count budgets and an inactivity (idle) watchdog, never a
  fixed total wall clock that force-fails a run for making progress (#4194);
- tools execute only through ToolRuntime + trusted ToolAuthorizationContext;
- approval-required ToolRuntime errors become a pause checkpoint;
- raw pending tool arguments are server-state only and are omitted from the
  public result projection.

The idle window is measured from the last *verified* progress event (a step
decision returned by the driver, a completed Tool result, or a persisted
durable checkpoint). A healthy long run therefore keeps its own budget while a
stalled run still fails closed inside the window as ``MAX_WALL_TIME``.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
import time
from typing import Protocol
import uuid

from ._pc_core_invoke import pc_core_log, pc_core_stage
from .agent_approval import ApprovalPause, approval_pause_from_tool_error
from .agent_definition import AgentTerminalReason, BoundedAgentDefinition
from .agent_profile_adapter import CompiledAgentProfile, effective_max_steps
from .agent_progress import AgentProgressTracker
from .agent_tool_result_ledger import (
    InMemoryToolResultLedger,
    ToolResultLedger,
    ToolResultRef,
)
from .contracts import RunStatus, ToolEvent
from .tool_runtime import (
    ToolAuthorizationContext,
    ToolExecutionResult,
    ToolInvocation,
    ToolRuntime,
    ToolRuntimeError,
)


MAX_APPROVAL_PAUSE_SECONDS = 86_400
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
# #5015: a step driver may name its own failure with a bounded lowercase
# detail code. Core keeps only that shape-checked identifier and never reads
# the exception text, so a product can classify its own step failure (an
# unparsable model answer, an unauthorized tool choice, a model-call error)
# without Core importing product modules or inventing a telemetry system.
_STEP_FAILURE_DETAIL_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


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


def step_failure_code(exc: BaseException) -> str:
    """The bounded public code for a step-driver failure (#5015).

    A driver marks its own closed detail on the exception it raises; anything
    else keeps the previous generic code. Only the identifier shape crosses
    this boundary: the exception message, the model answer and every other
    value stay where they were raised.
    """
    detail = getattr(exc, "code", None)
    if isinstance(detail, str) and _STEP_FAILURE_DETAIL_RE.fullmatch(detail):
        return f"agent_step_failed.{detail}"
    return "agent_step_failed"


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
            # #4379: the completed answer is not bounded by a PADIEM character
            # count. The provider's own output limit and the platform decide
            # how much text a model can produce.
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
    tool_result_refs: tuple[ToolResultRef, ...]
    result_ledger: ToolResultLedger

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
            or self.step_index < 1
        ):
            # #4379: a step index is not a PADIEM quantity. A long run may
            # reach any step number; the inactivity watchdog, the durable lease
            # and cancellation still end it.
            raise AgentRuntimeError(
                "invalid_agent_run",
                "step_index must be a positive integer.",
            )
        if not isinstance(self.input_text, str) or not self.input_text.strip():
            raise AgentRuntimeError(
                "invalid_agent_run",
                "Agent input must be a non-empty string.",
            )
        text = self.input_text.strip()
        # #4379: the Agent input is not bounded by a PADIEM character count.
        object.__setattr__(self, "input_text", text)
        if not isinstance(self.tool_result_refs, tuple):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "tool_result_refs must be a tuple.",
            )
        if any(not isinstance(item, ToolResultRef) for item in self.tool_result_refs):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "tool_result_refs must contain ToolResultRef values.",
            )
        if not hasattr(self.result_ledger, "resolve"):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "result_ledger must be a ToolResultLedger.",
            )

    async def resolve_tool_result(self, ref: ToolResultRef) -> ToolExecutionResult:
        """Resolve one earlier tool result through its authorized reference.

        The runtime never holds the payload; the driver asks the ledger for the
        result it needs, so a long run does not retain every output in memory.
        """
        return await self.result_ledger.resolve(ref)

    async def resolve_tool_results(self) -> tuple[ToolExecutionResult, ...]:
        """Resolve every earlier tool result, in call order."""
        return tuple(
            [await self.result_ledger.resolve(ref) for ref in self.tool_result_refs]
        )


    @classmethod
    def with_results(
        cls,
        *,
        run_id: str,
        step_index: int,
        input_text: str,
        results: tuple[ToolExecutionResult, ...] = (),
    ) -> "AgentStepContext":
        """Build a context for results a host already holds.

        The payloads go into a process-local ledger and the context keeps only
        the references, exactly like the runtime does.
        """
        ledger = InMemoryToolResultLedger()
        refs = ledger.adopt(
            run_id=run_id, step_index=step_index, results=results,
        )
        return cls(
            run_id=run_id,
            step_index=step_index,
            input_text=input_text,
            tool_result_refs=refs,
            result_ledger=ledger,
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
    initial_tool_result_refs: tuple[ToolResultRef, ...] = ()
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
        # #4379: the Agent input is not bounded by a PADIEM character count.
        object.__setattr__(self, "input_text", text)
        if not isinstance(self.initial_tool_result_refs, tuple) or any(
            not isinstance(item, ToolResultRef) for item in self.initial_tool_result_refs
        ):
            raise AgentRuntimeError(
                "invalid_agent_run",
                "initial_tool_result_refs must contain ToolResultRef values.",
            )
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
        run_guard: Callable[[], bool | Awaitable[bool]] | None = None,
        checkpoint_hook: Callable[[int], bool | Awaitable[bool]] | None = None,
        progress: AgentProgressTracker | None = None,
        result_ledger: ToolResultLedger | None = None,
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
        if run_guard is not None and not callable(run_guard):
            raise ValueError("run_guard must be callable when configured")
        self._run_guard = run_guard
        if checkpoint_hook is not None and not callable(checkpoint_hook):
            raise ValueError("checkpoint_hook must be callable when configured")
        if progress is not None and not isinstance(progress, AgentProgressTracker):
            raise ValueError("progress must be AgentProgressTracker when configured")
        if result_ledger is not None and not hasattr(result_ledger, "resolve"):
            raise ValueError("result_ledger must be a ToolResultLedger")
        self._checkpoint_hook = checkpoint_hook
        # #4379: the ledger owns the tool payloads. The runtime keeps only the
        # references, so the retained memory of a long run scales with the
        # number of calls, not with the size of their outputs.
        self._result_ledger = result_ledger or InMemoryToolResultLedger()
        self._approval_pause_seconds = approval_pause_seconds
        # Shared with a trusted host (Engine/orchestration) so an outer
        # inactivity watchdog observes the same real progress events.
        self._progress = progress or AgentProgressTracker(clock=clock)

    @property
    def progress(self) -> AgentProgressTracker:
        """Liveness tracker for this runtime; not an authorization signal."""
        return self._progress

    def _record_progress(self, phase: str) -> None:
        self._progress.touch(phase)

    def _idle_remaining(self, idle_seconds: float) -> float:
        return self._progress.remaining_idle_seconds(idle_seconds)

    def _total_cap_reached(self, *, started: float, total_cap: int | None) -> bool:
        """Only an explicit host-opted ceiling stops a progressing run."""
        if total_cap is None:
            return False
        return self._elapsed(started) >= float(total_cap)

    async def _ensure_run_active(self, *, diagnostic_tool_id: str | None = None) -> None:
        """Fail closed before model/tool dispatch when durable lease is revoked.

        Trusted hosts inject an owner/fingerprint-scoped ledger guard. This
        does not signal a running external Tool or replace Tool idempotency.
        """
        with pc_core_stage("run_guard", diagnostic_tool_id,
                           guard_injected=self._run_guard is not None):
            if self._run_guard is None:
                return
            try:
                active = self._run_guard()
                if inspect.isawaitable(active):
                    active = await active
            except Exception:
                active = False
        if active is not True:
            raise AgentRuntimeError("agent_run_fenced", "Agent run is no longer active.")

    async def _record_trusted_checkpoint(self, step_index: int) -> None:
        """Durable progress metadata only, NOT authorization for Tool replay."""
        if self._checkpoint_hook is None:
            return
        try:
            recorded = self._checkpoint_hook(step_index)
            if inspect.isawaitable(recorded):
                recorded = await recorded
        except Exception:
            recorded = False
        if recorded is not True:
            raise AgentRuntimeError("agent_checkpoint_unavailable", "Agent checkpoint was not persisted.")

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

    def _total_cap_terminal(
        self,
        *,
        run_id: str,
        steps: int,
        tool_calls: int,
        tool_events: list[ToolEvent],
    ) -> AgentRunResult:
        """Only an explicit host-opted total ceiling reaches this path."""
        return self._terminal(
            run_id=run_id,
            reason=AgentTerminalReason.MAX_WALL_TIME,
            steps=steps,
            tool_calls=tool_calls,
            tool_events=tool_events,
        )

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        if not isinstance(request, AgentRunRequest):
            raise ValueError("request must be AgentRunRequest")

        run_id = request.run_id or self._new_identifier("run")
        started = self._clock()
        budget = request.definition.execution_budget
        idle_seconds = float(budget.max_wall_seconds)
        total_cap = budget.max_total_seconds
        self._record_progress("run_start")
        max_steps = effective_max_steps(
            budget.max_steps, request.compiled_profile.runtime_profile.max_steps
        )
        tool_result_refs: list[ToolResultRef] = []
        tool_events: list[ToolEvent] = list(request.initial_tool_events)
        tool_calls = len(request.initial_tool_results)
        # #4379: the runtime keeps only references. The payload lives in the
        # ledger, so a long run does not retain every tool output in memory
        # and no step copies the whole history again.
        ledger = self._result_ledger
        if request.initial_tool_result_refs:
            # A resumed run restores the original results by reference, so the
            # exact payload survives the pause without being carried in memory.
            tool_result_refs.extend(request.initial_tool_result_refs)
            tool_calls = len(tool_result_refs)
        else:
            for ordinal, seeded in enumerate(request.initial_tool_results):
                tool_result_refs.append(
                    await ledger.append(
                        run_id=run_id,
                        step_index=request.initial_step_index,
                        ordinal=ordinal,
                        result=seeded,
                    )
                )

        # #4379: a step count is no longer a PADIEM ceiling. The run continues
        # until the model produces its final answer; the inactivity watchdog,
        # the opt-in total cap, the durable lease and cancellation still end it.
        step_index = request.initial_step_index - 1
        while max_steps is None or step_index < max_steps:
            step_index += 1
            await self._ensure_run_active()
            if self._total_cap_reached(started=started, total_cap=total_cap):
                return self._total_cap_terminal(
                    run_id=run_id,
                    steps=step_index - 1,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )
            remaining = self._idle_remaining(idle_seconds)
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
                tool_result_refs=tuple(tool_result_refs),
                result_ledger=ledger,
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
            except Exception as exc:
                # #5015: the public message stays generic, and the original
                # exception is still not chained to the caller. The driver's
                # own bounded detail code is preserved instead of being lost.
                raise AgentRuntimeError(
                    step_failure_code(exc),
                    "Agent step execution failed.",
                ) from None

            if not isinstance(decision, AgentStepDecision):
                raise AgentRuntimeError(
                    "invalid_agent_step",
                    "Agent step driver returned an invalid decision.",
                )

            # Fail closed on a decision that arrived after the idle window,
            # then count it as verified progress and open a fresh window.
            if self._idle_remaining(idle_seconds) <= 0.0:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )
            self._record_progress("step_decision")
            if self._total_cap_reached(started=started, total_cap=total_cap):
                return self._total_cap_terminal(
                    run_id=run_id,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )

            if decision.kind is AgentStepKind.COMPLETE:
                await self._ensure_run_active()
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
            pc_core_log("decision", invocation.tool_id, "enter")
            pc_core_log("decision", invocation.tool_id, "done")

            if budget.max_tool_calls is not None and tool_calls >= budget.max_tool_calls:
                # #4379: a tool-call count is no longer a PADIEM ceiling. A
                # caller that still wants one sets it explicitly.
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_TOOL_CALLS,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )
            tool_calls += 1

            remaining = self._idle_remaining(idle_seconds)
            if remaining <= 0:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )

            with pc_core_stage("run_active", invocation.tool_id):
                await self._ensure_run_active(diagnostic_tool_id=invocation.tool_id)
            try:
                with pc_core_stage("tool_runtime_wait_for", invocation.tool_id, timeout=remaining):
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
                if exc.code == "invalid_tool_arguments":
                    pc_core_log("input_schema_rejected", invocation.tool_id, "done")
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
                        # This is annotation of the original REGISTERED ToolSpec,
                        # not additional authorization. The ToolRuntime already
                        # verified these scopes are granted before it raised a
                        # USER_CONFIRMATION or EXTERNAL_AUTHORIZATION pause.
                        # The invocation/model cannot choose or widen them.
                        approval_scope=self._tool_runtime.registered_approval_scopes(
                            invocation.tool_id
                        ),
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

            # A Tool result is verified progress, but a Tool call that ran past
            # the idle window still fails closed before it is recorded.
            if self._idle_remaining(idle_seconds) <= 0.0:
                return self._terminal(
                    run_id=run_id,
                    reason=AgentTerminalReason.MAX_WALL_TIME,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )
            self._record_progress("tool_result")
            await self._ensure_run_active()
            tool_result_refs.append(
                await ledger.append(
                    run_id=run_id,
                    step_index=step_index,
                    ordinal=len(tool_result_refs),
                    result=tool_result,
                )
            )
            tool_events.append(tool_result.event)
            await self._record_trusted_checkpoint(step_index)
            self._record_progress("checkpoint")
            if self._total_cap_reached(started=started, total_cap=total_cap):
                return self._total_cap_terminal(
                    run_id=run_id,
                    steps=step_index,
                    tool_calls=tool_calls,
                    tool_events=tool_events,
                )

        return self._terminal(
            run_id=run_id,
            reason=AgentTerminalReason.MAX_STEPS,
            steps=max_steps if max_steps is not None else step_index,
            tool_calls=tool_calls,
            tool_events=tool_events,
        )
