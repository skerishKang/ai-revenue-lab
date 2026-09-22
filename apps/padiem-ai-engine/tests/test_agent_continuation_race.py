"""Continuation race tests (#2786 S13-4 Phase 2 follow-up, T13).

The lifecycle must survive two requests aimed at the same continuation. Protection
already exists in the store contract (claim/commit CAS); these tests pin the
observable outcome: exactly one winner, a single terminal state, no double cancel.

The service path is exercised concurrently on one event loop, and the CAS contract
itself is exercised deterministically at the store boundary, because the in-memory
reference store is synchronous.
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
    fixture.pre_confirmed = True

    async def _both() -> Any:
        return await asyncio.gather(
            fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)),
            fixture.service.cancel_payload(fixture.cancel_payload(ref)),
        )

    resumed, cancelled = _run(_both())

    winners = [r for r in (resumed, cancelled) if r.status_code == 200]
    assert len(winners) == 1
    loser = cancelled if resumed.status_code == 200 else resumed
    assert loser.status_code == 409
    assert loser.body["error"]["code"] in TERMINAL_CODES

    # Whatever won, the continuation now has exactly one terminal state.
    follow_up = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert follow_up.status_code == 409
    assert follow_up.body["error"]["code"] in TERMINAL_CODES
    assert fixture.runtime.calls == 0
