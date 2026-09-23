"""#2929 S2F4E — compose an already-terminal scheduled run into the existing
Task/Alert authority.

COMPOSITION BOUNDARY ONLY. The existing bounded Task/Alert projection foundation
(#2913, :mod:`app.claw_automation_projection_bridge`) already owns *how* one
explicit automation output becomes at most one record, but nothing composed it
with the terminal scheduled-run path. This module is exactly that composition and
nothing else: it adds no record shape, no id grammar, no table, no store, and no
scheduler.

Canonical path:

```text
existing terminal ClawScheduledRun              (claimed occurrence row)
+ existing ClawAutomationRule                   (explicit closed output_type)
+ already-resolved ResolvedAutomationOwner      (existing owner authority; the
+                                                caller resolves it, and this
+                                                module never infers an owner)
+ existing D1 task/alert store surface          (existing persistence authority)
        |
        v  project_scheduled_run_output         (existing #2913 projection)
at most one existing-authority ClawFollowupTask or ClawAlert
```

Invariants pinned here:

* ``TASK_ALERT_OUTPUT_SOURCE_COMPOSED=YES`` — the terminal scheduled-run path can
  now reach the existing projection authority through one auditable seam.
* ``ONLY_TERMINAL_RUN_PROJECTED`` — a PENDING/RUNNING occurrence fails closed
  before any store access; a live run can never be turned into a record.
* ``SECOND_RUN_ID=0`` — the row must carry the existing occurrence-derived
  ``sched_run_<digest>`` identity for the same workspace/rule/scheduled_time. A
  row without that canonical identity is refused, so no foreign run can be
  projected under this rule.
* ``SECOND_TASK_ALERT_AUTHORITY=0`` — every validation of the record shape and
  every persistence call belongs to the existing projection authority and the
  existing store; this module neither constructs a record nor writes one.
* ``SECOND_OWNER_AUTHORITY=0`` — only an already-resolved trusted owner context is
  accepted. No owner resolution, no workspace/member inference, and no use of the
  rule's opaque owner provenance as an identity.
* ``SECOND_HISTORY_STORE=0`` / ``SECOND_SESSION_AUTHORITY=0`` — this slice writes
  no run history and no session. #2924 already projects a terminal scheduled row
  into the existing run-history authority; that projection is not repeated here.
* ``SECOND_COMPLETION_AUTHORITY=0`` / ``NEW_SCHEDULER_AUTHORITY=0`` — the row's own
  terminal status is read as-is. Nothing re-completes, re-schedules, claims an
  occurrence, or resurrects a run.
* ``SECOND_DEDUP_AUTHORITY=0`` — the existing deterministic
  ``(workspace_id, run_id, kind)`` record identity stays the only dedup authority.
* ``EXTERNAL_SEND=0`` / ``PROVIDER_CALLS=0`` / ``SANDBOX_ALLOCATIONS=0`` — no
  outbound notification, no provider or model call, no sandbox lease.
* USER STATUS PRESERVED — a duplicate projection is a bounded read. An existing
  record whose immutable identity matches is left exactly as it is, so a task the
  user already completed or cancelled, and an alert the user already dismissed,
  are never reopened.

Non-goals (other slices): owner resolution, run-history projection, P01 dispatch,
scheduler activation, external send, provider call, Production mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kagent.claw_automation import (
    ClawAutomationRule,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    _derived_occurrence_id,
)

from .claw_automation_owner_resolution import ResolvedAutomationOwner
from .claw_automation_projection_bridge import (
    ClawTaskAlertProjectionStore,
    project_scheduled_run_output,
)

# Statuses that are not terminal at all: an occurrence that has not finished may
# never be projected, so it is refused instead of being silently ignored.
_NON_TERMINAL_STATUSES = frozenset(
    {
        ClawScheduledRunStatus.PENDING,
        ClawScheduledRunStatus.RUNNING,
    }
)

# The existing store surface this seam consumes, exactly as the existing
# projection authority declares it. Named here only to fail closed early for a
# store that cannot serve the projection.
_STORE_SURFACE = ("get_task", "get_alert", "add_task", "add_alert")


class ScheduledTaskAlertProjectionError(RuntimeError):
    """Fail-closed refusal raised before any store access."""


@dataclass(frozen=True, slots=True)
class ScheduledTaskAlertProjection:
    """Bounded result of one existing-authority Task/Alert projection.

    Carries no raw output content, no credential material, and no owner
    provenance: only the canonical run identity, its truthful terminal status,
    the kind of record the existing authority touched, and whether this call
    created it.
    """

    run_id: str
    status: ClawScheduledRunStatus
    created_kind: Literal["task", "alert"] | None
    record_id: str | None
    created: bool


def _require_rule(rule: object) -> ClawAutomationRule:
    if not isinstance(rule, ClawAutomationRule):
        raise ScheduledTaskAlertProjectionError("rule must be a ClawAutomationRule")
    return rule


def _require_scheduled_run(scheduled_run: object) -> ClawScheduledRun:
    if not isinstance(scheduled_run, ClawScheduledRun):
        raise ScheduledTaskAlertProjectionError(
            "scheduled_run must be a ClawScheduledRun"
        )
    return scheduled_run


def _require_owner(owner: object) -> ResolvedAutomationOwner:
    if not isinstance(owner, ResolvedAutomationOwner):
        raise ScheduledTaskAlertProjectionError(
            "a resolved automation owner is required; owner resolution is not performed here"
        )
    return owner


def _require_store(store: object) -> None:
    if any(not callable(getattr(store, name, None)) for name in _STORE_SURFACE):
        raise ScheduledTaskAlertProjectionError(
            "the existing task/alert store cannot serve this projection"
        )


def _require_terminal(scheduled_run: ClawScheduledRun) -> None:
    if scheduled_run.status in _NON_TERMINAL_STATUSES:
        raise ScheduledTaskAlertProjectionError(
            "only an already-terminal scheduled run can reach Task/Alert projection"
        )


def _require_canonical_occurrence(
    *, rule: ClawAutomationRule, scheduled_run: ClawScheduledRun
) -> None:
    """Pin the existing occurrence identity; never mint or accept a second one."""

    expected = _derived_occurrence_id(
        "sched_run", rule.workspace_id, rule.rule_id, scheduled_run.scheduled_time
    )
    if scheduled_run.run_id != expected:
        raise ScheduledTaskAlertProjectionError(
            "scheduled run does not carry the canonical occurrence identity for this rule"
        )


async def project_terminal_scheduled_run_to_task_alert(
    *,
    rule: ClawAutomationRule,
    scheduled_run: ClawScheduledRun,
    owner: ResolvedAutomationOwner,
    store: ClawTaskAlertProjectionStore,
) -> ScheduledTaskAlertProjection:
    """Compose one already-terminal scheduled row into the existing Task/Alert path.

    Every guard here runs before any store access, and every record-shape and
    persistence decision is delegated to the existing projection authority, whose
    refusals propagate unchanged. A run whose rule/output type materializes no
    record (REPORT/DRAFT) and a terminal run that is not COMPLETED
    (FAILED/CANCELLED) resolve to a bounded no-op with zero writes.
    """

    checked_rule = _require_rule(rule)
    checked_run = _require_scheduled_run(scheduled_run)
    checked_owner = _require_owner(owner)
    _require_store(store)
    _require_terminal(checked_run)
    _require_canonical_occurrence(rule=checked_rule, scheduled_run=checked_run)

    result = await project_scheduled_run_output(
        owner=checked_owner,
        rule=checked_rule,
        run=checked_run,
        store=store,
    )
    return ScheduledTaskAlertProjection(
        run_id=checked_run.run_id,
        status=checked_run.status,
        created_kind=result.created_kind,
        record_id=result.record_id,
        created=result.created,
    )


__all__ = [
    "ScheduledTaskAlertProjection",
    "ScheduledTaskAlertProjectionError",
    "project_terminal_scheduled_run_to_task_alert",
]
