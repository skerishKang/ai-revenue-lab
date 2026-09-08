from __future__ import annotations

from datetime import datetime, timezone

import pytest

from padiem_ai_core import PublicUiEvent, PublicUiEventError, PublicUiEventKind, PublicUiEventStream

from app.public_event_projection import (
    PUBLIC_EVENT_PROJECTION_CONTRACT_VERSION,
    PUBLIC_EVENT_STREAM_PROJECTION_CONTRACT_VERSION,
    project_public_ui_event,
    project_public_ui_event_stream,
)

T0 = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


def event(**overrides) -> PublicUiEvent:
    values: dict = {
        "event_id": "evt-0001",
        "stream_id": "stream-1",
        "sequence": 1,
        "run_id": "run-1",
        "kind": PublicUiEventKind.RUN_STATUS_CHANGED,
        "occurred_at": T0,
        "summary": "Run queued",
    }
    values.update(overrides)
    return PublicUiEvent(**values)


def test_single_event_projection_reuses_core_serialization_verbatim():
    projected = project_public_ui_event(event(subject_ref="subject-1"))
    assert projected["contract_version"] == PUBLIC_EVENT_PROJECTION_CONTRACT_VERSION
    assert projected["kind"] == "run_status_changed"
    assert projected["hidden_reasoning"] is False
    assert projected["model_messages"] is False
    assert projected["tool_arguments"] is False
    assert projected["tool_results"] is False
    assert projected["raw_diff"] is False
    assert projected["raw_terminal_output"] is False
    assert projected["credential_values"] is False
    assert projected["execution_authority"] is False


def test_projection_fails_closed_on_non_core_values():
    with pytest.raises(PublicUiEventError):
        project_public_ui_event({"event_id": "evt-0001"})  # type: ignore[arg-type]
    with pytest.raises(PublicUiEventError):
        project_public_ui_event_stream({"events": []}, "stream-1")  # type: ignore[arg-type]


def test_stream_projection_preserves_core_order_and_membership():
    stream = PublicUiEventStream()
    stream.append(event())
    stream.append(event(event_id="evt-0002", sequence=2, kind=PublicUiEventKind.APPROVAL_REQUIRED, summary="Approval needed"))
    stream.append(event(event_id="evt-0003", sequence=3, kind=PublicUiEventKind.APPROVAL_RESOLVED, summary="Approval granted"))
    export = project_public_ui_event_stream(stream, "stream-1")
    assert export["contract_version"] == PUBLIC_EVENT_STREAM_PROJECTION_CONTRACT_VERSION
    assert [item["event_id"] for item in export["events"]] == ["evt-0001", "evt-0002", "evt-0003"]
    assert [item["sequence"] for item in export["events"]] == [1, 2, 3]
    assert export["ag_ui_canonical_authority"] is False
    assert export["b62_execution_authority"] is False
    assert export["engine_transport_projection"] is True
    assert export["grants_execution_authority"] is False


def test_stream_projection_never_fabricates_or_reorders_events():
    stream = PublicUiEventStream()
    assert project_public_ui_event_stream(stream, "stream-1")["events"] == []
    stream.append(event())
    with pytest.raises(PublicUiEventError):
        stream.append(event(event_id="evt-0002", sequence=3, summary="Gap"))
    export = project_public_ui_event_stream(stream, "stream-1")
    assert [item["sequence"] for item in export["events"]] == [1]


def test_projection_adds_no_credential_or_endpoint_fields():
    export = project_public_ui_event_stream(PublicUiEventStream(), "stream-1")
    text = repr(export)
    for forbidden in ("api_key", "token", "endpoint", "account", "credential"):
        assert forbidden not in text
