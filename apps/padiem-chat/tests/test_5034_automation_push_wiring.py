"""#5034 — the automation terminal event actually reaches the push seam.

NETWORK_FREE. This pins the wiring, not the crypto (that is
``test_5034_web_push_sender.py``) and not the subscription store (that is
``test_5034_claw_push_subscription.py``).

The question this file answers: when an existing scheduled automation run
reaches a terminal state, does the notification fire directly from that
terminal state (대표 결정 2026-11-07: COMPLETED 성공, FAILED/CANCELLED 실패,
출력·작업함 투사 무관), click through to the automation's own conversation,
and get attempted exactly once per event?

Pinned here:

- EVENT_REACHES_PUSH=PASS (a COMPLETED run notifies, output or not; the
  Task/Alert projection is gone with the inbox — PR2)
- TERMINAL_DECIDES=PASS (FAILED/CANCELLED use the failure wording)
- CLICK_TARGET_CONVERSATION=PASS (the URL is the automation conversation)
- DEDUP_BY_RUN=PASS (a re-projected run does not notify twice)
- PUSH_FAILURE_NEVER_RERUNS_JOB=PASS (a failing sender changes nothing)
- PUSH_FAILURE_NEVER_RAISES=PASS (the automation lane result is unaffected)
- NO_PUSH_STORE_IS_A_NOOP=PASS (an unconfigured deployment is silent)
- MINIMAL_LOCK_SCREEN=PASS (only a short status and the conversation link)
- ACCOUNT_ISOLATION=PASS (the notification is scoped to the run's own owner)
"""

from __future__ import annotations

from typing import Any

import pytest

from app.claw_automation_background_execution import _project_terminal_run
from app.claw_automation_push_notification import (
    CONVERSATION_LINK_PATH,
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
async def test_completed_run_notifies_the_owner_device() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()
    conversation_url = CONVERSATION_LINK_PATH.format(conversation_id="chat_" + "3" * 32)

    outcome = await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        run_status="COMPLETED",
        created=True,
        conversation_url=conversation_url,
    )

    assert outcome.state == "delivered"
    assert outcome.delivered == 1
    assert len(sender.calls) == 1
    assert sender.calls[0]["url"] == conversation_url


@pytest.mark.asyncio
async def test_the_push_links_to_the_automation_conversation() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()
    conversation_url = CONVERSATION_LINK_PATH.format(conversation_id="chat_" + "4" * 32)

    await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        run_status="COMPLETED",
        created=True,
        conversation_url=conversation_url,
    )

    # 대표 결정(2026-11-07): the lock-screen notification opens the automation's
    # own conversation. The reference is the only thing the URL carries — no
    # result body, no run output ever rides the lock screen.
    assert sender.calls[0]["url"] == conversation_url
    assert sender.calls[0]["title"] == "자동화 완료"
    assert sender.calls[0]["body"] == "예약 작업이 완료되었습니다."
    assert "run_id" not in sender.calls[0]["url"]


@pytest.mark.asyncio
async def test_a_missing_conversation_url_sends_no_link_at_all() -> None:
    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()

    await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        run_status="COMPLETED",
        created=True,
        conversation_url=None,
    )

    call = sender.calls[0]
    # The inbox deep link is gone; a notification without a target still
    # reaches the device and simply focuses the app when tapped.
    assert call["url"] is None
    assert call["title"] == "자동화 완료"


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
        run_status="FAILED",
        created=True,
    )

    assert "실패" in sender.calls[0]["title"]


