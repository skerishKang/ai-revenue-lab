"""#2924 S2F4D — project an already-terminal scheduled run into Claw run history.

This module is a composition boundary only. It turns an existing terminal
``ClawScheduledRun`` row into one bounded row of the existing Claw run-history
authority, reusing the canonical session/conversation authority for an optional
session reference. It never claims an occurrence, creates a run, resolves an
owner, writes a Task/Alert, or calls a provider.

Canonical path:

```text
existing ClawScheduledRun (terminal row)
        |
        v  plan_canonical_scheduled_execution    (existing S2F4B correlation)
existing sched_run_<digest> identity
        |
        +-- ResolvedAutomationOwner              (existing owner authority;
        |                                         resolved by the caller)
        +-- optional conversation reference      (existing validate_conversation_id
        |                                         + owner-scoped get_conversation)
        |
        v  store.record_claw_run                 (existing #2317 history authority)
one bounded owner-scoped run-history row keyed by (user_id, run_id)
```

Invariants pinned here:

* ``CLAW_RUN_HISTORY_PROJECTION=YES`` — the terminal scheduled state is
  projected truthfully (completed / failed / cancelled) into the existing
  history authority.
* ``SECOND_RUN_ID=0`` — the history row is keyed by the occurrence-derived
  ``sched_run_<digest>``; no ``run_<uuid>`` or second identity is minted.
* ``SECOND_HISTORY_STORE=0`` — ``HistoryStore.record_claw_run`` is the only
  write surface; this module creates no table, no store, and no ledger.
* ``SECOND_SESSION_AUTHORITY=0`` — an optional reference reuses the existing
  conversation shape validator and the owner-scoped conversation lookup. No
  session, conversation, or account authority is created, and no reference is
  ever fabricated: absence stays ``None`` (legacy rows project ``session``
  ``null``).
* ``SECOND_OWNER_AUTHORITY=0`` — owner resolution is not performed here; only
  an already-resolved trusted owner context is accepted, and a workspace
  mismatch fails closed before any write.
* ``SECOND_COMPLETION_AUTHORITY=0`` / ``NEW_SCHEDULER_AUTHORITY=0`` — the
  scheduled row's own terminal status is read as-is; nothing re-completes,
  re-schedules, or resurrects it.
* ``TASK_ALERT_WRITE=0`` — no Task/Alert store is touched.
* ``FABRICATED_SESSION_ID=0`` — only a validated owner conversation handle is
  persisted; malformed or foreign references fail closed before any write.
* EXACT RETRY IDEMPOTENT — the existing ``(user_id, run_id)`` upsert owns
  idempotency; projecting the same terminal row twice re-issues identical
  kwargs and never inserts a second history record.

Non-goals (other slices): owner resolution, Task/Alert projection, external
send/write, provider call expansion, Production mutation.
"""

from __future__ import annotations

from dataclasses import dataclass

from kagent.claw_automation import (
    ClawAutomationRule,
    ClawScheduledRun,
    ClawScheduledRunStatus,
)

from .claw_automation_execution_bridge import plan_canonical_scheduled_execution
from .claw_automation_owner_resolution import ResolvedAutomationOwner
from .history import HistoryStore, validate_conversation_id

# The in-repo precedent vocabulary for scheduled-automation rows on this exact
# authority (#2833 S2F3A workspace-linkage tests record channel
# "claw_automation"); the action reuses the rule's existing closed output-type
# enum. No new channel/action vocabulary is invented here.
_HISTORY_CHANNEL = "claw_automation"

_TERMINAL_STATUSES = frozenset(
    {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }
)


class ScheduledHistoryProjectionError(RuntimeError):
    """Fail-closed refusal for an unsafe or mismatched history projection."""


@dataclass(frozen=True, slots=True)
class ScheduledHistoryProjection:
    """Bounded result of one existing-authority history projection."""

    run_id: str
    status: ClawScheduledRunStatus
    conversation_id: str | None


def _require_terminal(scheduled_run: ClawScheduledRun) -> None:
    if scheduled_run.status not in _TERMINAL_STATUSES:
        raise ScheduledHistoryProjectionError(
            "only a terminal scheduled run can be projected to run history"
        )


