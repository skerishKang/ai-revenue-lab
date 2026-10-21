"""Continuation race tests (#2786 S13-4 Phase 2 follow-up, T13).

The lifecycle must survive two requests aimed at the same continuation. Protection
already exists in the store contract (claim/commit CAS); these tests pin the
observable outcome: exactly one winner, exactly one execution, a single terminal
state, no double cancel.

A loser observes the state that was true when it arrived, which may still be a
claim in flight. Both in-flight codes are published 409s with their own retry
protocol, so they are truthful answers rather than anomalies; what every race
must guarantee is the single terminal state afterwards.

The service path is exercised concurrently on one event loop, and the CAS contract
itself is exercised deterministically at the store boundary, because the in-memory
reference store is synchronous. The event loop decides which request claims first,
so the loser's in-flight code cannot be pinned per run; both interleavings are
pinned deterministically at the store boundary instead.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

import pytest

from padiem_ai_core.agent_approval import ApprovalPause, ApprovalRequirement

from app.service import ServiceContractError

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from agent_pause_fixture import (  # noqa: E402
    APP_ID,
    RUNTIME_TOOL,
    PausedRunFixture,
)

CANCEL_CODES = {"continuation_cancelled", "continuation_cancel_in_progress"}
TERMINAL_CODES = {"continuation_cancelled", "continuation_consumed"}
# The continuation state vocabulary is closed, and it distinguishes a claim that
# is still in flight from one that has already settled:
#
#   claimed    -> continuation_claimed              (a resume owns the claim)
#   cancelling -> continuation_cancel_in_progress   (a cancel owns the claim)
#   cancelled  -> continuation_cancelled            (terminal)
#   consumed   -> continuation_consumed             (terminal)
#
# A request that loses a race observes whatever state was true at that instant.
# Both in-flight codes are published 409s with their own retry protocol
# (SAME_CONTINUATION_REF / SAME_CONTINUATION_REF), so an in-flight observation
# is a truthful answer, not an anomaly. What the lifecycle must guarantee is the
# outcome below: exactly one owner, exactly one execution, and one terminal
# state that neither request can revive.
IN_FLIGHT_CODES = {"continuation_claimed", "continuation_cancel_in_progress"}
RACE_LOSER_CODES = IN_FLIGHT_CODES | TERMINAL_CODES


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _pause_and_ref(fixture: PausedRunFixture) -> tuple[str, str]:
    response = _run(fixture.service.run_payload(fixture.run_payload()))
    assert response.status_code == 202, response.body
    return (
        response.body["continuation_ref"],
        response.body["agent_skill"]["approval_pause"]["continuation_id"],
    )


def _active_pause() -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_race_fixture0001",
        run_id="bridge_run_race00000001",
        agent_runtime_id="agent:core:pause@1",
        tool_id=RUNTIME_TOOL,
        invocation_sha256="c" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        trace_id="agtr_racefixture00000001",
    )


# --- concurrent cancel ----------------------------------------------------


def test_concurrent_cancel_has_exactly_one_winner() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)

    async def _both() -> Any:
        return await asyncio.gather(
            fixture.service.cancel_payload(fixture.cancel_payload(ref)),
            fixture.service.cancel_payload(fixture.cancel_payload(ref)),
        )

    first, second = _run(_both())

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    loser = first if first.status_code == 409 else second
    assert loser.body["error"]["code"] in CANCEL_CODES

    # A single terminal state survives, and it keeps refusing further cancels.
    follow_up = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert follow_up.status_code == 409
    assert follow_up.body["error"]["code"] == "continuation_cancelled"
    assert fixture.runtime.calls == 0


def test_cancel_claim_is_single_use_and_token_bound() -> None:
    fixture = PausedRunFixture()
    ref = fixture.store.issue(app_id=APP_ID, pause=_active_pause(), plan_id=None)

    claimed = fixture.store.claim_cancel(
        app_id=APP_ID, continuation_ref=ref, reason="user_cancelled"
    )
    assert claimed.state == "cancelling"
    assert claimed.claim_token

    # A second claim cannot start while the first cancel is in flight.
    with pytest.raises(ServiceContractError) as second_claim:
        fixture.store.claim_cancel(
            app_id=APP_ID, continuation_ref=ref, reason="user_cancelled"
        )
    assert second_claim.value.code == "continuation_cancel_in_progress"

    # A stale or foreign token cannot commit the cancellation.
    with pytest.raises(ServiceContractError) as stale_commit:
        fixture.store.commit_cancel(
            app_id=APP_ID, continuation_ref=ref, claim_token="cancel_not_the_claim"
        )
    assert stale_commit.value.code == "continuation_cancel_claim_failed"

    committed = fixture.store.commit_cancel(
        app_id=APP_ID, continuation_ref=ref, claim_token=claimed.claim_token
    )
    assert committed.state == "cancelled"
    assert committed.claim_token is None
    assert committed.cancel_event_fingerprint
    assert committed.cancel_event_fingerprint.startswith("evt_")

    # After the commit the continuation can never be claimed again.
    with pytest.raises(ServiceContractError) as replay:
        fixture.store.claim_cancel(
            app_id=APP_ID, continuation_ref=ref, reason="user_cancelled"
        )
    assert replay.value.code == "continuation_cancelled"
    with pytest.raises(ServiceContractError) as replay_commit:
        fixture.store.commit_cancel(
            app_id=APP_ID, continuation_ref=ref, claim_token=claimed.claim_token
        )
    assert replay_commit.value.code == "continuation_cancel_claim_failed"


# --- concurrent resume against cancel ------------------------------------


def test_concurrent_resume_and_cancel_are_mutually_exclusive() -> None:
    fixture = PausedRunFixture()
    ref, pause_id = _pause_and_ref(fixture)
    assert fixture.tool_calls == 0, "entering the pause must not execute the gated write"
    fixture.pre_confirmed = True

    async def _both() -> Any:
        return await asyncio.gather(
            fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)),
            fixture.service.cancel_payload(fixture.cancel_payload(ref)),
        )

    resumed, cancelled = _run(_both())

    winners = [r for r in (resumed, cancelled) if r.status_code == 200]
    assert len(winners) == 1, "exactly one request may own the continuation"
    loser = cancelled if resumed.status_code == 200 else resumed
    assert loser.status_code == 409
    assert loser.body["error"]["code"] in RACE_LOSER_CODES

    # Exactly-once execution: the confirmation-gated write runs only when the
    # resume actually owned the claim, and it never runs twice.
    resume_won = resumed.status_code == 200
    assert fixture.tool_calls == (1 if resume_won else 0)
    # The pause fixture's provider sentinel is never reached on either outcome.
    assert fixture.runtime.calls == 0

    # Whatever won, the continuation now has exactly one terminal state. Both
    # directions are refused with a terminal code, so no request can revive the
    # continuation, take a second claim, or re-run the write.
    follow_up_cancel = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert follow_up_cancel.status_code == 409
    assert follow_up_cancel.body["error"]["code"] in TERMINAL_CODES
    follow_up_resume = _run(
        fixture.service.resume_payload(fixture.resume_payload(ref, pause_id))
    )
    assert follow_up_resume.status_code == 409
    assert follow_up_resume.body["error"]["code"] in TERMINAL_CODES
    assert fixture.tool_calls == (1 if resume_won else 0)
    assert fixture.runtime.calls == 0


# --- both interleavings, pinned deterministically at the store boundary ----


def test_the_store_names_each_in_flight_claim_truthfully() -> None:
    """A loser observes the claim that is actually held, in both directions.

    The reference store is synchronous, so these orders are deterministic: the
    service-level race above cannot pin which request reaches the claim first.
    """

    # A resume holds the claim: a cancel arriving now cannot take it.
    resumed = PausedRunFixture()
    resume_ref = resumed.store.issue(app_id=APP_ID, pause=_active_pause(), plan_id=None)
    resumed.store.claim(app_id=APP_ID, continuation_ref=resume_ref)
    with pytest.raises(ServiceContractError) as cancel_loses:
        resumed.store.claim_cancel(
            app_id=APP_ID, continuation_ref=resume_ref, reason="user_cancelled"
        )
    assert cancel_loses.value.code == "continuation_claimed"

    # A cancel holds the claim: a resume arriving now cannot take it.
    cancelled = PausedRunFixture()
    cancel_ref = cancelled.store.issue(app_id=APP_ID, pause=_active_pause(), plan_id=None)
    cancelled.store.claim_cancel(
        app_id=APP_ID, continuation_ref=cancel_ref, reason="user_cancelled"
    )
    with pytest.raises(ServiceContractError) as resume_loses:
        cancelled.store.claim(app_id=APP_ID, continuation_ref=cancel_ref)
    assert resume_loses.value.code == "continuation_cancel_in_progress"


def test_a_second_resume_can_never_take_the_claim_or_re_execute() -> None:
    """The CAS claim is the single-owner gate, so no second execution is possible."""

    fixture = PausedRunFixture()
    ref = fixture.store.issue(app_id=APP_ID, pause=_active_pause(), plan_id=None)
    first = fixture.store.claim(app_id=APP_ID, continuation_ref=ref)
    with pytest.raises(ServiceContractError) as second:
        fixture.store.claim(app_id=APP_ID, continuation_ref=ref)
    assert second.value.code == "continuation_claimed"

    # The holder still owns and can settle it exactly once.
    fixture.store.commit(
        app_id=APP_ID, continuation_ref=ref, claim_token=first.claim_token or ""
    )
    with pytest.raises(ServiceContractError) as after:
        fixture.store.claim(app_id=APP_ID, continuation_ref=ref)
    assert after.value.code == "continuation_consumed"
    with pytest.raises(ServiceContractError) as stale:
        fixture.store.commit(
            app_id=APP_ID, continuation_ref=ref, claim_token=first.claim_token or ""
        )
    assert stale.value.code == "continuation_consumed"
