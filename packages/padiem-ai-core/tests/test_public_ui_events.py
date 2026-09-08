from __future__ import annotations

from datetime import datetime, timezone

import pytest

from padiem_ai_core.public_ui_events import (
    MAX_PUBLIC_UI_EVENT_SEQUENCE,
    MAX_PUBLIC_UI_EVENT_SUMMARY_CHARS,
    PublicUiEvent,
    PublicUiEventError,
    PublicUiEventKind,
    PublicUiEventStream,
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


def test_event_kinds_are_exactly_the_nine_public_kinds():
    assert {kind.value for kind in PublicUiEventKind} == {
        "run_status_changed",
        "approval_required",
        "approval_resolved",
        "human_takeover_required",
        "human_takeover_resolved",
        "artifact_ready",
        "verified_diff_ready",
        "draft_pr_ready",
        "user_visible_error",
    }


def test_safe_dict_projection_is_bounded_and_public_safe():
    projection = event(subject_ref="subject-1", trace_id="trace-1").safe_dict()
    assert projection["contract_version"] == "padiem-public-ui-event.v1"
    assert projection["kind"] == "run_status_changed"
    assert projection["occurred_at"] == "2026-09-08T12:00:00Z"
    assert projection["event_fingerprint"]
    assert projection["hidden_reasoning"] is False
    assert projection["model_messages"] is False
    assert projection["tool_arguments"] is False
    assert projection["tool_results"] is False
    assert projection["raw_diff"] is False
    assert projection["raw_terminal_output"] is False
    assert projection["credential_values"] is False
    assert projection["execution_authority"] is False


def test_summary_must_be_bounded_non_empty_text_without_control_chars():
    with pytest.raises(PublicUiEventError):
        event(summary="   ")
    with pytest.raises(PublicUiEventError):
        event(summary="x" * (MAX_PUBLIC_UI_EVENT_SUMMARY_CHARS + 1))
    with pytest.raises(PublicUiEventError):
        event(summary="line\x00break")


def test_summary_carrying_credential_material_is_rejected():
    with pytest.raises(PublicUiEventError):
        event(summary="config api_key = supersecretvalue123")
    with pytest.raises(PublicUiEventError):
        event(summary="Authorization: Bearer abcd1234efgh5678")
    with pytest.raises(PublicUiEventError):
        event(summary="token sk-abcdefghijklmnop1234")
    with pytest.raises(PublicUiEventError):
        event(summary="pwd = hunter2hunter2")


def test_identifiers_and_sequence_are_bounded():
    with pytest.raises(PublicUiEventError):
        event(event_id="bad id!")
    with pytest.raises(PublicUiEventError):
        event(run_id="")
    with pytest.raises(PublicUiEventError):
        event(sequence=0)
    with pytest.raises(PublicUiEventError):
        event(sequence=MAX_PUBLIC_UI_EVENT_SEQUENCE + 1)
    with pytest.raises(PublicUiEventError):
        event(sequence=True)
    with pytest.raises(PublicUiEventError):
        event(occurred_at=datetime(2026, 9, 8, 12, 0, 0))


def test_kind_accepts_wire_value_but_rejects_unknown_kind():
    coerced = event(kind="artifact_ready")
    assert coerced.kind is PublicUiEventKind.ARTIFACT_READY
    with pytest.raises(PublicUiEventError):
        event(kind="hidden_reasoning")


def test_stream_enforces_contiguous_sequence_from_one():
    stream = PublicUiEventStream()
    stream.append(event())
    stream.append(event(event_id="evt-0002", sequence=2, summary="Run started"))
    with pytest.raises(PublicUiEventError):
        stream.append(event(event_id="evt-0003", sequence=4, summary="Skipped"))
    with pytest.raises(PublicUiEventError):
        stream.append(event(event_id="evt-0000", sequence=0, summary="Zero"))


def test_stream_replay_is_idempotent_for_identical_event():
    stream = PublicUiEventStream()
    first = event()
    stream.append(first)
    stream.append(first)
    assert len(stream.events("stream-1")) == 1


def test_stream_rejects_conflicting_event_id_replay():
    stream = PublicUiEventStream()
    stream.append(event())
    conflicting = event(summary="Different content entirely")
    with pytest.raises(PublicUiEventError):
        stream.append(conflicting)


def test_stream_rejects_mixed_run_identity():
    stream = PublicUiEventStream()
    stream.append(event())
    with pytest.raises(PublicUiEventError):
        stream.append(
            event(event_id="evt-0002", sequence=2, run_id="run-2", summary="Other run")
        )


def test_stream_enforces_monotonic_event_time():
    stream = PublicUiEventStream()
    stream.append(event())
    with pytest.raises(PublicUiEventError):
        stream.append(
            event(
                event_id="evt-0002",
                sequence=2,
                occurred_at=datetime(2026, 9, 8, 11, 59, 59, tzinfo=timezone.utc),
                summary="Time regression",
            )
        )
    same_time = event(event_id="evt-0002", sequence=2, occurred_at=T0, summary="Same instant")
    stream.append(same_time)
    assert len(stream.events("stream-1")) == 2


def test_safe_export_reports_no_external_authority():
    stream = PublicUiEventStream()
    stream.append(event())
    export = stream.safe_export("stream-1")
    assert export["contract_version"] == "padiem-public-ui-event-stream.v1"
    assert export["stream_id"] == "stream-1"
    assert len(export["events"]) == 1
    assert export["ag_ui_canonical_authority"] is False
    assert export["b62_execution_authority"] is False


def test_fingerprint_is_deterministic_and_content_sensitive():
    base = event()
    same = event()
    other = event(summary="Different summary")
    assert base.fingerprint == same.fingerprint
    assert base.fingerprint != other.fingerprint
    assert len(base.fingerprint) == 64


def test_non_utc_timezone_is_normalized_to_utc():
    from datetime import timedelta

    offset_tz = timezone(timedelta(hours=9))
    localized = event(occurred_at=datetime(2026, 9, 8, 21, 0, 0, tzinfo=offset_tz))
    assert localized.safe_dict()["occurred_at"] == "2026-09-08T12:00:00Z"
