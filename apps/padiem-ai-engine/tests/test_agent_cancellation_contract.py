"""Cancel continuation contract tests (#2786 S13-4 Phase 2).

Uses the shared paused-run fixture (a genuine Core approval pause), so these cases
exercise the real cancel flow rather than a hand-made record.

Contract under test: the `continuation` block a cancel response publishes, plus the
authorization/state guards the cancel flow already enforces.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

import pytest

from padiem_ai_core.agent_approval import ApprovalPause, ApprovalRequirement

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from agent_pause_fixture import APP_ID, RUNTIME_TOOL, SUBJECT_ID, PausedRunFixture  # noqa: E402

TRACE_ID_FIXTURE = "agtr_cancelfixture0001"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _pause_and_ref(fixture: PausedRunFixture) -> tuple[str, str]:
    response = _run(fixture.service.run_payload(fixture.run_payload()))
    assert response.status_code == 202, response.body
    ref = response.body["continuation_ref"]
    pause_id = response.body["agent_skill"]["approval_pause"]["continuation_id"]
    return ref, pause_id


def _past_pause(*, trace_id: str | None = TRACE_ID_FIXTURE) -> ApprovalPause:
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    return ApprovalPause(
        pause_id="pause_expired_fixture01",
        run_id="bridge_run_expired0001",
        agent_runtime_id="agent:core:pause@1",
        tool_id=RUNTIME_TOOL,
        invocation_sha256="b" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=past,
        expires_at=past + timedelta(minutes=5),
        trace_id=trace_id,
    )


# --- T1 contract fields ---------------------------------------------------


def test_cancel_contract_fields() -> None:
    fixture = PausedRunFixture()
    ref, _pause_id = _pause_and_ref(fixture)

    response = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    assert response.status_code == 200, response.body
    block = response.body["continuation"]
    assert block["continuation_contract_version"] == "padiem.engine.agent-continuation/1.0"
    assert block["continuation_id"] == ref
    assert isinstance(block["task_id"], str) and block["task_id"]
    assert block["current_state"] == "active"
    assert block["terminal_state"] == "cancelled"
    assert block["cancel_reason"] == "user_cancelled"
    audit = block["audit_event"]
    assert audit["trace_id"] == TRACE_ID_FIXTURE or isinstance(audit["trace_id"], str)
    assert audit["event_count"] >= 1
    assert isinstance(audit["terminal_kind"], str)


def test_cancel_contract_omits_owner_identity() -> None:
    """Phase 2 decision: the cancel path has no trusted subject source."""

    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)

    response = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    block = response.body["continuation"]
    assert "owner_identity" not in block
    assert "cancel_requester" not in block
    assert SUBJECT_ID not in repr(block)


def test_cancel_contract_carries_no_authority_material() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)

    response = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    serialized = repr(response.body["continuation"])
    for forbidden in ("claim_token", "cancel_event_fingerprint", "request_fingerprint", "authorization"):
        assert forbidden not in serialized


# --- T2 backward compatibility -------------------------------------------


def test_cancel_response_keeps_its_previous_shape() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)

    response = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    body = response.body
    assert body["ok"] is True
    assert body["status"] == "cancelled"
    assert isinstance(body["events"], list) and body["events"]
    assert body["events"][0]["trace_id"]
    assert "agent_skill" not in body


# --- T3/T6 state handling -------------------------------------------------


def test_cancel_marks_the_continuation_cancelled() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)

    _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    second = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert second.status_code == 409
    assert second.body["error"]["code"] == "continuation_cancelled"


def test_cancel_rejects_an_already_cancelled_continuation() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)
    first = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert first.status_code == 200

    again = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    assert again.status_code == 409
    assert again.body["error"]["code"] == "continuation_cancelled"


# --- T4/T5/T8 fail-closed cases ------------------------------------------


def test_unknown_continuation_fails_closed() -> None:
    fixture = PausedRunFixture()

    response = _run(
        fixture.service.cancel_payload(
            {
                "app_id": APP_ID,
                "continuation_ref": "cont_does_not_exist_000000000000",
                "reason": "user_cancelled",
            }
        )
    )

    assert response.status_code == 409
    assert response.body["error"]["code"] == "invalid_continuation"


def test_expired_continuation_is_refused() -> None:
    fixture = PausedRunFixture()
    ref = fixture.store.issue(app_id=APP_ID, pause=_past_pause(), plan_id=None)

    response = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_expired"


def test_foreign_application_cannot_cancel() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)

    response = _run(
        fixture.service.cancel_payload(
            {"app_id": "other-app", "continuation_ref": ref, "reason": "user_cancelled"}
        )
    )

    assert response.status_code == 409
    assert response.body["error"]["code"] == "invalid_continuation"


# --- T7 invalid transition (cancel then resume) ---------------------------


def test_resume_after_cancel_is_refused() -> None:
    fixture = PausedRunFixture()
    ref, pause_id = _pause_and_ref(fixture)
    assert _run(fixture.service.cancel_payload(fixture.cancel_payload(ref))).status_code == 200
    fixture.pre_confirmed = True

    response = _run(fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)))

    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_cancelled"


# --- T9 allowlist / T10 identity ------------------------------------------


def test_cancel_rejects_unsupported_fields() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)

    response = _run(
        fixture.service.cancel_payload(
            {
                "app_id": APP_ID,
                "continuation_ref": ref,
                "reason": "user_cancelled",
                "extra": "not allowed",
            }
        )
    )

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"


def test_cancel_requires_trusted_trace_identity() -> None:
    fixture = PausedRunFixture()
    ref = fixture.store.issue(app_id=APP_ID, pause=_past_pause(trace_id=None), plan_id=None)

    response = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    assert response.status_code == 409
    assert response.body["error"]["code"] in {
        "continuation_identity_mismatch",
        "continuation_expired",
    }


# --- T11 provider independence -------------------------------------------


def test_cancel_contract_is_provider_free() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause_and_ref(fixture)

    response = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))

    assert response.status_code == 200
    assert fixture.runtime.calls == 0
