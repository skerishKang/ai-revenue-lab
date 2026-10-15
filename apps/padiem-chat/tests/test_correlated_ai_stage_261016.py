"""B62 and B14 stage IDs link without PII or provider credentials."""
import json
import logging
import pytest
from starlette.testclient import TestClient

from app.request_telemetry import (
    build_stage_event, current_request_id, emit_stage_event,
    RequestTelemetryMiddleware,
)
from app.app_factory import create_app
from app.config import Settings


def test_stage_event_is_bounded_and_safe():
    item = build_stage_event(
        request_id="req_1234567890ab", stage="b14.complete",
        outcome="error", duration_ms=25.66, code="upstream_timeout",
        model="opencode-go/cat-jam-free", provider="example")
    assert item["request_id"] == "req_1234567890ab"
    assert item["code"] == "upstream_timeout"
    assert item["model"] == "opencode-go/cat-jam-free"
    assert "prompt" not in json.dumps(item)
    assert "cookie" not in json.dumps(item)


def test_untrusted_stage_labels_are_rejected_or_masked():
    with pytest.raises(ValueError):
        build_stage_event(request_id="req_safe_123456", stage="user\nsecret",
                          outcome="ok", duration_ms=1)
    out = build_stage_event(request_id="req_safe_123456",
                            stage="b14.complete", outcome="error", duration_ms=1,
                            code="Authorization: bearer SECRET", model="private request\ntext")
    assert out["code"] == "unknown" and out["model"] == "unknown"
    assert "SECRET" not in json.dumps(out)


def test_stage_emission_no_context_no_event(monkeypatch):
    received = []
    monkeypatch.setattr("app.request_telemetry.default_emitter",received.append)
    emit_stage_event(stage="b14.complete", outcome="ok", duration_ms=2)
    assert received == []


def test_context_is_per_request_and_restored(monkeypatch):
    received = []
    monkeypatch.setattr("app.request_telemetry.default_emitter",received.append)
    assert current_request_id() is None
    from starlette.responses import JSONResponse
    from starlette.applications import Starlette
    from starlette.routing import Route
    async def trace_for_test(request):
        emit_stage_event(stage="b14.complete", outcome="error", duration_ms=6, code="timeout")
        return JSONResponse({"seen":current_request_id()})
    app = RequestTelemetryMiddleware(Starlette(routes=[Route("/__trace_test",trace_for_test)]))
    with TestClient(app) as client:
        resp=client.get("/__trace_test",headers={"X-Request-Id":"req_trace_987654321"})
        assert resp.status_code==200
        assert resp.json()["seen"]=="req_trace_987654321"
        stage=[event for event in received if event.get("event")=="ai_stage"]
        assert len(stage)==1
        assert stage[0]["request_id"]==resp.headers["X-Request-Id"]
    assert current_request_id() is None
