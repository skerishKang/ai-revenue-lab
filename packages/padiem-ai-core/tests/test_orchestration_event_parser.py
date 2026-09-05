from __future__ import annotations

import pytest

from padiem_ai_core.orchestration_events import (
    OrchestrationEventError,
    OrchestrationEventKind,
    orchestration_event_from_public,
    public_orchestration_event,
)


def _payload() -> dict[str, object]:
    event = public_orchestration_event(
        event_id="evt_001",
        run_id="run_001",
        trace_id="trace_001",
        app_id="b54-padiem-claw",
        kind=OrchestrationEventKind.APPROVAL_PAUSED,
        sequence=4,
        message="approval required",
        metadata={"decision_id": "dec_001", "attempt": 1},
        timestamp_iso="2026-09-05T00:00:00+00:00",
    )
    return event.to_public_dict()


def test_public_event_round_trips_through_the_parser() -> None:
    event = orchestration_event_from_public(_payload())

    assert event.event_id == "evt_001"
    assert event.run_id == "run_001"
    assert event.trace_id == "trace_001"
    assert event.app_id == "b54-padiem-claw"
    assert event.kind is OrchestrationEventKind.APPROVAL_PAUSED
    assert event.sequence == 4
    assert event.message == "approval required"
    assert dict(event.metadata) == {"decision_id": "dec_001", "attempt": 1}


def test_round_trip_preserves_every_kind() -> None:
    for kind in OrchestrationEventKind:
        event = public_orchestration_event(
            event_id="evt_kind",
            run_id="run_kind",
            trace_id="trace_kind",
            app_id="b54-padiem-claw",
            kind=kind,
            sequence=1,
        )
        assert orchestration_event_from_public(event.to_public_dict()).kind is kind


def test_unknown_field_is_rejected_not_skipped() -> None:
    payload = _payload()
    payload["approval_state"] = {"paused": True}

    with pytest.raises(OrchestrationEventError) as caught:
        orchestration_event_from_public(payload)
    assert caught.value.code == "unsupported_event_field"


def test_unknown_kind_is_rejected_not_skipped() -> None:
    payload = _payload()
    payload["kind"] = "teleport_finished"

    with pytest.raises(OrchestrationEventError) as caught:
        orchestration_event_from_public(payload)
    assert caught.value.code == "unsupported_event_kind"


def test_non_mapping_payload_is_rejected() -> None:
    with pytest.raises(OrchestrationEventError) as caught:
        orchestration_event_from_public(["not", "a", "mapping"])  # type: ignore[arg-type]
    assert caught.value.code == "invalid_event_payload"


def test_non_positive_sequence_is_rejected() -> None:
    payload = _payload()
    payload["sequence"] = 0

    with pytest.raises(OrchestrationEventError):
        orchestration_event_from_public(payload)


def test_non_scalar_metadata_value_is_rejected() -> None:
    payload = _payload()
    payload["metadata"] = {"decision_id": {"nested": "object"}}

    with pytest.raises(OrchestrationEventError) as caught:
        orchestration_event_from_public(payload)
    assert caught.value.code == "invalid_event_metadata"


def test_null_metadata_value_and_null_message_are_allowed() -> None:
    payload = _payload()
    payload["metadata"] = {"decision_id": None}
    payload["message"] = None

    event = orchestration_event_from_public(payload)

    assert event.message is None
    assert dict(event.metadata) == {"decision_id": None}


def test_parser_does_not_accept_partial_identity() -> None:
    payload = _payload()
    del payload["run_id"]

    with pytest.raises(OrchestrationEventError):
        orchestration_event_from_public(payload)
