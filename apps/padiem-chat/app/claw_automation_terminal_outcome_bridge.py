"""#2918 S2F4C - project an existing P01 outcome onto its scheduled row.

This module is a composition boundary only. It reuses the S2F4B execution
bridge and the S2F4A existing-row output attachment path. It never claims an
occurrence, creates a run, resolves an owner, writes History/Task/Alert, or
calls a provider.

The scheduled run id remains the only identity from occurrence claim through
P01 execution and terminal projection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
from typing import Callable, Protocol, Any

from kagent.claw_automation import (
    ClawAutomationOutput,
    ClawAutomationRule,
    ClawScheduledRun,
    ClawScheduledRunStatus,
)
from kagent.contracts import ClawRunStatus, ContractError, RunProjection, SandboxLease
from kagent.p01_adapter import ClawOrchestrationOutcome

from .claw_automation_execution_bridge import (
    CanonicalScheduledExecutionPlan,
    P01ExecutionPort,
    execute_scheduled_occurrence,
    plan_canonical_scheduled_execution,
)


class ScheduledOutcomeProjectionError(RuntimeError):
    """Fail-closed refusal for an unsafe or mismatched terminal outcome."""


class ScheduledOutcomeStore(Protocol):
    """The existing scheduled-row surface this projection consumes.

    A method may answer synchronously (the durable SQLite reference store and the
    in-memory store) or through an awaitable (a D1-backed Worker store, where the
    binding is only reachable through awaited statements). The awaitable path
    resolves either shape with ``_await_projection`` instead of forcing a
    synchronous adapter over an async binding, so this stays ONE store contract.
    """

    def get_run(self, run_id: str, workspace_id: str) -> ClawScheduledRun | None: ...

    def update_run_projection(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
        status: ClawScheduledRunStatus,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        output: ClawAutomationOutput | None = None,
    ) -> ClawScheduledRun: ...


@dataclass(frozen=True, slots=True)
class ScheduledOutcomeProjection:
    """Bounded result of one existing-row terminal projection."""

    scheduled_run: ClawScheduledRun
    outcome: ClawOrchestrationOutcome | None
    output: ClawAutomationOutput | None


_FAILED_MESSAGE = "P01 execution failed before a safe terminal output was available."
_UNSAFE_COMPLETED_MESSAGE = "P01 completed without a safe bounded answer."
_CANCELLED_MESSAGE = "P01 execution was cancelled."


def _completion_time(
    completed_at: datetime | None,
    clock: Callable[[], datetime] | None,
) -> datetime:
    value = completed_at if completed_at is not None else (clock or _utc_now)()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScheduledOutcomeProjectionError("completed_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _output_id(*, workspace_id: str, rule_id: str, run_id: str) -> str:
    payload = json.dumps(
        {"v": 1, "workspace_id": workspace_id, "rule_id": rule_id, "run_id": run_id},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"scheduled_output_{digest}"


async def _resolve(value: Any) -> Any:
    """Resolve one store result whether the store is sync or awaitable.

    The durable reference stores answer synchronously, while a D1-backed Worker
    store can only answer through awaited statements. Resolving both here keeps
    ONE store contract and lets either implementation be injected. It never
    synchronously drives a coroutine and never blocks the event loop.
    """

    return await value if inspect.isawaitable(value) else value


def _validate_existing_row(
    *,
    current: ClawScheduledRun | None,
    plan: CanonicalScheduledExecutionPlan,
) -> ClawScheduledRun:
    """Shared fail-closed identity check for an already-read scheduled row."""

    if current is None:
        raise ScheduledOutcomeProjectionError(
            "terminal projection requires an existing scheduled run"
        )
    if (
        current.workspace_id != plan.rule.workspace_id
        or current.rule_id != plan.rule.rule_id
        or current.scheduled_time != plan.scheduled_run.scheduled_time
    ):
        raise ScheduledOutcomeProjectionError(
            "stored scheduled row identity does not match the canonical occurrence"
        )
    return current


def _require_existing_row(
    *,
    store: ScheduledOutcomeStore,
    plan: CanonicalScheduledExecutionPlan,
) -> ClawScheduledRun:
    """Read and validate the existing scheduled row for the synchronous path.

    The synchronous entry point can only serve a synchronous store. An awaitable
    store answers through a coroutine this function cannot drive, so it fails
    closed and points the caller to the async entry point instead of faking a
    synchronous result.
    """

    current = store.get_run(plan.run.run_id, plan.rule.workspace_id)
    if inspect.isawaitable(current):
        raise ScheduledOutcomeProjectionError(
            "project_p01_outcome_to_scheduled_run is the synchronous entry point; "
            "an awaitable store requires project_p01_outcome_to_scheduled_run_async"
        )
    return _validate_existing_row(current=current, plan=plan)


async def _read_existing_row(
    *,
    store: ScheduledOutcomeStore,
    plan: CanonicalScheduledExecutionPlan,
) -> ClawScheduledRun:
    """Awaitable-tolerant read, for a D1-backed store."""

    current = await _resolve(store.get_run(plan.run.run_id, plan.rule.workspace_id))
    return _validate_existing_row(current=current, plan=plan)


def _require_outcome_run(
    *,
    outcome: ClawOrchestrationOutcome,
    plan: CanonicalScheduledExecutionPlan,
) -> RunProjection:
    if not isinstance(outcome, ClawOrchestrationOutcome):
        raise ScheduledOutcomeProjectionError("P01 returned an invalid orchestration outcome")
    projection = outcome.projection
    if projection.run_id != plan.run.run_id:
        raise ScheduledOutcomeProjectionError(
            "P01 outcome run id does not match the scheduled run"
        )
    if projection.run_id != plan.scheduled_run.run_id:
        raise ScheduledOutcomeProjectionError(
            "P01 outcome correlation does not match the scheduled occurrence"
        )
    return projection


def _bounded_output(
    *,
    rule: ClawAutomationRule,
    plan: CanonicalScheduledExecutionPlan,
    outcome: ClawOrchestrationOutcome,
) -> ClawAutomationOutput:
    answer = outcome.answer
    if not isinstance(answer, str) or not answer.strip():
        raise ScheduledOutcomeProjectionError(
            "completed P01 outcome is missing a safe bounded answer"
        )
    # The P01 adapter exposes only its already-redacted answer surface. The
    # ClawAutomationOutput contract applies the final bounded-text validation.
    return ClawAutomationOutput(
        output_id=_output_id(
            workspace_id=rule.workspace_id,
            rule_id=rule.rule_id,
            run_id=plan.run.run_id,
        ),
        workspace_id=rule.workspace_id,
        output_type=rule.output_type,
        title=rule.name,
        content=answer,
    )


def _same_terminal_result(
    *,
    current: ClawScheduledRun,
    status: ClawScheduledRunStatus,
    output: ClawAutomationOutput | None,
) -> ScheduledOutcomeProjection | None:
    if current.status is ClawScheduledRunStatus.COMPLETED:
        if status is ClawScheduledRunStatus.COMPLETED and (
            output is None or current.output == output
        ):
            return ScheduledOutcomeProjection(current, None, current.output)
        if status is ClawScheduledRunStatus.COMPLETED and current.output is None:
            # S2F4A explicitly permits one bounded output backfill for an
            # already-completed row. The existing store owns its idempotency.
            return None
        raise ScheduledOutcomeProjectionError(
            "terminal completed scheduled row cannot be changed"
        )
    if current.status is ClawScheduledRunStatus.FAILED:
        if status is ClawScheduledRunStatus.FAILED:
            return ScheduledOutcomeProjection(current, None, current.output)
        raise ScheduledOutcomeProjectionError(
            "terminal failed scheduled row cannot be resurrected"
        )
    if current.status is ClawScheduledRunStatus.CANCELLED:
        if status is ClawScheduledRunStatus.CANCELLED:
            return ScheduledOutcomeProjection(current, None, current.output)
        raise ScheduledOutcomeProjectionError(
            "terminal cancelled scheduled row cannot be resurrected"
        )
    return None


@dataclass(frozen=True, slots=True)
class _TerminalDecision:
    """Pure terminal decision: the status, error and output a projection needs.

    Data only. It performs no store access, so the synchronous and awaitable
    entry points below share ONE decision and cannot drift on what an outcome
    means.
    """

    status: ClawScheduledRunStatus
    error_message: str | None
    output: ClawAutomationOutput | None


def _decide_terminal_projection(
    *,
    rule: ClawAutomationRule,
    plan: CanonicalScheduledExecutionPlan,
    outcome: ClawOrchestrationOutcome,
    projection: RunProjection,
) -> _TerminalDecision:
    """Pure: which terminal projection an already-validated outcome requires."""

    if projection.status is ClawRunStatus.COMPLETED:
        try:
            output = _bounded_output(rule=rule, plan=plan, outcome=outcome)
        except (ContractError, ScheduledOutcomeProjectionError):
            return _TerminalDecision(
                ClawScheduledRunStatus.FAILED, _UNSAFE_COMPLETED_MESSAGE, None
            )
        return _TerminalDecision(ClawScheduledRunStatus.COMPLETED, None, output)
    if projection.status is ClawRunStatus.FAILED:
        return _TerminalDecision(ClawScheduledRunStatus.FAILED, _FAILED_MESSAGE, None)
    if projection.status is ClawRunStatus.CANCELLED:
        return _TerminalDecision(ClawScheduledRunStatus.CANCELLED, None, None)
    raise ScheduledOutcomeProjectionError(
        "P01 outcome is not a terminal lifecycle result"
    )


async def _await_projection(
    projection: ScheduledOutcomeProjection,
) -> ScheduledOutcomeProjection:
    """Resolve a projection whose stored row may be an un-awaited store coroutine.

    ``_project_status`` is the ONE write call site for both the synchronous and
    the Worker-D1 (awaitable) stores, so it returns the stored row directly for a
    synchronous store and the store coroutine for an awaitable store. The sync
    entry point uses the row as-is; an async caller awaits here first.
    """

    row = projection.scheduled_run
    if inspect.isawaitable(row):
        row = await row
    return ScheduledOutcomeProjection(row, projection.outcome, projection.output)


def _project_status(
    *,
    store: ScheduledOutcomeStore,
    plan: CanonicalScheduledExecutionPlan,
    current: ClawScheduledRun,
    status: ClawScheduledRunStatus,
    completed_at: datetime,
    error_message: str | None = None,
    outcome: ClawOrchestrationOutcome | None = None,
    output: ClawAutomationOutput | None = None,
) -> ScheduledOutcomeProjection:
    """The single terminal-projection write call site for this module.

    The idempotent-retry short circuit returns the existing terminal row with NO
    write. Otherwise it calls ``store.update_run_projection`` — the only such
    literal in this module, so the synchronous and Worker-D1 stores can never
    drift on what a terminal projection writes. For a synchronous store the call
    returns the row; for an awaitable store it returns the coroutine the caller
    must await (see ``_await_projection``).
    """

    existing = _same_terminal_result(current=current, status=status, output=output)
    if existing is not None:
        return ScheduledOutcomeProjection(existing.scheduled_run, outcome, existing.output)
    updated = store.update_run_projection(
        run_id=plan.run.run_id,
        workspace_id=plan.rule.workspace_id,
        rule_id=plan.rule.rule_id,
        scheduled_time=plan.scheduled_run.scheduled_time,
        status=status,
        completed_at=completed_at,
        error_message=error_message,
        output=output,
    )
    return ScheduledOutcomeProjection(updated, outcome, output)


def project_p01_outcome_to_scheduled_run(
    *,
    rule: ClawAutomationRule,
    scheduled_run: ClawScheduledRun,
    outcome: ClawOrchestrationOutcome,
    store: ScheduledOutcomeStore,
    completed_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ScheduledOutcomeProjection:
    """Project one already-correlated P01 terminal outcome to the same row.

    Synchronous entry point for the durable SQLite and in-memory reference
    stores. An awaitable Worker-D1 store must use
    ``project_p01_outcome_to_scheduled_run_async``: this function cannot await,
    and it will not fake a synchronous result.
    """

    plan = plan_canonical_scheduled_execution(rule, scheduled_run)
    projection = _require_outcome_run(outcome=outcome, plan=plan)
    current = _require_existing_row(store=store, plan=plan)
    decision = _decide_terminal_projection(
        rule=rule, plan=plan, outcome=outcome, projection=projection
    )
    return _project_status(
        store=store,
        plan=plan,
        current=current,
        status=decision.status,
        completed_at=_completion_time(completed_at, clock),
        error_message=decision.error_message,
        outcome=outcome,
        output=decision.output,
    )


async def project_p01_outcome_to_scheduled_run_async(
    *,
    rule: ClawAutomationRule,
    scheduled_run: ClawScheduledRun,
    outcome: ClawOrchestrationOutcome,
    store: ScheduledOutcomeStore,
    completed_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ScheduledOutcomeProjection:
    """Awaitable twin of ``project_p01_outcome_to_scheduled_run``.

    Same decision, same fail-closed order, same idempotent-retry short circuit;
    the store access is awaited and the ONE ``_project_status`` write call site is
    shared. A D1-backed Worker store needs this path, and a synchronous store is
    served by it unchanged.
    """

    plan = plan_canonical_scheduled_execution(rule, scheduled_run)
    projection = _require_outcome_run(outcome=outcome, plan=plan)
    current = await _read_existing_row(store=store, plan=plan)
    decision = _decide_terminal_projection(
        rule=rule, plan=plan, outcome=outcome, projection=projection
    )
    return await _await_projection(
        _project_status(
            store=store,
            plan=plan,
            current=current,
            status=decision.status,
            completed_at=_completion_time(completed_at, clock),
            error_message=decision.error_message,
            outcome=outcome,
            output=decision.output,
        )
    )


async def execute_and_project_scheduled_occurrence(
    *,
    rule: ClawAutomationRule,
    scheduled_run: ClawScheduledRun,
    adapter: P01ExecutionPort,
    store: ScheduledOutcomeStore,
    lease: SandboxLease | None = None,
    product_tier: Any | None = None,
    completed_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ScheduledOutcomeProjection:
    """Execute through S2F4B, then project the result through S2F4A."""

    plan = plan_canonical_scheduled_execution(rule, scheduled_run)
    current = await _read_existing_row(store=store, plan=plan)
    if current.status in {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }:
        # A terminal scheduled row is already the lifecycle authority. Exact
        # retries are projection reads, never a second P01 execution.
        return ScheduledOutcomeProjection(current, None, current.output)
    try:
        outcome = await execute_scheduled_occurrence(
            rule=rule,
            scheduled_run=scheduled_run,
            adapter=adapter,
            lease=lease,
            product_tier=product_tier,
        )
    except asyncio.CancelledError:
        await _await_projection(
            _project_status(
                store=store,
                plan=plan,
                current=current,
                status=ClawScheduledRunStatus.CANCELLED,
                completed_at=_completion_time(completed_at, clock),
                outcome=None,
            )
        )
        raise
    except Exception:
        await _await_projection(
            _project_status(
                store=store,
                plan=plan,
                current=current,
                status=ClawScheduledRunStatus.FAILED,
                completed_at=_completion_time(completed_at, clock),
                error_message=_FAILED_MESSAGE,
                outcome=None,
            )
        )
        raise
    return await project_p01_outcome_to_scheduled_run_async(
        rule=rule,
        scheduled_run=scheduled_run,
        outcome=outcome,
        store=store,
        completed_at=completed_at,
        clock=clock,
    )


__all__ = [
    "ScheduledOutcomeProjection",
    "ScheduledOutcomeProjectionError",
    "execute_and_project_scheduled_occurrence",
    "project_p01_outcome_to_scheduled_run",
    "project_p01_outcome_to_scheduled_run_async",
]
