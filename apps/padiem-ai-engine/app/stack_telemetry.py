"""Content-blind Worker request/stage exporter to the external Grafana Cloud Stack.

Identical narrow boundary in B14 and Engine: each Worker is independently
packaged, and no request content, tokens or customer IDs enter the payload.
"""
from __future__ import annotations

import asyncio
import base64
from contextvars import ContextVar
import json
import re
import time
import uuid

SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")
SAFE_STAGE = re.compile(r"^[a-z][a-z0-9_.-]{0,47}$")
OTLP_ENDPOINT = "https://otlp-gateway-prod-ap-northeast-0.grafana.net/otlp/v1/logs"
OTLP_USER = "1876517"
_CURRENT = ContextVar("padiem_worker_telemetry", default=None)


def safe_id(value: object) -> str:
    if isinstance(value, str) and SAFE_ID.fullmatch(value):
        return value
    return "req_" + uuid.uuid4().hex[:24]


def start_trace(request, service: str, route: str):
    headers = getattr(request, "headers", None)
    incoming = None
    try:
        if headers is not None:
            incoming = headers.get("x-request-id")
    except Exception:
        pass
    if route not in {"/api/pilot/*", "/api/b66/*", "/internal/*"}:
        route = "<unmatched>"
    if str(getattr(request, "method", "")).upper() not in ("GET", "POST"):
        method = "OTHER"
    else:
        method = str(request.method).upper()
    state = {
        "request_id": safe_id(incoming),
        "service": service,
        "route": route,
        "method": method,
        "start": time.perf_counter(),
        "stages": [],
    }
    return state, _CURRENT.set(state)


def reset_trace(token) -> None:
    _CURRENT.reset(token)


def active_request_id() -> str | None:
    state = _CURRENT.get()
    return state["request_id"] if isinstance(state, dict) else None


def record_stage(stage: str, success: bool, milliseconds: float, code: str = "none"):
    state = _CURRENT.get()
    if not isinstance(state, dict) or len(state["stages"]) >= 8:
        return
    if not SAFE_STAGE.fullmatch(stage):
        return
    # Code never comes from raw exceptions, provider strings, request text.
    if code not in {"none", "timeout", "rate_limit", "provider_error", "internal_error"}:
        code = "provider_error"
    state["stages"].append({
        "event": "ai_stage", "service": state["service"],
        "request_id": state["request_id"], "stage": stage,
        "outcome": "ok" if success else "error",
        "duration_ms": round(max(0, min(float(milliseconds), 3600000)), 2),
        "code": code,
    })


def make_events(state: dict, status: int) -> list[dict]:
    status = status if isinstance(status, int) and 100 <= status <= 599 else 500
    elapsed = round(max(0, min((time.perf_counter()-state["start"])*1000, 3600000)), 2)
    event = {
        "event": "http_request", "service": state["service"],
        "request_id": state["request_id"], "method": state["method"],
        "route": state["route"], "status": status,
        "outcome": "server_error" if status >= 500 else
                   "client_error" if status >= 400 else "ok",
        "duration_ms": elapsed,
    }
    stages = state["stages"]
    # Normal read-only GET polling is intentionally not exported. Capture all
    # POST executions so the error-rate denominator remains reliable, plus
    # failed GET (5xx), with a strict maximum 8 stage records.
    if state["method"] != "POST" and status < 500:
        return []
    return [event] + stages


async def _send(events: list[dict], env) -> None:
    """Only invoked via Worker waitUntil; failures never affect customers."""
    try:
        secret = getattr(env, "PADIEM_GRAFANA_OTLP_TOKEN", None)
        if secret is None:
            return
        if not isinstance(secret, str):
            get = getattr(secret, "get", None)
            if not callable(get):
                return
            secret = get()
            if hasattr(secret, "__await__"):
                secret = await secret
        if not isinstance(secret, str) or len(secret) < 20:
            return
        from js import Object, fetch
        from pyodide.ffi import to_js
        stamp = str(time.time_ns())
        records = [{
            "timeUnixNano": stamp,
            "severityText": "ERROR" if e["outcome"] in ("server_error", "error") else "INFO",
            "body": {"stringValue": json.dumps(e, sort_keys=True, separators=(",", ":"))},
        } for e in events]
        body = json.dumps({"resourceLogs": [{
            "resource": {"attributes": [
                {"key":"service.name", "value":{"stringValue":events[0]["service"]}},
                {"key":"deployment.environment", "value":{"stringValue":"production"}},
            ]}, "scopeLogs":[{"scope":{"name":"padiem.request.telemetry"},
                               "logRecords":records}]
        }]}, separators=(",", ":"))
        auth = base64.b64encode((OTLP_USER + ":" + secret).encode()).decode()
        init = to_js({"method":"POST",
                      "headers":{"Authorization":"Basic "+auth,
                                 "Content-Type":"application/json"},
                      "body":body}, dict_converter=Object.fromEntries,
                     create_pyproxies=False)
        response = await fetch(OTLP_ENDPOINT, init)
        # Avoid logging response text or headers.
        _ = int(response.status)
    except Exception:
        return


def finish_trace(state: dict, token, response, ctx, env) -> None:
    try:
        status = int(getattr(response, "status", 500)) if response is not None else 500
        events = make_events(state, status)
        if events and ctx is not None:
            from pyodide.ffi import create_proxy
            pending = _send(events, env)
            try:
                ctx.waitUntil(create_proxy(asyncio.wait_for(pending, timeout=1.0)))
            except Exception:
                pending.close()
    except Exception:
        pass
    finally:
        reset_trace(token)
