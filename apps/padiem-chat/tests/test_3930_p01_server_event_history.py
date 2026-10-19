"""#3930: real verified post-execution P01 history crosses server SSE, never fake live phases."""
from __future__ import annotations

import json

from app.claw_general_routes import _claw_general_sse
from test_b54_claw_general_p01_routing import _client, _make_adapter, _make_outcome, _payload


def _history():
    events = []
    for seq, kind in enumerate(("run_started", "tool_started", "run_completed"), start=1):
        events.append({
            "event_id": f"evt_{seq}", "run_id": "run_true_1",
            "trace_id": "trace_true_1", "app_id": "claw",
            "kind": kind, "sequence": seq,
            "timestamp_iso": "2026-10-09T14:00:00+00:00",
            "message": "fake secret should never leave server",
            "metadata": {"api_key": "do-not-expose"},
        })
    return tuple(events)


def test_route_sse_delivers_only_canonical_event_identity_and_no_raw_content():
    outcome = _make_outcome()
    outcome.p01_event_history = _history()
    with _client(_make_adapter(outcome=outcome)) as client:
        response = client.post("/api/claw/general", json=_payload())
    assert response.status_code == 200
    assert response.text.count("event: p01_event") == 3
    assert response.text.index("event: p01_event") < response.text.index("event: delta")
    assert response.text.count("event: done") == 1
    assert "fake secret" not in response.text
    assert "api_key" not in response.text
    assert "do-not-expose" not in response.text
    assert '"delivery":"post_execution"' in response.text
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert [p["kind"] for p in payloads[:3]] == ["run_started", "tool_started", "run_completed"]
    assert all(set(p) == {
        "event_id", "run_id", "trace_id", "app_id", "kind",
        "sequence", "timestamp_iso", "delivery",
    } for p in payloads[:3])


def test_legacy_no_events_never_fabricates_stages():
    response = _claw_general_sse("검증 답변")
    assert response.body.count(b"event: done") == 1
    assert b"event: p01_event" not in response.body
    assert b"event: delta" in response.body


def test_bounded_invalid_history_fails_closed_without_poisoning_answer():
    for history in (({"kind": "tool_started"},), tuple(_history()[0] for _ in range(129))):
        response = _claw_general_sse("확정", history=history)
        assert b"event: p01_event" not in response.body
        assert response.body.count(b"event: done") == 1
        assert b"event: delta" in response.body


def test_engine_failure_502_emits_no_false_execution_history():
    outcome = _make_outcome(status="failed", answer=None)
    outcome.p01_event_history = _history()
    with _client(_make_adapter(outcome=outcome)) as client:
        response = client.post("/api/claw/general", json=_payload())
    assert response.status_code == 502
    assert "event: p01_event" not in response.text
