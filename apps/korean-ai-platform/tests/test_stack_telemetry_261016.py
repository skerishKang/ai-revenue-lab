"""Service-independent, content-blind Grafana logs contract."""
import asyncio
from types import SimpleNamespace
import pytest

from app.stack_telemetry import (
    safe_id, start_trace, reset_trace, record_stage, make_events,
    active_request_id, _send,
)


def test_correlated_id_only_allows_safe_bounded_values():
    incoming = "req_trusted_123456789"
    assert safe_id(incoming) == incoming
    for bad in ("", "x", "Bearer secret", "bad\nheader", "x"*65):
        good = safe_id(bad)
        assert good.startswith("req_")
        assert good != bad


def test_trace_has_no_body_cookie_ip_or_provider():
    request = SimpleNamespace(
        headers={"x-request-id": "req_trace_12345678", "cookie": "secret"},
        method="POST", url="https://example.net/internal/v1/execute?token=hidden",
        body="private conversation",
    )
    state, token = start_trace(request, "padiem-ai-engine", "/internal/*")
    try:
        assert active_request_id() == "req_trace_12345678"
        record_stage("provider.call", False, 22.32, "timeout")
        events = make_events(state, 502)
        assert len(events) == 2
        assert events[0]["status"] == 502
        assert events[1]["code"] == "timeout"
        assert all("secret" not in str(event) for event in events)
        assert all("hidden" not in str(event) for event in events)
        assert all("private" not in str(event) for event in events)
        assert all("example.net" not in str(event) for event in events)
        assert events[0]["request_id"] == events[1]["request_id"]
    finally:
        reset_trace(token)
    assert active_request_id() is None


def test_successes_and_failures_have_denominators_without_static_traffic():
    r=SimpleNamespace(headers={},method="POST")
    state, token = start_trace(r,"korean-ai-platform","/api/pilot/*")
    try:
        ev=make_events(state,200)
        assert len(ev)==1 and ev[0]["outcome"]=="ok"
    finally:
        reset_trace(token)


def test_bad_stage_is_not_added_and_no_secret_disables_network():
    r=SimpleNamespace(headers={},method="POST")
    state, token = start_trace(r,"korean-ai-platform","/api/b66/*")
    try:
        record_stage("provider.called?secret", False, 20, "token leak")
        assert state["stages"] == []
        asyncio.run(_send(make_events(state,500), SimpleNamespace()))
    finally:
        reset_trace(token)


def test_browser_worker_fetch_emits_metadata_only(monkeypatch):
    import sys
    import types
    import json
    from app.stack_telemetry import _send
    captured = []

    async def fake_fetch(url, init):
        captured.append((url, init))
        return SimpleNamespace(status=204)

    mod_js = types.ModuleType("js")
    mod_js.Object = SimpleNamespace(fromEntries=lambda value: value)
    mod_js.fetch = fake_fetch
    mod_ffi = types.ModuleType("pyodide.ffi")
    mod_ffi.to_js = lambda value, **kwargs: value
    mod_pyodide = types.ModuleType("pyodide")
    mod_pyodide.ffi = mod_ffi
    monkeypatch.setitem(sys.modules, "js", mod_js)
    monkeypatch.setitem(sys.modules, "pyodide", mod_pyodide)
    monkeypatch.setitem(sys.modules, "pyodide.ffi", mod_ffi)

    request = SimpleNamespace(method="POST", headers={"x-request-id":"req_api_12345"})
    state, token = start_trace(request, "padiem-ai-engine", "/internal/*")
    try:
        record_stage("provider.call", False, 18.5, "timeout")
        events = make_events(state, 502)
        class PrivateToken:
            async def get(self):
                return "synthetic-test-token-not-real"
        asyncio.run(_send(events, SimpleNamespace(PADIEM_GRAFANA_OTLP_TOKEN=PrivateToken())))
    finally:
        reset_trace(token)
    assert len(captured) == 1
    url, init = captured[0]
    assert url.endswith("/otlp/v1/logs")
    assert init["method"] == "POST"
    body = init["body"]
    assert '"request_id' in body and 'req_api_12345' in body
    assert "synthetic-test-token-not-real" not in body
    assert "private conversation" not in body
    assert "provider.call" in body
    assert json.loads(body)["resourceLogs"][0]["resource"]["attributes"][0]["key"] == "service.name"


def test_successful_readonly_get_is_not_exported():
    r=SimpleNamespace(headers={},method="GET")
    state, token=start_trace(r,"korean-ai-platform","/api/pilot/*")
    try:
        assert make_events(state,200)==[]
        assert len(make_events(state,503))==1
    finally:
        reset_trace(token)
