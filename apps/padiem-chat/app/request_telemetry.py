"""Bounded request telemetry for the Business 62 Worker (#1975).

Why this exists
---------------
Before #1975 the B62 Worker had a richly instrumented ``/health`` (binding and
readiness truth) but **zero per-request observability**: no request identifier,
no latency signal, no error-rate signal, and no structured log channel. Any
"monitoring" question ("is it slow?", "is it erroring?") was unanswerable
without attaching a debugger to a live isolate.

Why not Prometheus / Grafana
----------------------------
Cloudflare Workers execute in many short-lived isolates with no shared memory
and no scrape target. An in-process counter is therefore a *sample of one
isolate*, never a fleet-wide rate; a ``/metrics`` endpoint returning such
counters would look authoritative while being silently wrong. Standing up a
Prometheus server or a Grafana board would also require external provisioning
that this change is not allowed to perform.

The minimum-viable improvement that fits the current stack is therefore:

* emit **one structured event per request** (latency is measured locally and is
  exact; count and error-rate are derived downstream),
* leave aggregation, alerting and dashboards to the log pipeline that
  Cloudflare already provides (``wrangler tail`` / Workers Logs / Logpush),

and deliberately **not** introduce in-process counters or a scrape endpoint.

Evidence boundary
-----------------
An emitted event is bounded evidence. It may never contain request material:
no query string, no headers, no cookies, no body, no client address, no tenant
or user identifier. Path data is reduced to the matched **route template**, so
document ids / project ids / conversation ids never enter the log line. Client
supplied identifiers are accepted only when they match a conservative charset,
which also removes newline-injection into the log stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from collections.abc import Awaitable, Callable, MutableMapping
from datetime import datetime, timezone
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.routing import Match, Route

SERVICE_NAME = "padiem-chat"
REQUEST_ID_HEADER = "X-Request-Id"
EVENT_NAME = "http_request"

# Emitted for paths that do not match a declared API Route (static assets and
# unknown paths). A single bounded label keeps log cardinality flat.
UNMATCHED_ROUTE = "<unmatched>"

OUTCOME_OK = "ok"
OUTCOME_CLIENT_ERROR = "client_error"
OUTCOME_SERVER_ERROR = "server_error"

_REQUEST_ID_PREFIX = "req_"
_REQUEST_ID_BODY_LENGTH = 24
_REQUEST_ID_MIN_LENGTH = 8
_REQUEST_ID_MAX_LENGTH = 64
# Conservative charset: alphanumeric plus a small separator set. It excludes
# whitespace and control characters, so a client-supplied value can never break
# the single-line event shape.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")

LoggerEmitter = Callable[[dict[str, object]], None]

_LOGGER = logging.getLogger("padiem_chat.request")
_LOGGER.setLevel(logging.INFO)
# Keep the event stream off the root logger so this module never reconfigures
# logging for the rest of the Worker.
_LOGGER.propagate = False
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(_handler)


def new_request_id() -> str:
    return f"{_REQUEST_ID_PREFIX}{uuid.uuid4().hex[:_REQUEST_ID_BODY_LENGTH]}"


def is_safe_request_id(value: Any) -> bool:
    """Accept a client-supplied request id only when it is bounded and inert."""
    if not isinstance(value, str):
        return False
    if len(value) < _REQUEST_ID_MIN_LENGTH or len(value) > _REQUEST_ID_MAX_LENGTH:
        return False
    return bool(_REQUEST_ID_RE.fullmatch(value))


def classify_outcome(status_code: int) -> str:
    """Collapse a status code into the three outcomes an alert rule needs."""
    if status_code < 400:
        return OUTCOME_OK
    if status_code < 500:
        return OUTCOME_CLIENT_ERROR
    return OUTCOME_SERVER_ERROR


def resolve_route_template(app: Any, scope: MutableMapping[str, Any]) -> str:
    """Return the matched route template, never the raw request path.

    Only declared ``Route`` objects are considered. The catch-all static
    ``Mount`` is intentionally skipped so asset traffic and unknown paths both
    collapse to :data:`UNMATCHED_ROUTE` instead of leaking a raw path.
    """
    routes = getattr(app, "routes", None)
    if not routes:
        return UNMATCHED_ROUTE

    partial_template: str | None = None
    for route in routes:
        if not isinstance(route, Route):
            continue
        try:
            match, _ = route.matches(scope)
        except Exception:
            continue
        if match is Match.FULL:
            path = getattr(route, "path", None)
            return path if isinstance(path, str) and path else UNMATCHED_ROUTE
        if match is Match.PARTIAL and partial_template is None:
            path = getattr(route, "path", None)
            if isinstance(path, str) and path:
                partial_template = path
    return partial_template or UNMATCHED_ROUTE


def classify_product(route: str) -> str:
    # No user/tenant/model values, only fixed template prefix.
    if route.startswith("/api/claw"):
        return "claw"
    if route.startswith("/api/b66"):
        return "b66"
    if route.startswith("/api/chat"):
        return "chat"
    return "other"


def build_request_event(
    *,
    request_id: str,
    request_id_source: str,
    method: str,
    route: str,
    status: int,
    duration_ms: float,
    service: str = SERVICE_NAME,
    occurred_at: datetime | None = None,
) -> dict[str, object]:
    """Build the single bounded event emitted per request."""
    moment = occurred_at or datetime.now(timezone.utc)
    return {
        "event": EVENT_NAME,
        "service": service,
        "ts": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "request_id": request_id,
        "request_id_source": request_id_source,
        "method": method,
        "route": route,
        "product": classify_product(route),
        "status": status,
        "duration_ms": duration_ms,
        "outcome": classify_outcome(status),
    }


def default_emitter(event: dict[str, object]) -> None:
    """Write the event as one line of JSON on the Worker log channel."""
    _LOGGER.info(json.dumps(event, separators=(",", ":"), sort_keys=True))


# PADIEM_CORRELATED_STAGE_TELEMETRY_261016
# Never record request text, headers, auth, IP, customer IDs or paths.
# Context propagation lets Chat/Claw/B66 B14 stage events share the same
# opaque request id as the already-existing HTTP middleware event.
_CURRENT_REQUEST_ID: ContextVar[str | None] = ContextVar("padiem_trace_id", default=None)
_CURRENT_STAGE_EVENTS: ContextVar[list[dict[str, object]] | None] = ContextVar(
    "padiem_stage_events", default=None
)
# PADIEM_BACKGROUND_GRAFANA_SCHEDULER: set only for the active Worker invocation.
# Do not capture a first request's self.ctx in a process-wide ASGI singleton.
_CURRENT_EXPORT_SCHEDULER: ContextVar[Callable[[Awaitable[None]], None] | None] = (
    ContextVar("padiem_export_scheduler", default=None)
)


def install_export_scheduler(scheduler: Callable[[Awaitable[None]], None]):
    return _CURRENT_EXPORT_SCHEDULER.set(scheduler)


def reset_export_scheduler(token) -> None:
    _CURRENT_EXPORT_SCHEDULER.reset(token)
_SAFE_STAGE = re.compile(r"^[a-z][a-z0-9_.-]{0,47}$")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,119}$")


def current_request_id() -> str | None:
    return _CURRENT_REQUEST_ID.get()


def _safe_label(value: Any, *, fallback: str = "unknown") -> str:
    return value if isinstance(value, str) and _SAFE_VALUE.fullmatch(value) else fallback


def build_stage_event(
    *, request_id: str, stage: str, outcome: str, duration_ms: float,
    code: str | None = None, model: str | None = None,
    provider: str | None = None, b14_request_id: str | None = None,
) -> dict[str, object]:
    """Bounded diagnostic projection; never pass arbitrary exception messages."""
    if not is_safe_request_id(request_id):
        raise ValueError("UNSAFE_TRACE_ID")
    if not _SAFE_STAGE.fullmatch(stage):
        raise ValueError("UNSAFE_STAGE")
    if outcome not in ("ok", "error"):
        raise ValueError("UNSAFE_OUTCOME")
    return {
        "event": "ai_stage",
        "service": SERVICE_NAME,
        "request_id": request_id,
        "stage": stage,
        "outcome": outcome,
        "duration_ms": round(max(0.0, float(duration_ms)), 2),
        "code": _safe_label(code) if code else None,
        "model": _safe_label(model) if model else None,
        "provider": _safe_label(provider) if provider else None,
        "b14_request_id": _safe_label(b14_request_id) if b14_request_id else None,
    }


def emit_stage_event(*, stage: str, outcome: str, duration_ms: float,
                     code: str | None = None, model: str | None = None,
                     provider: str | None = None,
                     b14_request_id: str | None = None) -> None:
    """Emit when inside a traced HTTP request; never fail model execution."""
    request_id = current_request_id()
    if request_id is None:
        return
    try:
        event = build_stage_event(
            request_id=request_id, stage=stage, outcome=outcome,
            duration_ms=duration_ms, code=code, model=model,
            provider=provider, b14_request_id=b14_request_id,
        )
        pending = _CURRENT_STAGE_EVENTS.get()
        if pending is not None and len(pending) < 10:
            pending.append(event)
        # Before external ingestion is configured, retain ONLY failing stage
        # evidence on the existing log channel to minimize Cloudflare events.
        if outcome == "error":
            default_emitter(event)
    except Exception:
        pass


class RequestTelemetryMiddleware:
    """Emit one bounded structured event per HTTP request.

    Implemented as raw ASGI (not ``BaseHTTPMiddleware``) so streaming responses
    are untouched and the added latency is a single timer.
    """

    def __init__(
        self,
        app: Any,
        *,
        service: str = SERVICE_NAME,
        emitter: LoggerEmitter | None = None,
        exporter: Callable[[list[dict[str, object]]], Awaitable[None]] | None = None,
    ) -> None:
        self.app = app
        self.service = service
        self.emitter = emitter or default_emitter
        self.exporter = exporter

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = scope.get("headers") or ()
        incoming = _header_value(raw_headers, b"x-request-id")
        if is_safe_request_id(incoming):
            request_id = incoming
            request_id_source = "client"
        else:
            request_id = new_request_id()
            request_id_source = "generated"

        scope["request_id"] = request_id
        trace_context_token = _CURRENT_REQUEST_ID.set(request_id)
        stage_context_token = _CURRENT_STAGE_EVENTS.set([])

        status_holder: dict[str, int] = {}

        async def send_with_request_id(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status = message.get("status")
                if isinstance(status, int):
                    status_holder["status"] = status
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            # No response start means the request failed before any status was
            # written; treat it as a server error rather than dropping the event.
            status = status_holder.get("status", 500)
            try:
                # GRAFANA_NONBLOCKING_EVENT_EXPORT_261016:
                # export only bounded HTTP/stage data on AI routes, never static
                # traffic, queries, headers, request body or raw exceptions.
                http_event = build_request_event(
                    request_id=request_id,
                    request_id_source=request_id_source,
                    service=self.service,
                    method=str(scope.get("method") or ""),
                    route=resolve_route_template(scope.get("app"), scope),
                    status=status,
                    duration_ms=elapsed_ms,
                )
                self.emitter(http_event)
                if self.exporter is not None and (
                    http_event["route"].startswith(("/api/chat", "/api/claw", "/api/b66"))
                    or status >= 500
                ):
                    try:
                        stage_events = list(_CURRENT_STAGE_EVENTS.get() or [])
                        scheduler = _CURRENT_EXPORT_SCHEDULER.get()
                        if scheduler is not None:
                            # No remote I/O in the response's critical path.
                            # ctx.waitUntil owns this bounded background task.
                            async def _export() -> None:
                                try:
                                    await asyncio.wait_for(
                                        self.exporter([http_event] + stage_events),
                                        timeout=1.0,
                                    )
                                except Exception:
                                    pass

                            background = _export()
                            try:
                                scheduler(background)
                            except Exception:
                                background.close()
                    except Exception:
                        # Remote telemetry failure MUST NOT change the response.
                        pass
            except Exception:
                # Telemetry must never turn a healthy request into a failure.
                pass
            finally:
                _CURRENT_STAGE_EVENTS.reset(stage_context_token)
                _CURRENT_REQUEST_ID.reset(trace_context_token)


def _header_value(raw_headers: Any, name: bytes) -> str | None:
    try:
        for key, value in raw_headers:
            if key.lower() == name:
                return value.decode("latin-1")
    except Exception:
        return None
    return None


__all__ = [
    "EVENT_NAME",
    "OUTCOME_CLIENT_ERROR",
    "OUTCOME_OK",
    "OUTCOME_SERVER_ERROR",
    "REQUEST_ID_HEADER",
    "UNMATCHED_ROUTE",
    "RequestTelemetryMiddleware",
    "build_request_event",
    "classify_outcome",
    "default_emitter",
    "current_request_id",
    "install_export_scheduler",
    "reset_export_scheduler",
    "build_stage_event",
    "emit_stage_event",
    "is_safe_request_id",
    "new_request_id",
    "resolve_route_template",
]
