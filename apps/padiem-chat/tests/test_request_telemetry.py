"""Network-free request telemetry regressions for Business 62 (#1975).

Scope note: this proves the *emitted evidence* contract — one bounded event per
request, a correlation id, an exact latency, and a route template instead of a
raw path. It deliberately does not assert counters or rates: on Cloudflare
Workers those are isolate-local and would be misleading, so aggregation is left
to the log pipeline (see docs/operations/B62_REQUEST_TELEMETRY_v1.md).
"""

from __future__ import annotations

import json
import logging

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.config import Settings
from app.request_telemetry import (
    OUTCOME_CLIENT_ERROR,
    OUTCOME_OK,
    OUTCOME_SERVER_ERROR,
    REQUEST_ID_HEADER,
    UNMATCHED_ROUTE,
    RequestTelemetryMiddleware,
    build_request_event,
    classify_outcome,
    default_emitter,
    is_safe_request_id,
    new_request_id,
    resolve_route_template,
)

ARTIFACT_ROUTE_TEMPLATE = "/api/claw/manual-intake/artifact/{document_id}"
EXPECTED_EVENT_KEYS = {
    "event",
    "service",
    "ts",
    "request_id",
    "request_id_source",
    "method",
    "route",
    "status",
    "duration_ms",
    "outcome",
}

# Material that must never reach the telemetry channel.
SECRET_TOKEN = "telemetry-never-see-this-token"
SECRET_COOKIE = "telemetry-never-see-this-cookie"
SECRET_DOCUMENT_ID = "doc_telemetry_secret_identifier"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="off",
    )


@pytest.fixture
def events() -> list[dict]:
    return []


@pytest.fixture
def client(events: list[dict]) -> TestClient:
    app = create_app(settings=_settings(), telemetry_emitter=events.append)
    return TestClient(app)


# --------------------------------------------------------------------------
# request id
# --------------------------------------------------------------------------


def test_response_carries_a_generated_request_id(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    request_id = response.headers.get(REQUEST_ID_HEADER)
    assert request_id
    assert is_safe_request_id(request_id)
    assert request_id.startswith("req_")


def test_safe_client_request_id_is_echoed_verbatim(client: TestClient, events: list[dict]):
    client_id = "client-correlation-0123456789"

    response = client.get("/health", headers={REQUEST_ID_HEADER: client_id})

    assert response.headers[REQUEST_ID_HEADER] == client_id
    assert events[-1]["request_id"] == client_id
    assert events[-1]["request_id_source"] == "client"


@pytest.mark.parametrize(
    "unsafe",
    [
        "short",  # below the minimum length
        "x" * 200,  # above the maximum length
        "bad\ninjected",  # newline injection
        "id with spaces",  # whitespace
        "id;rm -rf",  # shell metacharacter
    ],
)
def test_unsafe_client_request_id_is_discarded(client: TestClient, unsafe: str):
    response = client.get("/health", headers={REQUEST_ID_HEADER: unsafe})

    echoed = response.headers[REQUEST_ID_HEADER]
    assert echoed != unsafe
    assert is_safe_request_id(echoed)


def test_new_request_id_is_bounded_and_inert():
    for _ in range(5):
        value = new_request_id()
        assert is_safe_request_id(value)
        assert "\n" not in value


# --------------------------------------------------------------------------
# event shape
# --------------------------------------------------------------------------


def test_event_key_set_is_exactly_the_documented_projection(client: TestClient, events: list[dict]):
    client.get("/health")

    assert len(events) == 1
    assert set(events[0]) == EXPECTED_EVENT_KEYS
    assert events[0]["event"] == "http_request"
    assert events[0]["service"] == "padiem-chat"
    assert events[0]["method"] == "GET"
    assert events[0]["status"] == 200
    assert events[0]["outcome"] == OUTCOME_OK


def test_event_uses_route_template_not_raw_path(client: TestClient, events: list[dict]):
    client.get(f"/api/claw/manual-intake/artifact/{SECRET_DOCUMENT_ID}")

    assert events[-1]["route"] == ARTIFACT_ROUTE_TEMPLATE
    assert SECRET_DOCUMENT_ID not in json.dumps(events[-1])


def test_event_carries_no_request_material(client: TestClient, events: list[dict]):
    client.get(
        f"/api/claw/manual-intake/artifact/{SECRET_DOCUMENT_ID}?token={SECRET_TOKEN}",
        headers={
            "Cookie": f"session={SECRET_COOKIE}",
            "Authorization": f"Bearer {SECRET_TOKEN}",
            "X-Api-Key": SECRET_TOKEN,
        },
    )

    blob = json.dumps(events[-1]).lower()
    for needle in (SECRET_TOKEN.lower(), SECRET_COOKIE.lower(), SECRET_DOCUMENT_ID.lower()):
        assert needle not in blob, f"telemetry leaked request material: {needle}"
    assert "cookie" not in blob
    assert "authorization" not in blob
    assert "?" not in blob
    assert "query" not in blob


def test_unmatched_path_collapses_to_a_bounded_label(client: TestClient, events: list[dict]):
    client.get("/definitely-not-a-route?token=abc")

    assert events[-1]["route"] == UNMATCHED_ROUTE
    assert events[-1]["status"] == 404
    assert events[-1]["outcome"] == OUTCOME_CLIENT_ERROR


def test_duration_ms_is_a_non_negative_number(client: TestClient, events: list[dict]):
    client.get("/health")

    duration = events[-1]["duration_ms"]
    assert isinstance(duration, (int, float))
    assert duration >= 0


def test_response_request_id_matches_the_event_request_id(client: TestClient, events: list[dict]):
    response = client.get("/health")

    assert response.headers[REQUEST_ID_HEADER] == events[-1]["request_id"]


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, expected",
    [
        (200, OUTCOME_OK),
        (204, OUTCOME_OK),
        (304, OUTCOME_OK),
        (400, OUTCOME_CLIENT_ERROR),
        (404, OUTCOME_CLIENT_ERROR),
        (429, OUTCOME_CLIENT_ERROR),
        (500, OUTCOME_SERVER_ERROR),
        (503, OUTCOME_SERVER_ERROR),
    ],
)
def test_outcome_classification(status: int, expected: str):
    assert classify_outcome(status) == expected


