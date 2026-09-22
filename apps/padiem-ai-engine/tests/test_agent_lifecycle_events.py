"""Continuation lifecycle event tests (#2786 S13-4 Phase 3).

Two planes are pinned here.  The frozen core run event plane (``events``) is not
touched; the continuation lifecycle stream (``lifecycle_events``) is projected next
to it, from transitions the coordinator already performed.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

import pytest

from padiem_ai_core.agent_approval import ApprovalPause, ApprovalRequirement

from app.agent_skill_continuation_projection import (
    ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION,
    project_agent_lifecycle_events,
)
from app.service import ServiceContractError

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from agent_pause_fixture import APP_ID, RUNTIME_TOOL, PausedRunFixture  # noqa: E402

LIFECYCLE_EVENT_KEYS = {
    "event_id",
    "continuation_id",
    "task_id",
    "trace_id",
    "sequence",
    "kind",
    "terminal",
    "timestamp_iso",
    "derived_from",
    "source_event_id",
}
RESUME_BLOCK_KEYS = {
    "continuation_contract_version",
    "continuation_id",
    "task_id",
    "owner_identity",
    "current_state",
    "resume_target_state",
    "resume_authority",
    "lifecycle_contract_version",
    "lifecycle_events",
    "audit_event",
}
CANCEL_BLOCK_KEYS = {
    "continuation_contract_version",
    "continuation_id",
    "task_id",
    "current_state",
    "terminal_state",
    "cancel_reason",
    "lifecycle_contract_version",
    "lifecycle_events",
    "audit_event",
}
FORBIDDEN_EVENT_KEYS = {
    "claim_token",
    "cancel_event_fingerprint",
    "caller_id",
    "subject_id",
    "authority",
    "decision",
    "approval_decision",
    "resume_authority",
}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _pause(fixture: PausedRunFixture) -> tuple[str, str]:
    response = _run(fixture.service.run_payload(fixture.run_payload()))
    assert response.status_code == 202, response.body
    return (
        response.body["continuation_ref"],
        response.body["agent_skill"]["approval_pause"]["continuation_id"],
    )


def _expired_pause() -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_lifecycle_expired01",
        run_id="bridge_run_lifecycle0001",
        agent_runtime_id="agent:core:pause@1",
        tool_id=RUNTIME_TOOL,
        invocation_sha256="d" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
        trace_id="agtr_lifecycleexpired0001",
    )


# --- T1 ordering -----------------------------------------------------------


def test_t1_lifecycle_sequence_is_ordered_and_independent_of_run_sequence() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause(fixture)

    cancelled = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert cancelled.status_code == 200, cancelled.body

    events = cancelled.body["continuation"]["lifecycle_events"]
    assert [event["sequence"] for event in events] == [1, 2]
    assert [event["kind"] for event in events] == ["cancel_requested", "cancelled"]
    assert len({event["event_id"] for event in events}) == 2

    # The core plane restarts its sequence at 1 on the cancel path; the lifecycle
    # stream carries its own sequence and never borrows the run sequence.
    run_sequences = [event["sequence"] for event in cancelled.body["events"]]
    assert run_sequences == [1]


# --- T2 duplicate transition ----------------------------------------------


def test_t2_repeat_transition_emits_no_duplicate_lifecycle_event() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause(fixture)

    first = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert first.status_code == 200

    repeat = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert repeat.status_code == 409
    assert repeat.body["error"]["code"] == "continuation_cancelled"
    assert "lifecycle_events" not in repeat.body
    assert "continuation" not in repeat.body

    # The projection itself is deterministic, so a repeated observation cannot
    # accumulate new identities for the same transition.
    once = project_agent_lifecycle_events(continuation_id=ref, transition="cancel")
    twice = project_agent_lifecycle_events(continuation_id=ref, transition="cancel")
    assert once == twice


# --- T3 resume/cancel consistency (includes the CENTRAL-required assertion) --


def test_t3_resume_response_projects_the_resumed_lifecycle_event() -> None:
    fixture = PausedRunFixture()
    ref, pause_id = _pause(fixture)
    fixture.pre_confirmed = True

    resumed = _run(fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)))
    assert resumed.status_code == 200, resumed.body

    events = resumed.body["continuation"]["lifecycle_events"]
    assert [event["kind"] for event in events] == ["resume_requested", "resumed"]
    assert "resumed" in [event["kind"] for event in events]
    assert events[0]["derived_from"] == "store_transition"
    assert events[0]["source_event_id"] is None

    terminal = events[-1]
    assert terminal["terminal"] is True
    assert terminal["derived_from"] in {"run_events", "store_record"}
    if terminal["derived_from"] == "run_events":
        assert terminal["source_event_id"]

    # The resume response still has no run event plane of its own (unchanged shape).
    assert "events" not in resumed.body


def test_t3b_resume_and_cancel_lifecycle_streams_are_disjoint() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause(fixture)

    cancelled = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert cancelled.status_code == 200

    kinds = [event["kind"] for event in cancelled.body["continuation"]["lifecycle_events"]]
    assert kinds == ["cancel_requested", "cancelled"]
    assert "resumed" not in kinds
    assert "resume_requested" not in kinds


# --- T4 terminal state uniqueness ----------------------------------------


def test_t4_exactly_one_terminal_lifecycle_event_per_transition() -> None:
    expected = {
        "resume": "resumed",
        "cancel": "cancelled",
        "expired": "expiration_observed",
    }
    for transition, terminal_kind in expected.items():
        events = project_agent_lifecycle_events(
            continuation_id="cont_t4", transition=transition
        )
        terminals = [event for event in events if event["terminal"]]
        assert len(terminals) == 1, transition
        assert terminals[0]["kind"] == terminal_kind


# --- T5 backward compatibility -------------------------------------------


def test_t5_existing_response_contracts_are_unchanged() -> None:
    fixture = PausedRunFixture()

    pause = _run(fixture.service.run_payload(fixture.run_payload()))
    assert pause.status_code == 202
    assert set(pause.body) == {"ok", "agent_skill", "continuation_ref"}

    ref, pause_id = pause.body["continuation_ref"], pause.body["agent_skill"]["approval_pause"][
        "continuation_id"
    ]
    fixture.pre_confirmed = True
    resumed = _run(fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)))
    assert resumed.status_code == 200
    assert set(resumed.body) == {"ok", "agent_skill", "continuation"}
    assert set(resumed.body["continuation"]) == RESUME_BLOCK_KEYS
    assert resumed.body["continuation"]["continuation_contract_version"] == (
        "padiem.engine.agent-continuation/1.0"
    )
    assert resumed.body["continuation"]["lifecycle_contract_version"] == (
        ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION
    )

    other = PausedRunFixture()
    ref2, _ = _pause(other)
    cancelled = _run(other.service.cancel_payload(other.cancel_payload(ref2)))
    assert cancelled.status_code == 200
    assert set(cancelled.body) == {"ok", "status", "events", "continuation"}
    assert set(cancelled.body["continuation"]) == CANCEL_BLOCK_KEYS
    assert cancelled.body["status"] == "cancelled"

    invalid = _run(
        other.service.cancel_payload(
            {"app_id": APP_ID, "continuation_ref": ref2, "unexpected": 1}
        )
    )
    assert invalid.status_code == 400
    assert invalid.body["error"]["code"] == "invalid_request"
    assert "lifecycle_events" not in invalid.body
    assert "continuation" not in invalid.body


# --- T6 consumer isolation -----------------------------------------------


def test_t6_lifecycle_projection_exposes_no_authority_material() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause(fixture)

    cancelled = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert cancelled.status_code == 200

    events = cancelled.body["continuation"]["lifecycle_events"]
    assert events
    for event in events:
        assert set(event) == LIFECYCLE_EVENT_KEYS
        assert not (set(event) & FORBIDDEN_EVENT_KEYS)
        assert event["event_id"].startswith("lce_")
        assert event["continuation_id"] == ref


# --- T7 audit projection consistency ------------------------------------


def test_t7_audit_event_stays_a_summary_of_the_run_event_plane() -> None:
    fixture = PausedRunFixture()
    ref, _ = _pause(fixture)

    cancelled = _run(fixture.service.cancel_payload(fixture.cancel_payload(ref)))
    assert cancelled.status_code == 200

    block = cancelled.body["continuation"]
    # Phase 3 does not extend audit_event; it stays the Phase 1/2 summary.
    assert set(block["audit_event"]) == {"trace_id", "event_count", "terminal_kind"}
    assert block["audit_event"]["event_count"] == len(cancelled.body["events"])
    assert block["audit_event"]["terminal_kind"] == cancelled.body["events"][-1]["kind"]

    # The lifecycle plane is additive and does not rewrite the audit summary.
    assert len(block["lifecycle_events"]) == 2
    assert "lifecycle_events" not in block["audit_event"]


# --- T8 expired stays lazy ----------------------------------------------


def test_t8_expiry_is_projected_lazily_and_idempotently() -> None:
    first = project_agent_lifecycle_events(continuation_id="cont_t8", transition="expired")
    second = project_agent_lifecycle_events(continuation_id="cont_t8", transition="expired")

    assert [event["kind"] for event in first] == ["expiration_observed"]
    assert first[0]["terminal"] is True
    assert first[0]["derived_from"] == "read_observation"
    assert first[0]["timestamp_iso"] is None
    assert first[0]["source_event_id"] is None
    assert first == second


def test_t8b_expiry_is_observed_on_read_not_swept() -> None:
    fixture = PausedRunFixture()
    ref = fixture.store.issue(app_id=APP_ID, pause=_expired_pause(), plan_id=None)

    with pytest.raises(ServiceContractError) as observed:
        fixture.store.resolve(app_id=APP_ID, continuation_ref=ref)
    assert observed.value.code == "continuation_expired"
    assert observed.value.status_code == 409

    # Reading again observes the same expired state; nothing swept the record and
    # no second terminal state appeared.
    with pytest.raises(ServiceContractError) as reread:
        fixture.store.resolve(app_id=APP_ID, continuation_ref=ref)
    assert reread.value.code == "continuation_expired"


# --- projection contract guards -----------------------------------------


def test_projection_rejects_unknown_transitions_and_missing_identity() -> None:
    with pytest.raises(ValueError):
        project_agent_lifecycle_events(continuation_id="cont_x", transition="revive")
    with pytest.raises(TypeError):
        project_agent_lifecycle_events(continuation_id="", transition="cancel")
