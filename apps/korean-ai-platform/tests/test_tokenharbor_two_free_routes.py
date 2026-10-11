"""TokenHarbor: exactly two owner-approved free routes, no real upstream calls.

The universal key may access paid models, so the final platform adapter
checks its own fixed free-model allowlist independently of routing metadata.
"""
from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform
from app.pilot.errors import NoSafeRoute, PilotNotConfigured, UpstreamRateLimited
from app.pilot.model_registry_file import read_registry
from app.pilot.platform import call_platform_chat_completions, stream_platform_chat_completions
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.router_core import resolve_manual_route

PROVIDER = "tokenharbor"
BINDING = "PADIEM_TOKEN_HARBOR_API_KEY"
ORIGIN = "https://tokenharbor.ai/v1"
ALLOWED = {
    "tokenharbor/claude-haiku-5.5:free": "claude-haiku-5.5:free",
    "tokenharbor/deepseek-v4.1-flash:free": "deepseek-v4.1-flash:free",
}
SYNTHETIC = "synthetic_tokenharbor_key_no_actual_account"


@pytest.fixture
def live_key(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, SYNTHETIC)


def _completed(*, model):
    return {
        "id": "synthetic-completion",
        "model": model,
        "choices": [
            {"message": {"role": "assistant", "content": "ready"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_canonical_registration_exactly_two_free_routes():
    registry = read_registry()
    provider = registry["providers"][PROVIDER]
    assert provider == {
        "base_origin": ORIGIN,
        "allowed_hosts": ["tokenharbor.ai"],
        "credential_source": "platform_secret",
        "credential_binding_name": BINDING,
        "enabled": True,
    }
    listed = {m["id"]: m for m in registry["models"] if m["provider_id"] == PROVIDER}
    assert set(listed) == set(ALLOWED)
    assert not any("mimo" in m or not m.endswith(":free") for m in listed)
    for mid, upstream in ALLOWED.items():
        row = listed[mid]
        assert row["upstream_model"] == upstream
        assert row["enabled"]
        assert "free" in row["capabilities"]
        assert row["input_price_usd_per_1m"] == 0
        assert row["output_price_usd_per_1m"] == 0
        assert row["source_checked_at"] == "2026-10-11"
    assert all(not row["id"].startswith(PROVIDER + "/") for group in registry["groups"].values()
               for row in registry["models"] if row["id"] in group)


def test_worker_and_wrangler_use_approved_existing_store_metadata_only():
    root = Path(__file__).resolve().parents[1]
    bindings = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf-8"))["secrets_store_secrets"]
    ours = [row for row in bindings if row["binding"] == BINDING]
    assert ours == [{
        "binding": BINDING,
        "store_id": "f0b09ca04a7b43248154c773704a5616",
        "secret_name": BINDING,
    }]
    assert BINDING in (root / "worker.py").read_text(encoding="utf-8")
    assert get_platform_provider(PROVIDER).credential_binding_name == BINDING


@pytest.mark.parametrize("mid, upstream", ALLOWED.items())
def test_manual_model_catalog_visibility_and_exact_identity(mid, upstream, live_key):
    decision = resolve_manual_route(mid, allow_external_fallback=False)
    assert decision.selected_model == mid
    assert decision.selected_upstream_model == upstream
    assert decision.platform_provider_id == PROVIDER
    assert decision.fallback_allowed is False
    with TestClient(create_app()) as client:
        resp = client.get("/api/pilot/models")
    assert resp.status_code == 200
    registered = next(row for row in resp.json()["registered_routes"] if row["id"] == mid)
    assert registered["upstream_model"] == upstream
    assert registered["provider_id"] == PROVIDER
    assert registered["auto_eligible"] is False
    assert SYNTHETIC not in resp.text
    assert BINDING not in resp.text


@pytest.mark.parametrize("mid, upstream", ALLOWED.items())
def test_exact_model_is_sent_to_fixed_endpoint_with_bearer(mid, upstream, live_key):
    called = []
    def handler(req):
        called.append(True)
        assert str(req.url) == ORIGIN + "/chat/completions"
        assert req.headers["Authorization"] == "Bearer " + SYNTHETIC
        assert json.loads(req.content) == {
            "model": upstream,
            "messages": [{"role": "user", "content": "synthetic probe"}],
        }
        return httpx.Response(200, json=_completed(model=upstream))
    result = asyncio.run(call_platform_chat_completions(
        model_id=mid, upstream_model=upstream,
        provider="TokenHarbor", platform_provider_id=PROVIDER,
        messages=[{"role": "user", "content": "synthetic probe"}],
        transport=httpx.MockTransport(handler),
    ))
    assert called == [True]
    assert result["model"] == upstream
    assert SYNTHETIC not in repr(result)


@pytest.mark.parametrize("mid, upstream", ALLOWED.items())
def test_exact_model_streaming_keeps_free_id(mid, upstream, live_key):
    called = []
    def handler(req):
        called.append(True)
        assert str(req.url) == ORIGIN + "/chat/completions"
        assert req.headers["Authorization"] == "Bearer " + SYNTHETIC
        assert json.loads(req.content) == {
            "model": upstream,
            "messages": [{"role": "user", "content": "test"}],
            "stream": True,
        }
        payload = (
            'data: '+json.dumps({
                "id": "synthetic-stream", "model": upstream,
                "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]
            })+'\n\n'
            'data: [DONE]\n\n'
        )
        return httpx.Response(200, content=payload.encode())
    async def run():
        return [chunk async for chunk in stream_platform_chat_completions(
            model_id=mid, upstream_model=upstream,
            provider="TokenHarbor", platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "test"}],
            transport=httpx.MockTransport(handler),
        )]
    chunks = asyncio.run(run())
    assert called == [True]
    assert chunks[0].model == upstream
    assert chunks[-1].done is True


@pytest.mark.parametrize("upstream", [
    "claude-haiku-5.5", "deepseek-v4.1-flash",
    "mimo-v2.6-flash:free", "claude-sonnet-5.5",
])
def test_paid_or_unapproved_upstream_cannot_escape_adapter(upstream, live_key):
    called = []
    def forbidden(req):
        called.append(req)
        raise AssertionError("Forbidden paid/unapproved upstream call")
    with pytest.raises(PilotNotConfigured, match="owner-approved free"):
        asyncio.run(call_platform_chat_completions(
            model_id="tokenharbor/claude-haiku-5.5:free",
            upstream_model=upstream,
            provider="TokenHarbor", platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "test"}],
            transport=httpx.MockTransport(forbidden),
        ))
    assert called == []