def test_resolve_route_template_matches_declared_routes_only():
    app = create_app(settings=_settings())

    assert resolve_route_template(app, {"type": "http", "method": "POST", "path": "/api/chat"}) == "/api/chat"
    assert resolve_route_template(app, {"type": "http", "method": "GET", "path": "/health"}) == "/health"
    assert (
        resolve_route_template(
            app, {"type": "http", "method": "GET", "path": f"/api/claw/manual-intake/artifact/{SECRET_DOCUMENT_ID}"}
        )
        == ARTIFACT_ROUTE_TEMPLATE
    )
    # Static assets and unknown paths must not leak a raw path.
    assert resolve_route_template(app, {"type": "http", "method": "GET", "path": "/app.js"}) == UNMATCHED_ROUTE
    assert resolve_route_template(app, {"type": "http", "method": "GET", "path": "/nope"}) == UNMATCHED_ROUTE
    assert resolve_route_template(None, {"type": "http", "method": "GET", "path": "/health"}) == UNMATCHED_ROUTE


def test_build_request_event_is_json_serialisable_and_bounded():
    event = build_request_event(
        request_id="req_test",
        request_id_source="generated",
        method="GET",
        route="/health",
        status=200,
        duration_ms=1.5,
    )

    assert set(event) == EXPECTED_EVENT_KEYS
    assert json.loads(json.dumps(event))["route"] == "/health"
    assert event["ts"].endswith("Z")


# --------------------------------------------------------------------------
# default emitter
# --------------------------------------------------------------------------


def test_default_emitter_writes_a_single_line_of_json():
    logger = logging.getLogger("padiem_chat.request")
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _Capture()
    logger.addHandler(handler)
    try:
        app = create_app(settings=_settings())
        with TestClient(app) as plain_client:
            plain_client.get(
                f"/api/claw/manual-intake/artifact/{SECRET_DOCUMENT_ID}?token={SECRET_TOKEN}",
                headers={"Cookie": f"session={SECRET_COOKIE}"},
            )
    finally:
        logger.removeHandler(handler)

    assert captured, "default emitter produced no log record"
    line = captured[-1]
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["route"] == ARTIFACT_ROUTE_TEMPLATE
    blob = line.lower()
    assert SECRET_TOKEN.lower() not in blob
    assert SECRET_COOKIE.lower() not in blob
    assert SECRET_DOCUMENT_ID.lower() not in blob


def test_default_emitter_survives_a_request_without_declared_route():
    logger = logging.getLogger("padiem_chat.request")
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = _Capture()
    logger.addHandler(handler)
    try:
        app = create_app(settings=_settings())
        with TestClient(app) as plain_client:
            plain_client.get("/")
    finally:
        logger.removeHandler(handler)

    assert captured
    assert json.loads(captured[-1])["route"] == UNMATCHED_ROUTE


# --------------------------------------------------------------------------
# resilience
# --------------------------------------------------------------------------


def test_emitter_failure_never_breaks_the_request():
    def _exploding_emitter(event: dict) -> None:
        raise RuntimeError("telemetry sink unavailable")

    app = create_app(settings=_settings(), telemetry_emitter=_exploding_emitter)

    with TestClient(app) as failing_client:
        response = failing_client.get("/health")

    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER)


async def test_middleware_passes_non_http_scope_through():
    calls: list[str] = []

    async def _app(scope, receive, send):
        calls.append(scope["type"])

    async def _receive():
        return {}

    async def _send(message):
        return None

    middleware = RequestTelemetryMiddleware(_app)
    await middleware({"type": "websocket", "path": "/ws"}, _receive, _send)

    assert calls == ["websocket"]


def test_health_reports_request_telemetry_enabled(client: TestClient):
    body = client.get("/health").json()
    assert body["request_telemetry_enabled"] is True