@pytest.mark.asyncio
async def test_cancelled_run_uses_failure_wording_too() -> None:
    """TERMINAL_DECIDES: CANCELLED is not COMPLETED, so it is a failure."""

    store = _RecordingStore([_subscription()])
    sender = _RecordingSender()

    await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        run_status="CANCELLED",
        created=True,
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
        run_status="COMPLETED",
        created=True,
    )
    second = await notify_terminal_run(
        push_store=store,
        push_sender=sender,
        workspace_id=WORKSPACE,
        member_id=MEMBER,
        scope=SCOPE,
        run_status="COMPLETED",
        created=False,
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
        run_status="COMPLETED",
        created=True,
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
        run_status="COMPLETED",
        created=True,
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
        run_status="COMPLETED",
        created=True,
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
        run_status="COMPLETED",
        created=True,
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
        run_status="COMPLETED",
        created=True,
        conversation_url=CONVERSATION_LINK_PATH.format(
            conversation_id="chat_" + "5" * 32
        ),
    )

    call = sender.calls[0]
    # A short status and the conversation link. No run output, no document
    # content, no ids.
    assert len(call["title"]) <= 120
    assert len(call["body"]) <= 200
    assert call["url"].startswith("/?notify=conversation&conversation_id=chat_")
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


@pytest.mark.asyncio
async def test_a_failed_run_reaches_the_push_seam_once() -> None:
    """대표 결정(2026-11-07): one automation owns one conversation — the first
    terminal projection ensured it, appended the result message once and
    linked the run row to it; the notification fires straight from the
    terminal state.
    """

    from test_claw_automation_background_execution import RecordingHistoryStore

    rule, row, owner = _failed_terminal_pair()
    history = RecordingHistoryStore()
    store = _RecordingStore([_owner_subscription(owner)])
    sender = _RecordingSender()

    await _project_terminal_run(
        rule=rule,
        scheduled_run=row,
        owner=owner,
        history_store=history,
        push_store=store,
        push_sender=sender,
        push_scope=SCOPE,
    )
    assert len(history.ensure_calls) == 1
    assert history.ensure_calls[0]["user_id"] == owner.product_user_id
    assert history.ensure_calls[0]["rule_id"] == rule.rule_id
    assert len(history.message_calls) == 1
    assert history.message_calls[0]["message_id"] == row.run_id + "_result"
    assert history.record_calls[0]["conversation_id"] == history._automation_conversation
    assert len(sender.calls) == 1
    assert sender.calls[0]["title"] == "자동화 실패"
    assert sender.calls[0]["url"].startswith("/?notify=conversation&conversation_id=chat_")

    # A re-projection of the same terminal row is not a new event: the result
    # message already exists in the SAME history store, so the idempotent
    # append reports False and the device attempt is skipped entirely.
    second = _RecordingSender()
    await _project_terminal_run(
        rule=rule,
        scheduled_run=row,
        owner=owner,
        history_store=history,
        push_store=_RecordingStore([_owner_subscription(owner)]),
        push_sender=second,
        push_scope=SCOPE,
    )
    assert second.calls == []


@pytest.mark.asyncio
async def test_a_completed_run_without_output_still_notifies() -> None:
    """TERMINAL_DECIDES: COMPLETED is a success regardless of the output.

    A REPORT/DRAFT rule's COMPLETED run materializes no Task/Alert record (the
    status boundary answers nothing for it), which is exactly the case the old
    created-signal skipped — the terminal state alone decides now.
    """

    from kagent.claw_automation import ClawAutomationOutputType, ClawScheduledRunStatus

    from test_claw_automation_background_execution import (
        RecordingHistoryStore,
        make_rule,
        scheduled_run,
    )

    rule = make_rule(output_type=ClawAutomationOutputType.REPORT)
    row = scheduled_run(rule=rule, status=ClawScheduledRunStatus.COMPLETED)
    owner = _failed_terminal_pair()[2]
    store = _RecordingStore([_owner_subscription(owner)])
    sender = _RecordingSender()
    history = RecordingHistoryStore()

    await _project_terminal_run(
        rule=rule,
        scheduled_run=row,
        owner=owner,
        history_store=history,
        push_store=store,
        push_sender=sender,
        push_scope=SCOPE,
    )

    assert len(sender.calls) == 1
    assert sender.calls[0]["title"] == "자동화 완료"
    assert sender.calls[0]["url"].startswith("/?notify=conversation&conversation_id=chat_")
    assert len(history.message_calls) == 1
    assert "완료" in history.message_calls[0]["content"]
