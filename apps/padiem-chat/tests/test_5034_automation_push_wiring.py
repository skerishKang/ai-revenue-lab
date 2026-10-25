"""#5034 — the automation terminal event actually reaches the push seam.

NETWORK_FREE. This pins the wiring, not the crypto (that is
``test_5034_web_push_sender.py``) and not the subscription store (that is
``test_5034_claw_push_subscription.py``).

The question this file answers: when an existing scheduled automation run
reaches a terminal state, does the EXISTING inbox projection still happen
unchanged, and does a device notification additionally get attempted exactly
once for that event?

Pinned here:

- EVENT_REACHES_PUSH=PASS (a COMPLETED run with an ALERT output notifies)
- INBOX_PROJECTION_UNCHANGED=PASS (the existing Task/Alert write still happens)
- DEDUP_BY_RUN=PASS (a re-projected run does not notify twice)
- PUSH_FAILURE_NEVER_RERUNS_JOB=PASS (a failing sender changes nothing)
- PUSH_FAILURE_NEVER_RAISES=PASS (the automation lane result is unaffected)
- NO_PUSH_STORE_IS_A_NOOP=PASS (an unconfigured deployment is silent)
- MINIMAL_LOCK_SCREEN=PASS (only a short status and an inbox link)
- ACCOUNT_ISOLATION=PASS (the notification is scoped to the run's own owner)
"""

from __future__ import annotations

from typing import Any

import pytest

from app.claw_automation_background_execution import _project_terminal_run
from app.claw_automation_push_notification import (
    INBOX_ALERTS_PATH,
    INBOX_TASKS_PATH,
    notify_terminal_run,
)
from app.claw_push_subscriptions import (
    D1ClawPushSubscriptionStore,
    PushDeliveryOutcome,
    PushSubscription,
    deliver_inbox_push,
)

WORKSPACE = "ws_owner"
MEMBER = "usr_" + "7" * 32
OTHER_MEMBER = "usr_" + "f" * 32
SCOPE = "https://chat.example.test/"


class _RecordingStore:
    """The subscription store surface ``deliver_inbox_push`` consumes."""

    def __init__(self, subscriptions: list[PushSubscription] | None = None) -> None:
        self.subscriptions = subscriptions or []
        self.unregistered: list[str] = []

    async def list_for(
        self, *, workspace_id: str, member_id: str, scope: str | None = None
    ) -> list[PushSubscription]:
        return [
            item
            for item in self.subscriptions
            if item.workspace_id == workspace_id and item.member_id == member_id
        ]

    async def unregister(
        self, *, workspace_id: str, member_id: str, subscription_id: str
    ) -> bool:
        self.unregistered.append(subscription_id)
        return True


def _subscription(member_id: str = MEMBER) -> PushSubscription:
    return PushSubscription(
        subscription_id="push_" + "a" * 32,
        workspace_id=WORKSPACE,
        member_id=member_id,
        endpoint="https://fcm.googleapis.com/wp/device-1",
        p256dh="p256dh-key",
        auth="auth-secret",
        scope=SCOPE,
        created_at="2026-10-23T00:00:00Z",
        updated_at="2026-10-23T00:00:00Z",
    )


class _RecordingSender:
    def __init__(self, *, delivered: bool = True, raises: bool = False) -> None:
        self.delivered = delivered
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def send(
        self, *, subscription: Any, title: str, body: str, url: str | None = None
    ) -> Any:
        self.calls.append(
            {
                "subscription_id": subscription.subscription_id,
                "title": title,
                "body": body,
                "url": url,
            }
        )
        if self.raises:
            raise RuntimeError("push service exploded")
        return type("Result", (), {"delivered": self.delivered, "gone": False})()


# --------------------------------------------------------------------------
# the event reaches the seam
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_alert_run_notifies_the_owner_device() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()

    outcome = await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="COMPLETED",
    )

    assert outcome.state == "delivered"
    assert outcome.delivered == 1
    assert len(sender.calls) == 1
    assert sender.calls[0]["url"] == INBOX_ALERTS_PATH


@pytest.mark.asyncio
async def test_task_output_links_to_the_task_inbox() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()

    await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="task",
        created=True,
        run_status="COMPLETED",
    )

    assert sender.calls[0]["url"] == INBOX_TASKS_PATH


@pytest.mark.asyncio
async def test_the_push_links_to_the_run_that_produced_the_result() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()
    run_id = "sched_run_" + "b" * 64

    await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="COMPLETED",
        run_id=run_id,
    )

    # #5034: the lock-screen notification opens the original run, not an
    # undifferentiated list. The reference is the only thing the URL carries.
    assert sender.calls[0]["url"] == f"/claw?notify=run&run_id={run_id}"
    assert "title" not in sender.calls[0]["url"]


@pytest.mark.asyncio
async def test_a_reference_outside_the_run_grammar_falls_back_to_the_inbox() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()

    for forged in (
        "../../other", "run/../x", "", None,
        "sched_run_" + "b" * 130, "run id with spaces",
    ):
        await notify_terminal_run(
            push_store=store,
            push_sender=sender,
            workspace_id=WORKSPACE,
            member_id=MEMBER,
            scope=SCOPE,
            created_kind="alert",
            created=True,
            run_status="COMPLETED",
            run_id=forged,
        )

    assert [call["url"] for call in sender.calls] == [INBOX_ALERTS_PATH] * 6


@pytest.mark.asyncio
async def test_failed_run_uses_failure_wording() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()

    await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="FAILED",
    )

    assert "실패" in sender.calls[0]["title"]


