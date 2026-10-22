"""#5034 — notify the existing web inbox's devices when an automation run ends.

This is a composition seam, not a new notification authority. It runs *after*
the existing terminal projection has already written the Task/Alert record, and
its only job is to additionally attempt a Web Push to the devices the same
account opted in.

Canonical position in the existing chain:

```text
existing terminal run
        |
        v  existing project_terminal_scheduled_run_to_history()   (#2927)
        v  existing project_terminal_scheduled_run_to_task_alert() (#2933)
        |     -> the web inbox record now exists (source of truth)
        v  THIS MODULE: deliver_inbox_push()                       (#5034)
              -> an additional device attempt, never a record
```

Invariants
----------
* ``INBOX_IS_SOURCE_OF_TRUTH`` — the record already exists before this runs. A
  push that fails, is unconfigured, or has no subscription changes nothing.
* ``NO_JOB_RERUN`` — a push failure never re-executes the automation, never
  re-opens the run and never retries the P01 dispatch.
* ``DEDUP_BY_RUN`` — the notification is derived from the run's own terminal
  identity, so a re-projected run cannot produce a second push for the same
  event. The existing projection idempotency is what makes this true: a run
  whose record already existed reports ``created=False`` and is skipped here.
* ``MINIMAL_LOCK_SCREEN`` — the payload is a short status plus the inbox link.
  No document content, no ERP data, no secret, no run output.
* ``PUSH_NEVER_RAISES`` — every failure is swallowed into the reported outcome
  so the automation lane's own result is unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .claw_push_subscriptions import deliver_inbox_push

# The existing inbox surface the notification links back to.
INBOX_ALERTS_PATH = "/claw?view=inbox&kind=alerts"
INBOX_TASKS_PATH = "/claw?view=inbox&kind=tasks"

_COMPLETED_TITLE = "자동화 완료"
_COMPLETED_BODY = "예약 작업이 완료되었습니다."
_FAILED_TITLE = "자동화 실패"
_FAILED_BODY = "예약 작업이 완료되지 못했습니다."


@dataclass(frozen=True, slots=True)
class AutomationPushOutcome:
    """What the device attempt did. Never describes the inbox record."""

    state: str
    attempted: int = 0
    delivered: int = 0
    failed: int = 0

    @property
    def inbox_state_changed(self) -> bool:
        return False


def _notification_text(*, created_kind: str | None, run_status: str) -> tuple[str, str, str]:
    """The bounded lock-screen text and the result link for one terminal run."""

    failed = str(run_status).upper() not in {"COMPLETED"}
    if failed:
        title, body = _FAILED_TITLE, _FAILED_BODY
    else:
        title, body = _COMPLETED_TITLE, _COMPLETED_BODY
    url = INBOX_TASKS_PATH if created_kind == "task" else INBOX_ALERTS_PATH
    return title, body, url


async def notify_terminal_run(
    *,
    push_store: Any | None,
    push_sender: Any | None,
    workspace_id: str,
    member_id: str,
    scope: str,
    created_kind: str | None,
    created: bool,
    run_status: str,
) -> AutomationPushOutcome:
    """Attempt one device notification for an already-projected terminal run.

    ``created`` is the existing projection's own idempotency answer. A run whose
    record already existed is a re-projection, not a new event, so it is skipped
    and cannot produce a duplicate notification.
    """

    if push_store is None:
        return AutomationPushOutcome(state="not_configured")
    if not created:
        # Re-projection of an existing record: not a new event.
        return AutomationPushOutcome(state="duplicate")
    if not workspace_id or not member_id:
        return AutomationPushOutcome(state="not_configured")
    title, body, url = _notification_text(
        created_kind=created_kind, run_status=run_status
    )
    try:
        outcome = await deliver_inbox_push(
            store=push_store,
            sender=push_sender,
            workspace_id=workspace_id,
            member_id=member_id,
            scope=scope,
            title=title,
            body=body,
            url=url,
        )
    except Exception:
        # A push must never fail the automation lane.
        return AutomationPushOutcome(state="failed")
    return AutomationPushOutcome(
        state=outcome.state,
        attempted=outcome.attempted,
        delivered=outcome.delivered,
        failed=outcome.failed,
    )


__all__ = [
    "INBOX_ALERTS_PATH",
    "INBOX_TASKS_PATH",
    "AutomationPushOutcome",
    "notify_terminal_run",
]
