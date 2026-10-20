"""#5224 — B14 platform-credential dispatch authorization.

The B14 Worker is published on the public ``workers.dev`` subdomain, so every
mounted route is anonymously reachable. These tests pin the external boundary
that keeps an anonymous public request away from the platform-owned provider
credential:

* a public Cloudflare edge request is rejected with ``401`` before any
  provider dispatch, so the provider POST count stays at zero;
* the internal Service Binding callers keep dispatching;
* the BYOK branch keeps spending the caller's own key;
* the read-only verification surfaces keep answering and never dispatch.

No real provider call is made: the platform dispatch functions are replaced
with local counters.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform as plat
from app.pilot import provider as prv
from app.pilot import auto_stream_gateway as auto_stream
from app.pilot import stream_gateway as stream_gw
from app.pilot.dispatch_authorization import (
    INTERNAL_ORIGIN_HOST,
    authorize_platform_dispatch,
)

PUBLIC_B14_ORIGIN = "https://ai-revenue-korean-ai-platform.charliekant.workers.dev"

# The Cloudflare public edge always adds these client headers to a request
# that arrived from the internet. A Worker-to-Worker subrequest never carries
# them.
EDGE_HEADERS = {
    "cf-connecting-ip": "203.0.113.10",
    "cf-ray": "8f1c0f2b3a4d5e6f",
}

CATALOG_MODEL = "agnes-ai/agnes-3.0-flash"
BYOK_MODEL = "test-model-v1"
AGNES_CREDENTIAL_BINDING = "PADIEM_B14_CREDENTIAL_01"
SYNTHETIC_KEY = "synthetic-b14-credential-0123456789abcdef"

_PLATFORM_ANSWER = {
    "id": "b14req-test",
    "object": "chat.completion",
    "model": "agnes-3.0-flash",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _edge_request(client: TestClient, method: str, path: str, **kwargs):
    """Issue one request that looks like it arrived through the public edge."""
    headers = dict(EDGE_HEADERS)
    headers.update(kwargs.pop("headers", {}) or {})
    return client.request(method, path, headers=headers, **kwargs)


@pytest.fixture()
def dispatch_counter(monkeypatch):
    """Replace every platform dispatch with a local counter.

    The counter proves the real provider HTTP call is never reached.
    """
    calls: dict[str, int] = {"platform": 0, "stream": 0, "auto_stream": 0, "byok": 0}

    async def fake_platform(**_kwargs):
        calls["platform"] += 1
        return dict(_PLATFORM_ANSWER)

    async def fake_byok(**_kwargs):
        calls["byok"] += 1
        return dict(_PLATFORM_ANSWER)

    def fake_stream(**_kwargs):
        calls["stream"] += 1
        raise AssertionError("streaming provider dispatch must not be reached")

    def fake_auto_stream(**_kwargs):
        calls["auto_stream"] += 1
        raise AssertionError("auto streaming provider dispatch must not be reached")

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake_platform)
    monkeypatch.setattr(prv, "call_chat_completions", fake_byok)
    monkeypatch.setattr(stream_gw, "stream_platform_chat_completions", fake_stream)
    monkeypatch.setattr(auto_stream, "stream_platform_chat_completions", fake_auto_stream)
    return calls


@pytest.fixture()
def platform_credential(monkeypatch):
    """Present one platform-owned credential so the route would really dispatch."""
    monkeypatch.setenv(AGNES_CREDENTIAL_BINDING, SYNTHETIC_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")


@pytest.fixture()
def byok_pilot(monkeypatch):
    """Configure the legacy BYOK route so the BYOK branch stays reachable."""
    from app.pilot.config import pilot_settings

    monkeypatch.setattr(pilot_settings, "provider_registry_json", "")
    monkeypatch.setattr(pilot_settings, "pilot_base_url", "https://api.test-pilot.example.com")
    monkeypatch.setattr(pilot_settings, "pilot_model_id", BYOK_MODEL)
    monkeypatch.setattr(pilot_settings, "pilot_provider_id", "test-provider")
    monkeypatch.setattr(pilot_settings, "pilot_upstream_model", "upstream-model-v1")
    monkeypatch.setattr(pilot_settings, "pilot_timeout_seconds", 10)
    yield


# ---------------------------------------------------------------------------
# Unit contract of the authorization decision
# ---------------------------------------------------------------------------
class TestAuthorizationDecision:
    def test_public_edge_request_is_denied(self):
        class _Request:
            url = f"{PUBLIC_B14_ORIGIN}/api/pilot/v1/chat/completions"
            headers = dict(EDGE_HEADERS)

        decision = authorize_platform_dispatch(_Request())
        assert decision.allowed is False
        assert decision.status_code == 401
        assert decision.reason == "unauthorized_public_ingress"

    def test_internal_origin_request_is_allowed(self):
        class _Request:
            url = f"https://{INTERNAL_ORIGIN_HOST}/api/pilot/v1/chat/completions"
            headers: dict[str, str] = {}

        decision = authorize_platform_dispatch(_Request())
        assert decision.allowed is True
        assert decision.reason == "service_binding_internal_origin"

    def test_worker_subrequest_without_edge_headers_is_allowed(self):
        class _Request:
            url = f"{PUBLIC_B14_ORIGIN}/api/pilot/v1/chat/completions"
            headers = {"content-type": "application/json"}

        decision = authorize_platform_dispatch(_Request())
        assert decision.allowed is True
        assert decision.reason == "service_binding_worker_subrequest"

    def test_unreadable_request_shape_fails_closed(self):
        class _Request:
            url = None
            headers = None

        decision = authorize_platform_dispatch(_Request())
        assert decision.allowed is False
        assert decision.status_code == 401


# ---------------------------------------------------------------------------
# Public edge: every real provider-dispatch entry point is denied
# ---------------------------------------------------------------------------
class TestPublicEdgeIsDeniedBeforeProviderDispatch:
    def test_chat_completions_is_denied_and_dispatches_nothing(
        self, client, dispatch_counter, platform_credential,
    ):
        resp = _edge_request(
            client,
            "POST",
            "/api/pilot/v1/chat/completions",
            json={"model": CATALOG_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized_platform_dispatch"
        assert dispatch_counter == {
            "platform": 0, "stream": 0, "auto_stream": 0, "byok": 0,
        }

    def test_stream_preview_is_denied_and_dispatches_nothing(
        self, client, dispatch_counter, platform_credential,
    ):
        resp = _edge_request(
            client,
            "POST",
            "/api/pilot/v1/chat/completions/stream-preview",
            json={"model": CATALOG_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized_platform_dispatch"
        assert dispatch_counter["stream"] == 0
        assert dispatch_counter["platform"] == 0

    def test_auto_stream_preview_is_denied_and_dispatches_nothing(
        self, client, dispatch_counter, platform_credential,
    ):
        resp = _edge_request(
            client,
            "POST",
            "/api/pilot/v1/chat/completions/auto-stream-preview",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized_platform_dispatch"
        assert dispatch_counter["auto_stream"] == 0
        assert dispatch_counter["stream"] == 0

    def test_b66_extraction_is_denied_and_dispatches_nothing(
        self, client, dispatch_counter, platform_credential,
    ):
        resp = _edge_request(
            client,
            "POST",
            "/api/b66/v1/quote/extract-image",
            json={
                "name": "quote.png",
                "media_type": "image/png",
                "base64": "iVBORw0KGgo=",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized_platform_dispatch"
        assert dispatch_counter["platform"] == 0


# ---------------------------------------------------------------------------
# The internal Service Binding path keeps working
# ---------------------------------------------------------------------------
class TestInternalServiceBindingKeepsDispatching:
    def test_chat_completions_dispatches_on_the_internal_origin(
        self, dispatch_counter, platform_credential,
    ):
        with TestClient(create_app(), base_url=f"https://{INTERNAL_ORIGIN_HOST}") as client:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": CATALOG_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            )
        assert resp.status_code == 200
        assert dispatch_counter["platform"] == 1

    def test_chat_completions_dispatches_for_a_worker_subrequest(
        self, client, dispatch_counter, platform_credential,
    ):
        # A Worker-to-Worker subrequest carries no Cloudflare edge client
        # headers, exactly like the B62 Chat / B54 Engine Service Binding call.
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": CATALOG_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        assert dispatch_counter["platform"] == 1


# ---------------------------------------------------------------------------
# The BYOK branch and the read-only verification surfaces are unchanged
# ---------------------------------------------------------------------------
class TestUnchangedContracts:
    def test_byok_branch_still_uses_the_caller_key(
        self, client, dispatch_counter, byok_pilot,
    ):
        resp = _edge_request(
            client,
            "POST",
            "/api/pilot/v1/chat/completions",
            json={"model": BYOK_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 200
        assert dispatch_counter["byok"] == 1
        assert dispatch_counter["platform"] == 0

    def test_read_only_verification_surfaces_are_not_blocked(
        self, client, dispatch_counter, platform_credential,
    ):
        assert _edge_request(client, "GET", "/api/pilot/health").status_code == 200
        assert _edge_request(client, "GET", "/api/pilot/models").status_code == 200
        resolve = _edge_request(
            client,
            "POST",
            "/api/pilot/router/resolve",
            json={"model": CATALOG_MODEL, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resolve.status_code == 200
        assert resolve.json()["credential_status"] == "key_available"
        assert dispatch_counter == {
            "platform": 0, "stream": 0, "auto_stream": 0, "byok": 0,
        }
