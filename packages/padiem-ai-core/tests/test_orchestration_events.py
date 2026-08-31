import pytest
from padiem_ai_core.orchestration_events import (
    OrchestrationEvent,
    OrchestrationEventError,
    OrchestrationEventKind,
    public_orchestration_event,
)


def test_public_orchestration_event_creates_valid_instance() -> None:
    evt = public_orchestration_event(
        event_id="evt_123",
        run_id="run_456",
        trace_id="trace_789",
        app_id="b62",
        kind=OrchestrationEventKind.RUN_STARTED,
        sequence=1,
        message="Orchestration started",
        metadata={"step": 1, "status": "ok", "duration_ms": 12.5, "is_retry": False},
    )

    assert evt.event_id == "evt_123"
    assert evt.run_id == "run_456"
    assert evt.trace_id == "trace_789"
    assert evt.app_id == "b62"
    assert evt.kind == OrchestrationEventKind.RUN_STARTED
    assert evt.sequence == 1
    assert evt.message == "Orchestration started"
    assert evt.metadata["step"] == 1
    assert evt.metadata["duration_ms"] == 12.5
    assert evt.metadata["is_retry"] is False

    d = evt.to_public_dict()
    assert d["event_id"] == "evt_123"
    assert d["kind"] == "run_started"
    assert d["metadata"]["status"] == "ok"


def test_invalid_event_identifiers_fail_closed() -> None:
    with pytest.raises(OrchestrationEventError) as exc:
        public_orchestration_event(
            event_id="invalid/id!",
            run_id="run_1",
            trace_id="trace_1",
            app_id="b62",
            kind=OrchestrationEventKind.RUN_STARTED,
            sequence=1,
        )
    assert exc.value.code == "invalid_event_identifier"


def test_invalid_event_sequence_fails_closed() -> None:
    with pytest.raises(OrchestrationEventError) as exc:
        public_orchestration_event(
            event_id="evt_1",
            run_id="run_1",
            trace_id="trace_1",
            app_id="b62",
            kind=OrchestrationEventKind.RUN_STARTED,
            sequence=0,
        )
    assert exc.value.code == "invalid_event_sequence"


def test_non_scalar_metadata_is_strictly_rejected() -> None:
    with pytest.raises(OrchestrationEventError) as exc:
        public_orchestration_event(
            event_id="evt_1",
            run_id="run_1",
            trace_id="trace_1",
            app_id="b62",
            kind=OrchestrationEventKind.TOOL_COMPLETED,
            sequence=2,
            metadata={"nested_obj": {"raw": "data"}},
        )
    assert exc.value.code == "non_scalar_metadata_rejected"

    with pytest.raises(OrchestrationEventError) as exc2:
        public_orchestration_event(
            event_id="evt_1",
            run_id="run_1",
            trace_id="trace_1",
            app_id="b62",
            kind=OrchestrationEventKind.TOOL_COMPLETED,
            sequence=2,
            metadata={"nested_list": [1, 2, 3]},
        )
    assert exc2.value.code == "non_scalar_metadata_rejected"


def test_sensitive_metadata_keys_are_strictly_rejected() -> None:
    for bad_key in ("secret_key", "auth_token", "api_key", "password", "user_credential"):
        with pytest.raises(OrchestrationEventError) as exc:
            public_orchestration_event(
                event_id="evt_1",
                run_id="run_1",
                trace_id="trace_1",
                app_id="b62",
                kind=OrchestrationEventKind.RUN_STARTED,
                sequence=1,
                metadata={bad_key: "val"},
            )
        assert exc.value.code == "sensitive_metadata_key_rejected"
