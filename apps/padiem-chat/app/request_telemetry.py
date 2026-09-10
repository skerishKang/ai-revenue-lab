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

import json
import logging
import re
import time
import uuid
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
        "status": status,
        "duration_ms": duration_ms,
        "outcome": classify_outcome(status),
    }


def default_emitter(event: dict[str, object]) -> None:
    """Write the event as one line of JSON on the Worker log channel."""
    _LOGGER.info(json.dumps(event, separators=(",", ":"), sort_keys=True))


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
    ) -> None:
        self.app = app
        self.service = service
        self.emitter = emitter or default_emitter

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
                self.emitter(
                    build_request_event(
                        request_id=request_id,
                        request_id_source=request_id_source,
                        service=self.service,
                        method=str(scope.get("method") or ""),
                        route=resolve_route_template(scope.get("app"), scope),
                        status=status,
                        duration_ms=elapsed_ms,
                    )
                )
            except Exception:
                # Telemetry must never turn a healthy request into a failure.
                pass


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
    "is_safe_request_id",
    "new_request_id",
    "resolve_route_template",
]