def _require_owner(
    owner: object, *, workspace_id: str
) -> ResolvedAutomationOwner:
    if not isinstance(owner, ResolvedAutomationOwner):
        raise ScheduledHistoryProjectionError(
            "a resolved automation owner is required; owner resolution is not performed here"
        )
    if owner.workspace_id != workspace_id:
        raise ScheduledHistoryProjectionError(
            "owner workspace does not match the rule workspace"
        )
    return owner


async def _resolve_session_reference(
    *,
    owner: ResolvedAutomationOwner,
    store: HistoryStore,
    conversation_id: str | None,
) -> str | None:
    """Reuse the canonical conversation authority, or fail closed (#2829)."""

    if conversation_id is None:
        # Absent reference keeps the legacy row: session stays null on read.
        return None
    try:
        candidate = validate_conversation_id(conversation_id)
    except ValueError as exc:
        raise ScheduledHistoryProjectionError(
            "conversation reference shape is invalid"
        ) from exc
    if candidate is None:
        return None
    get_conversation = getattr(store, "get_conversation", None)
    if not callable(get_conversation):
        raise ScheduledHistoryProjectionError(
            "conversation authority is unavailable"
        )
    try:
        conversation = await get_conversation(owner.product_user_id, candidate)
    except Exception as exc:
        # A missing/foreign reference and an authority failure share the same
        # non-disclosing fail-closed projection; no history row is written.
        raise ScheduledHistoryProjectionError(
            "conversation authority is unavailable"
        ) from exc
    if not isinstance(conversation, dict) or conversation.get("id") != candidate:
        raise ScheduledHistoryProjectionError(
            "conversation reference does not belong to the owner"
        )
    return candidate


def _history_fields(
    *, rule: ClawAutomationRule, scheduled_run: ClawScheduledRun
) -> tuple[str, str | None]:
    """Truthful bounded title + result summary for one terminal row."""

    if (
        scheduled_run.status is ClawScheduledRunStatus.COMPLETED
        and scheduled_run.output is not None
    ):
        # The output contract already bounds title (256) and content (16384);
        # the existing store truncates the summary to its own public bound.
        return scheduled_run.output.title, scheduled_run.output.content
    if scheduled_run.status is ClawScheduledRunStatus.FAILED:
        return rule.name, scheduled_run.error_message
    # CANCELLED (and a legacy completed row without output) carry no summary:
    # absence is projected as absence, never as a fabricated success.
    return rule.name, None


async def project_terminal_scheduled_run_to_history(
    *,
    rule: ClawAutomationRule,
    scheduled_run: ClawScheduledRun,
    owner: ResolvedAutomationOwner,
    store: HistoryStore,
    conversation_id: str | None = None,
) -> ScheduledHistoryProjection:
    """Project one already-terminal scheduled row into the existing history."""

    plan = plan_canonical_scheduled_execution(rule, scheduled_run)
    _require_terminal(scheduled_run)
    resolved = _require_owner(owner, workspace_id=plan.rule.workspace_id)
    # Session resolution (shape validator + owner-scoped lookup) completes
    # before any history write, so a foreign reference never half-projects.
    resolved_conversation_id = await _resolve_session_reference(
        owner=resolved, store=store, conversation_id=conversation_id
    )
    record = getattr(store, "record_claw_run", None)
    if not callable(record):
        raise ScheduledHistoryProjectionError(
            "history store cannot record claw runs"
        )
    title, summary = _history_fields(rule=rule, scheduled_run=scheduled_run)
    await record(
        user_id=resolved.product_user_id,
        run_id=scheduled_run.run_id,
        channel=_HISTORY_CHANNEL,
        action=rule.output_type.value,
        title=title,
        status=scheduled_run.status.value,
        result_summary=summary,
        conversation_id=resolved_conversation_id,
        workspace_id=scheduled_run.workspace_id,
    )
    return ScheduledHistoryProjection(
        run_id=scheduled_run.run_id,
        status=scheduled_run.status,
        conversation_id=resolved_conversation_id,
    )


__all__ = [
    "ScheduledHistoryProjection",
    "ScheduledHistoryProjectionError",
    "project_terminal_scheduled_run_to_history",
]
