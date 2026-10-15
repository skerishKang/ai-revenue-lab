"""Focused tests: safe OTLP projection and fail-open nonblocking lifecycle."""
import asyncio
import json

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.grafana_otlp_exporter import safe_otlp_payload, validated_otlp_endpoint
from app.request_telemetry import (
    RequestTelemetryMiddleware, install_export_scheduler, reset_export_scheduler,
    emit_stage_event,
)


def test_otlp_allowlist_rejects_unbounded_data():
    row = {
        "event": "http_request", "service": "padiem-chat",
        "request_id": "req_safe_trace_1010", "status": 503,
        "outcome": "server_error", "route": "/api/chat",
    }
    payload = safe_otlp_payload([row])
    assert len(payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"]) == 1
    assert '"request_id":"req_safe_trace_1010"' in (
        payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"]["stringValue"]
    )
    for evil in (
        dict(row, prompt="customer secret prompt"),
        dict(row, route="/api/chat?Authorization=Bearer something"),
        dict(row, cookie={"session": "secret"}),
    ):
        with pytest.raises(ValueError):
            safe_otlp_payload([evil])
    with pytest.raises(ValueError):
        validated_otlp_endpoint("https://otlp-gateway-prod-ap-northeast-0.grafana.net.evil.com/otlp/v1/logs")
    assert validated_otlp_endpoint(
        "https://otlp-gateway-prod-ap-northeast-0.grafana.net/otlp/v1/logs"
    )


def test_background_export_does_not_delay_or_fail_http_request():
    dispatched = []
    delivered = []
    events = []

    async def endpoint(request):
        emit_stage_event(stage="b14.complete", outcome="ok", duration_ms=2.5)
        return JSONResponse({"ok": True})

    async def failed_remote_export(batch):
        delivered.append(batch)
        raise ConnectionError("simulated ingest outage")

    app = Starlette(routes=[Route("/api/chat", endpoint, methods=["POST"])])
    wrapper = RequestTelemetryMiddleware(
        app, exporter=failed_remote_export, emitter=events.append,
    )

    async def exercise():
        scope = {
            "type": "http", "http_version": "1.1", "method": "POST",
            "scheme": "https", "path": "/api/chat", "root_path": "",
            "query_string": b"", "headers": [], "app": app,
            "client": ("127.0.0.1", 1234), "server": ("testserver", 443),
        }
        messages = []
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            messages.append(message)
        token = install_export_scheduler(dispatched.append)
        try:
            await wrapper(scope, receive, send)
        finally:
            reset_export_scheduler(token)
        # HTTP response has already completed with no remote request awaited.
        assert messages[0]["status"] == 200
        assert len(dispatched) == 1
        assert delivered == []
        await dispatched[0]  # swallowed simulated remote exception
        assert len(delivered) == 1
        assert len(delivered[0]) == 2
        assert delivered[0][0]["request_id"] == delivered[0][1]["request_id"]
    asyncio.run(exercise())
    assert events[0]["outcome"] == "ok"


def test_missing_scheduler_never_reaches_external_network():
    export_calls = []
    async def unexpected_export(batch):
        export_calls.append(batch)
    async def endpoint(request):
        return JSONResponse({"ok": True})
    app = Starlette(routes=[Route("/api/chat", endpoint, methods=["POST"])])
    wrapper = RequestTelemetryMiddleware(app, exporter=unexpected_export, emitter=lambda e: None)
    async def exercise():
        scope = {"type":"http","http_version":"1.1","method":"POST","scheme":"https",
                 "path":"/api/chat","root_path":"","query_string":b"","headers":[],
                 "app":app,"client":("127.0.0.1",1),"server":("testserver",443)}
        async def receive():
            return {"type":"http.request","body":b"","more_body":False}
        async def send(message):
            return None
        await wrapper(scope,receive,send)
    asyncio.run(exercise())
    assert export_calls == []