# --------------------------------------------------------------------------
# dedup: a re-projection is not a new event
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reprojected_run_does_not_notify_twice() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()

    first = await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="COMPLETED",
    )
    second = await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=False,
        run_status="COMPLETED",
    )

    assert first.state == "delivered"
    assert second.state == "duplicate"
    assert len(sender.calls) == 1, "a re-projection must not send a second push"


# --------------------------------------------------------------------------
# failure containment
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failing_sender_never_raises_into_the_automation_lane() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender(raises=True)

    outcome = await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="COMPLETED",
    )

    assert outcome.state == "failed"
    assert outcome.inbox_state_changed is False


@pytest.mark.asyncio
async def test_no_push_store_is_a_silent_noop() -> None:
    outcome = await notify_terminal_run(
        push_store=None,
        push_sender=None,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="COMPLETED",
    )
    assert outcome.state == "not_configured"


@pytest.mark.asyncio
async def test_no_subscription_reports_no_subscription() -> None:
    outcome = await notify_terminal_run(
        push_store=_RecordingStore([]),
        push_sender=_RecordingSender(),
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="COMPLETED",
    )
    assert outcome.state == "no_subscription"


# --------------------------------------------------------------------------
# isolation and gone-subscription cleanup
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_another_members_device_is_never_notified() -> None:
    store = _RecordingStore([_subscription(OTHER_MEMBER)])
    sender = _RecordingSender()

    outcome = await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="COMPLETED",
    )

    assert outcome.state == "no_subscription"
    assert sender.calls == []


@pytest.mark.asyncio
async def test_gone_device_is_dropped_from_the_store() -> None:
    store = _RecordingStore([_subscription()])

    class _GoneSender:
        async def send(self, *, subscription: Any, title: str, body: str, url: Any = None) -> Any:
            return type("Result", (), {"delivered": False, "gone": True})()

    outcome = await deliver_inbox_push(
        store=store,
        sender=_GoneSender(),
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        title="t",
        body="b",
    )

    assert outcome.state == "failed"
    assert store.unregistered == ["push_" + "a" * 32]


@pytest.mark.asyncio
async def test_minimal_lock_screen_payload() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()

    await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        created_kind="alert",
        created=True,
        run_status="COMPLETED",
    )

    call = sender.calls[0]
    # A short status and a link. No run output, no document content, no ids.
    assert len(call["title"]) <= 120
    assert len(call["body"]) <= 200
    assert call["url"].startswith("/claw")
    assert "endpoint" not in call["body"]


# --------------------------------------------------------------------------
# the failure result reaches the same seam exactly once
# --------------------------------------------------------------------------


def _owner_subscription(owner) -> PushSubscription:
    return PushSubscription(
        subscription_id="push_" + "a" * 32,
        workspace_id=owner.workspace_id,
        member_id=owner.member_id,
        endpoint="https://fcm.googleapis.com/wp/device-1",
        p256dh="p256dh-key",
        auth="auth-secret",
        scope=SCOPE,
        created_at="2026-10-23T00:00:00Z",
        updated_at="2026-10-23T00:00:00Z",
    )


def _failed_terminal_pair():
    """The background lane's own rule/run fixtures: a real execution intent."""

    from kagent.claw_automation import ClawScheduledRunStatus
    from test_claw_automation_background_execution import (
        OWNER_USER,
        SUBJECT,
        make_rule,
        scheduled_run,
    )

    from app.claw_automation_owner_resolution import ResolvedAutomationOwner

    rule = make_rule()
    row = scheduled_run(rule=rule, status=ClawScheduledRunStatus.FAILED)
    owner = ResolvedAutomationOwner(
        workspace_id=rule.workspace_id,
        owner_ref=rule.owner_ref or "owner:opaque:0001",
        product_user_id=OWNER_USER,
        member_id="member_0001",
        canonical_subject_id=SUBJECT,
    )
    return rule, row, owner


async def _project_failed_terminal(store, sender, alerts, *, owner, rule, row):
    from test_claw_automation_background_execution import RecordingHistoryStore

    await _project_terminal_run(
        rule=rule,
        scheduled_run=row,
        owner=owner,
        history_store=RecordingHistoryStore(),
        task_alert_store=alerts,
        push_store=store,
        push_sender=sender,
        push_scope=SCOPE,
    )


@pytest.mark.asyncio
async def test_a_failed_run_reaches_the_push_seam_once() -> None:
    """#5034 option 1: the failure wording is only reachable through the record.

    Before the status boundary existed, a FAILED row projected nothing, so
    ``created`` stayed False and the notification was skipped as a duplicate.
    """

    from test_claw_automation_background_execution import RecordingTaskAlertStore

    rule, row, owner = _failed_terminal_pair()
    alerts = RecordingTaskAlertStore()
    store = _RecordingStore([_owner_subscription(owner)])
    sender = _RecordingSender()

    await _project_failed_terminal(store, sender, alerts, owner=owner, rule=rule, row=row)

    assert alerts.add_alert_calls == 1
    assert len(sender.calls) == 1
    assert sender.calls[0]["title"] == "자동화 실패"
    assert sender.calls[0]["url"].startswith("/claw")

    # A re-projection of the same terminal row is not a new event.
    second = _RecordingSender()
    await _project_failed_terminal(
        _RecordingStore([_owner_subscription(owner)]), second, alerts,
        owner=owner, rule=rule, row=row,
    )
    assert second.calls == []
