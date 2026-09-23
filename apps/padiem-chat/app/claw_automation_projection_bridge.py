"""#2833 S2F3B — bounded Task/Alert output projection foundation.

FOUNDATION + COMPOSITION SEAM. This bridge owns the bounded projection rules and
is composed by :mod:`app.claw_automation_task_alert_bridge` (#2929 S2F4E) for the
terminal scheduled-run path. It is still not called from any scheduler, tick or
P01 runtime. It performs no owner resolution, no history write, no P01 dispatch,
no provider call, and creates no new persistence authority. It reuses the
existing Claw memory contracts and the existing D1 task/alert store.

CENTRAL product decision (fixed): Task/Alert records are created ONLY from the
automation rule's explicit :class:`ClawAutomationOutputType` and a COMPLETED run::

    TASK_PROPOSAL + COMPLETED -> exactly one ClawFollowupTask
    ALERT + COMPLETED         -> exactly one ClawAlert
    REPORT / DRAFT            -> no Task/Alert
    FAILED / CANCELLED / PENDING / RUNNING -> no Task/Alert (no implicit alert)

Identity is deterministic (no random ids): the record id is a SHA-256 digest of
``(workspace_id, run_id, kind)``. A duplicate projection therefore never creates
a second record, and it never reopens a user-mutated status — an existing record
whose immutable identity matches is left exactly as it is (DONE/CANCELLED/
DISMISSED preserved). A matching id with a DIFFERENT immutable identity fails
closed.

The one and only owner authority is a resolved, trusted
:class:`ResolvedAutomationOwner`. ``owner_ref`` is opaque provenance and is never
used as a member id or as any write authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Literal, Protocol

from kagent.claw_automation import (
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawScheduledRun,
    ClawScheduledRunStatus,
)
from kagent.claw_memory import (
    ClawAlert,
    ClawAlertKind,
    ClawAlertSeverity,
    ClawAlertStatus,
    ClawFollowupTask,
    ClawTaskStatus,
)
from kagent.core import redact_secrets

from .claw_automation_owner_resolution import ResolvedAutomationOwner

_TASK_PREFIX = "automation_task:"
_ALERT_PREFIX = "automation_alert:"


class AutomationProjectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AutomationTaskAlertProjectionResult:
    """Bounded projection result.

    Deliberately carries no raw output/content, no credential material and no
    ``owner_ref``: only what kind of record was touched, its deterministic id,
    and whether this call created it.
    """

    created_kind: Literal["task", "alert"] | None
    record_id: str | None
    created: bool


class ClawTaskAlertProjectionStore(Protocol):
    """The existing task/alert store surface this bridge consumes."""

    async def get_task(self, task_id: str, *, workspace_id: str) -> ClawFollowupTask | None: ...
    async def get_alert(
        self, alert_id: str, *, workspace_id: str, member_id: str | None = None
    ) -> ClawAlert | None: ...
    async def add_task(self, task: ClawFollowupTask) -> ClawFollowupTask: ...
    async def add_alert(self, alert: ClawAlert) -> ClawAlert: ...


def _deterministic_id(workspace_id: str, run_id: str, kind: str) -> str:
    """Deterministic projection identity, not an authority.

    ``(workspace_id, run_id, kind)`` -> ``automation_<kind>:<64 lowercase hex>``.
    Fits the existing ``_safe_id`` grammar used by the Claw memory contracts.
    """

    payload = json.dumps(
        {"v": 1, "workspace_id": workspace_id, "run_id": run_id, "kind": kind},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{_TASK_PREFIX if kind == 'task' else _ALERT_PREFIX}{digest}"


def _require_owner(owner: object) -> ResolvedAutomationOwner:
    if not isinstance(owner, ResolvedAutomationOwner):
        raise AutomationProjectionError(
            "a resolved automation owner is required; owner resolution is not performed here"
        )
    return owner


def _require_workspace_consistency(
    *, owner: ResolvedAutomationOwner, rule: ClawAutomationRule, run: ClawScheduledRun
) -> None:
    if owner.workspace_id != rule.workspace_id:
        raise AutomationProjectionError("owner workspace does not match the rule workspace")
    if run.workspace_id != rule.workspace_id:
        raise AutomationProjectionError("run workspace does not match the rule workspace")
    if run.rule_id != rule.rule_id:
        raise AutomationProjectionError("run rule_id does not match the rule")


def _require_task_identity(
    task: ClawFollowupTask,
    *,
    workspace_id: str,
    member_id: str,
    title: str,
    source_id: str,
    linked_ref: str,
) -> None:
    if (
        task.workspace_id != workspace_id
        or task.member_id != member_id
        or task.title != title
        or task.source_id != source_id
        or task.linked_ref != linked_ref
    ):
        raise AutomationProjectionError(
            "existing task identity does not match the projection; refusing to overwrite"
        )


def _require_alert_identity(
    alert: ClawAlert,
    *,
    workspace_id: str,
    kind: ClawAlertKind,
    severity: ClawAlertSeverity,
    title: str,
    visible_to_members: tuple[str, ...],
) -> None:
    if (
        alert.workspace_id != workspace_id
        or alert.kind is not kind
        or alert.severity is not severity
        or alert.title != title
        or tuple(alert.visible_to_members) != tuple(visible_to_members)
    ):
        raise AutomationProjectionError(
            "existing alert identity does not match the projection; refusing to overwrite"
        )


async def project_scheduled_run_output(
    *,
    owner: ResolvedAutomationOwner,
    rule: ClawAutomationRule,
    run: ClawScheduledRun,
    store: ClawTaskAlertProjectionStore,
) -> AutomationTaskAlertProjectionResult:
    """Project one completed scheduled run's explicit output type into a Task/Alert.

    Returns a bounded result. No-op (``created_kind=None``) for types that never
    materialize a record and for every non-COMPLETED run status.
    """

    resolved = _require_owner(owner)
    _require_workspace_consistency(owner=resolved, rule=rule, run=run)

    if run.status is not ClawScheduledRunStatus.COMPLETED:
        # FAILED/CANCELLED/PENDING/RUNNING never create a Task or an Alert.
        return AutomationTaskAlertProjectionResult(None, None, False)

    output_type = rule.output_type
    if output_type not in (
        ClawAutomationOutputType.TASK_PROPOSAL,
        ClawAutomationOutputType.ALERT,
    ):
        # REPORT / DRAFT materialize nothing.
        return AutomationTaskAlertProjectionResult(None, None, False)

    if run.completed_at is None:
        raise AutomationProjectionError("completed run is missing completed_at")
    output = run.output
    if output is None:
        raise AutomationProjectionError("completed output run is missing its output")
    if output.workspace_id != resolved.workspace_id:
        raise AutomationProjectionError(
            "output workspace does not match the resolved owner workspace"
        )
    if output.output_type != output_type:
        raise AutomationProjectionError("output_type does not match the rule output_type")

    # Reuse the existing secret-redaction helper; never store the raw content body.
    title = redact_secrets(output.title)

    if output_type is ClawAutomationOutputType.TASK_PROPOSAL:
        return await _project_task(
            owner=resolved, rule=rule, run=run, title=title, store=store
        )
    return await _project_alert(
        owner=resolved, rule=rule, run=run, title=title, store=store
    )


async def _project_task(
    *,
    owner: ResolvedAutomationOwner,
    rule: ClawAutomationRule,
    run: ClawScheduledRun,
    title: str,
    store: ClawTaskAlertProjectionStore,
) -> AutomationTaskAlertProjectionResult:
    task_id = _deterministic_id(owner.workspace_id, run.run_id, "task")
    existing = await store.get_task(task_id, workspace_id=owner.workspace_id)
    if existing is not None:
        _require_task_identity(
            existing,
            workspace_id=owner.workspace_id,
            member_id=owner.member_id,
            title=title,
            source_id=run.run_id,
            linked_ref=rule.rule_id,
        )
        # Idempotent: never create a second record, never reopen a user status.
        return AutomationTaskAlertProjectionResult("task", task_id, False)

    task = ClawFollowupTask(
        task_id=task_id,
        workspace_id=owner.workspace_id,
        member_id=owner.member_id,
        title=title,
        status=ClawTaskStatus.OPEN,
        created_at=run.completed_at,
        due_date=None,
        source_id=run.run_id,
        linked_ref=rule.rule_id,
    )
    await store.add_task(task)
    return AutomationTaskAlertProjectionResult("task", task_id, True)


async def _project_alert(
    *,
    owner: ResolvedAutomationOwner,
    rule: ClawAutomationRule,
    run: ClawScheduledRun,
    title: str,
    store: ClawTaskAlertProjectionStore,
) -> AutomationTaskAlertProjectionResult:
    alert_id = _deterministic_id(owner.workspace_id, run.run_id, "alert")
    visible_to_members = (owner.member_id,)
    existing = await store.get_alert(
        alert_id, workspace_id=owner.workspace_id, member_id=owner.member_id
    )
    if existing is not None:
        _require_alert_identity(
            existing,
            workspace_id=owner.workspace_id,
            kind=ClawAlertKind.AUTOMATION,
            severity=ClawAlertSeverity.INFO,
            title=title,
            visible_to_members=visible_to_members,
        )
        return AutomationTaskAlertProjectionResult("alert", alert_id, False)

    alert = ClawAlert(
        alert_id=alert_id,
        workspace_id=owner.workspace_id,
        kind=ClawAlertKind.AUTOMATION,
        severity=ClawAlertSeverity.INFO,
        title=title,
        created_at=run.completed_at,
        status=ClawAlertStatus.ACTIVE,
        visible_to_members=visible_to_members,
    )
    await store.add_alert(alert)
    return AutomationTaskAlertProjectionResult("alert", alert_id, True)


__all__ = [
    "AutomationProjectionError",
    "AutomationTaskAlertProjectionResult",
    "ClawTaskAlertProjectionStore",
    "project_scheduled_run_output",
]
