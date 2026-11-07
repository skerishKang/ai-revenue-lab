"""#5034 — notify the owner's opted-in devices when an automation run ends.

This is a composition seam, not a new notification authority. 대표 결정
(2026-11-07): the notification is judged directly from the run's terminal
state — COMPLETED is a success, FAILED/CANCELLED a failure, output presence
or the Task/Alert projection no longer decides anything — and the click
target is the automation's own conversation (one rule owns one conversation).

Canonical position in the existing chain:

```text
existing terminal run
        |
        v  existing project_terminal_scheduled_run_to_history()   (#2927,
        |     now linked to the automation conversation)
        v  the result message is appended to that conversation (idempotent)
        v  THIS MODULE: deliver_inbox_push()                       (#5034)
              -> an additional device attempt, never a record
```

Invariants
----------
* ``TERMINAL_DECIDES`` — the run's terminal state alone picks success or
  failure wording; no projection record, no output contract, no inbox.
* ``NO_JOB_RERUN`` — a push failure never re-executes the automation, never
  re-opens the run and never retries the P01 dispatch.
* ``DEDUP_BY_RUN`` — the result message append is idempotent per run; a
  re-projected run reports ``created=False`` and is skipped here, so one
  terminal event is one device attempt.
* ``MINIMAL_LOCK_SCREEN`` — the payload is a short status plus the
  conversation link. No document content, no ERP data, no secret, no run
  output (대표 결정: 문구는 현행 고정 문구 유지).
* ``PUSH_NEVER_RAISES`` — every failure is swallowed into the reported outcome
  so the automation lane's own result is unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .claw_push_subscriptions import deliver_inbox_push

# 대표 결정(2026-11-07): 알림 클릭은 그 자동화의 대화를 연다. The reference is
# the server-derived conversation id only — no title, no document, no ERP
# content and no secret ever reaches the lock screen or the URL.
CONVERSATION_LINK_PATH = "/?notify=conversation&conversation_id={conversation_id}"

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


def _notification_text(
    *, run_status: str, conversation_url: str | None,
) -> tuple[str, str, str]:
    """The bounded lock-screen text and the conversation link for one run."""

    failed = str(run_status).upper() not in {"COMPLETED"}
    if failed:
        title, body = _FAILED_TITLE, _FAILED_BODY
    else:
        title, body = _COMPLETED_TITLE, _COMPLETED_BODY
    return title, body, conversation_url


async def notify_terminal_run(
    *,
    push_store: Any | None,
    push_sender: Any | None,
    workspace_id: str,
    member_id: str,
    scope: str,
    run_status: str,
    created: bool,
    conversation_url: str | None = None,
) -> AutomationPushOutcome:
    """Attempt one device notification for one already-recorded terminal run.

    ``created`` is the result-message append's own idempotency answer: a run
    whose conversation message already existed is a re-projection, not a new
    event, so it is skipped and cannot produce a duplicate notification.
    """

    if push_store is None:
        return AutomationPushOutcome(state="not_configured")
    if not created:
        # Re-projection of an existing result message: not a new event.
        return AutomationPushOutcome(state="duplicate")
    if not workspace_id or not member_id:
        return AutomationPushOutcome(state="not_configured")
    title, body, url = _notification_text(
        run_status=run_status, conversation_url=conversation_url
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
    "CONVERSATION_LINK_PATH",
    "AutomationPushOutcome",
    "notify_terminal_run",
]
