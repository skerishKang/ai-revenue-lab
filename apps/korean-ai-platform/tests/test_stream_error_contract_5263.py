"""#5263: one public streaming error authority for both Business 14 SSE gates.

The manual ``stream-preview`` surface and the staged ``auto-stream-preview``
surface answer the same provider condition.  They must publish the same public
status and the same public message, and neither may publish provider-specific
or upstream detail (an upstream HTTP status, a byte budget, a provider quota
text) in a public body.
"""
from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.errors import (
    InvalidRequest,
    KiloFreeRateLimited,
    MalformedUpstreamResponse,
    NoSafeRoute,
    PilotNotConfigured,
    UpstreamAuthFailed,
    UpstreamBusyRateLimited,
    UpstreamClientError,
    UpstreamRateLimited,
    UpstreamResponseTooLarge,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.stream_error_contract import (
    STREAM_ERROR_DETAILS,
    pilot_error_from_code,
    public_stream_error,
    safe_stream_error_details,
)


STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"
MODEL = "test-fixture/kilo-stream-gateway"
MODEL_UPSTREAM = "test-fixture/kilo-stream-response"
LIVE_DUMMY_KEY = "unit-live-key-abcdef1234567890"

# Every provider/stream failure the platform can raise, with the status the
# raiser owns.  The shared table must agree with the raiser, otherwise the two
# authorities for one condition drift apart.
RAISER_CASES = (
    (UpstreamAuthFailed(), 401),
    (UpstreamRateLimited(), 429),
    (UpstreamBusyRateLimited(), 429),
    (KiloFreeRateLimited(), 429),
    (UpstreamTimeout(), 504),
    (UpstreamServerError(), 502),
    (UpstreamClientError(404), 502),
    (MalformedUpstreamResponse(), 502),
    (UpstreamResponseTooLarge(), 502),
    (PilotNotConfigured(), 503),
    (NoSafeRoute(), 503),
)

# Upstream-specific detail that must never reach a public body.
UPSTREAM_DETAIL_MARKERS = (
    "upstream HTTP",
    "bytes)",
    "req/hour",
    "Kilo Gateway",
    "Please retry later",
)


@pytest.fixture(autouse=True)
def _synthetic_catalog_stream_route(monkeypatch):
    """Isolated synthetic keyless fixture; never restore owner-deleted IDs."""
    from dataclasses import replace
    import app.pilot.catalog as cat
    from app.pilot import platform_secrets as ps
    base = next(iter(cat.CATALOG_BY_ID.values()))
    fixture = replace(
        base, model_id=MODEL, upstream_model=MODEL_UPSTREAM,
        display_name="Synthetic SSE test-only model",
        provider="Fixture Test Provider", platform_provider_id="test-fixture",
        capabilities=frozenset({"chat", "free"}),
        input_price_usd_per_1m=0.0, output_price_usd_per_1m=0.0,
    )
    spec = ps.PlatformProviderSpec(
        provider_id="test-fixture", credential_source=ps.CredentialSource.NONE,
        credential_binding_name="", base_origin="https://stream-fixture.example/v1",
        allowed_hosts=("stream-fixture.example",),
    )
    monkeypatch.setitem(cat.CATALOG_BY_ID, MODEL, fixture)
    monkeypatch.setitem(ps._PLATFORM_PROVIDERS, "test-fixture", spec)
    yield


@pytest.fixture(autouse=True)
def _reset_runtime_config(monkeypatch):
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved = {"provider_mode": rcfg.provider_mode, "max_response_bytes": rcfg.max_response_bytes}
    rcfg.provider_mode = "mock"
    rcfg.max_response_bytes = 1024 * 1024
    yield
    rcfg.provider_mode = saved["provider_mode"]
    rcfg.max_response_bytes = saved["max_response_bytes"]


def _payload(**overrides):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "안녕하세요"}],
        "stream": True,
    }
    payload.update(overrides)
    return payload


def _client(transport: httpx.AsyncBaseTransport | None = None) -> TestClient:
    app = create_app()
    if transport is not None:
        app.state.stream_transport = transport
    return TestClient(app)


@pytest.mark.parametrize(("exc", "expected_status"), RAISER_CASES)
def test_shared_table_status_agrees_with_the_raiser(exc, expected_status):
    """The table and the raiser must never disagree about one condition."""
    assert exc.status_code == expected_status
    details = STREAM_ERROR_DETAILS.get(exc.code)
    assert details is not None, exc.code
    assert details[0] == expected_status, exc.code


@pytest.mark.parametrize(("exc", "expected_status"), RAISER_CASES)
def test_public_message_drops_upstream_detail(exc, expected_status):
    """A public body must not repeat the upstream status or provider text."""
    code, status_code, message = public_stream_error(exc)
    assert code == exc.code
    assert status_code == expected_status
    assert message == STREAM_ERROR_DETAILS[exc.code][1]
    for marker in UPSTREAM_DETAIL_MARKERS:
        assert marker not in message, (exc.code, marker)


@pytest.mark.parametrize(("exc", "expected_status"), RAISER_CASES)
def test_both_sse_surfaces_publish_the_same_public_error(exc, expected_status):
    """The manual and the auto SSE gate answer one condition identically."""
    from app.pilot import auto_stream_gateway, stream_gateway

    request_id = "b14req_shared"
    manual = stream_gateway._error_response(exc, request_id)
    auto = auto_stream_gateway._error_response(exc, request_id)

    assert manual.status_code == auto.status_code == expected_status
    assert manual.body == auto.body
    assert b'"code":"' + exc.code.encode() + b'"' in manual.body
    for marker in UPSTREAM_DETAIL_MARKERS:
        assert marker.encode() not in manual.body, (exc.code, marker)


def test_caller_error_keeps_its_own_status_and_message():
    """A request error is not a provider failure and keeps its own contract."""
    exc = InvalidRequest("model must be a catalog id")
    code, status_code, message = public_stream_error(exc)
    assert code == "invalid_request"
    assert status_code == 400
    assert message == "model must be a catalog id"


def test_unknown_provider_code_publishes_a_bounded_generic_message():
    """An unknown provider code must not fall through to the raw detail."""
    status_code, message = safe_stream_error_details("some_unseen_provider_code")
    assert status_code == 502
    assert "some_unseen_provider_code" not in message
    assert "418" not in message


def test_router_reported_code_uses_the_shared_status_and_message():
    """A router-reported code has no raiser, so the table owns both values."""
    status_code, message = safe_stream_error_details("upstream_rate_limited")
    assert status_code == 429
    exc = pilot_error_from_code("upstream_rate_limited")
    assert exc.code == "upstream_rate_limited"
    assert exc.status_code == 429
    assert exc.message == message


def test_manual_surface_publishes_the_shared_message_not_the_upstream_detail():
    """The manual SSE gate must answer a provider failure with the shared body."""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, content=b"bounded error")

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()["error"]
    assert body["code"] == "upstream_client_error"
    assert body["message"] == STREAM_ERROR_DETAILS["upstream_client_error"][1]
    assert "422" not in body["message"]
    assert "upstream HTTP" not in body["message"]