def test_unapproved_public_model_has_no_manual_route(live_key):
    for mid in ("tokenharbor/mimo-v2.6-flash:free", "tokenharbor/claude-haiku-5.5"):
        with pytest.raises(NoSafeRoute):
            resolve_manual_route(mid, allow_external_fallback=False)


def test_missing_secret_denied_before_network(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(BINDING, raising=False)
    monkeypatch.setenv("PADIEM_GEMINI_API_KEY", "synthetic_other_provider")
    called = []
    with pytest.raises(PilotNotConfigured):
        asyncio.run(call_platform_chat_completions(
            model_id="tokenharbor/deepseek-v4.1-flash:free",
            upstream_model="deepseek-v4.1-flash:free",
            provider="TokenHarbor", platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "test"}],
            transport=httpx.MockTransport(lambda req: called.append(req)),
        ))
    assert called == []


def test_free_quota_429_is_failure_not_paid_model_retry(live_key):
    called = []
    def quota(req):
        called.append(json.loads(req.content)["model"])
        return httpx.Response(429, json={"error": {"code": "free_quota_exhausted"}})
    with pytest.raises(UpstreamRateLimited):
        asyncio.run(call_platform_chat_completions(
            model_id="tokenharbor/deepseek-v4.1-flash:free",
            upstream_model="deepseek-v4.1-flash:free",
            provider="TokenHarbor", platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "test"}],
            transport=httpx.MockTransport(quota),
        ))
    assert called == ["deepseek-v4.1-flash:free"]



@pytest.mark.parametrize("mid", ALLOWED)
def test_free_route_rejects_external_fallback_to_other_paid_provider(mid, live_key):
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(mid, allow_external_fallback=True)
    assert exc.value.reason_code == "tokenharbor_free_only_fallback_disabled"
