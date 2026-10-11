"""TokenHarbor: DeepSeek-only owner-approved free route, no real upstream calls.

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


def test_canonical_registration_only_deepseek_free_route():
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
            model_id="tokenharbor/deepseek-v4.1-flash:free",
            upstream_model=upstream,
            provider="TokenHarbor", platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "test"}],
            transport=httpx.MockTransport(forbidden),
        ))
    assert called == []



def test_retired_haiku_cannot_be_dispatched_from_final_adapter(live_key):
    """Catalog and final adapter both deny Haiku even with a working TokenHarbor key."""
    called = []
    def should_not_call(req):
        called.append(req)
        raise AssertionError("Haiku must not reach upstream")
    with pytest.raises(NoSafeRoute):
        resolve_manual_route("tokenharbor/claude-haiku-5.5:free", allow_external_fallback=False)
    with pytest.raises(PilotNotConfigured, match="owner-approved free"):
        asyncio.run(call_platform_chat_completions(
            model_id="tokenharbor/claude-haiku-5.5:free",
            upstream_model="claude-haiku-5.5:free",
            provider="TokenHarbor",
            platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "retired"}],
            transport=httpx.MockTransport(should_not_call),
        ))
    assert not called

def test_unapproved_public_model_has_no_manual_route(live_key):
    for mid in ("tokenharbor/mimo-v2.6-flash:free", "tokenharbor/claude-haiku-5.5", "tokenharbor/claude-haiku-5.5:free"):
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

@pytest.mark.parametrize("upstream_http_status", [401, 403])
@pytest.mark.parametrize("credential_shape", ["expected", "unexpected"])
@pytest.mark.parametrize("response_kind", ["edge_html", "origin_json"])
def test_tokenharbor_auth_failure_logs_only_safe_classification(
    monkeypatch, caplog, upstream_http_status, credential_shape, response_kind,
):
    from app.pilot.errors import UpstreamAuthFailed

    fake_key = "thk_" + "a9b2c3d4e5f6g7h8" * 4
    if credential_shape == "unexpected":
        fake_key = '"' + fake_key + '"'
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, fake_key)

    def fail_with_upstream_status(request):
        assert request.url.host == "tokenharbor.ai"
        if response_kind == "edge_html":
            return httpx.Response(
                upstream_http_status,
                headers={"content-type": "text/html", "server": "cloudflare",
                         "cf-mitigated": "challenge", "cf-ray": "not_for_logs"},
                text="<!doctype html><title>do_not_log_upstream_body</title>",
            )
        return httpx.Response(
            upstream_http_status,
            headers={"content-type": "application/json",
                     "x-vercel-id": "not_for_logs"},
            json={"error": {"message": "do_not_log_upstream_body"}},
        )

    with caplog.at_level("WARNING", logger="korean-ai-platform.pilot.platform"):
        with pytest.raises(UpstreamAuthFailed):
            asyncio.run(call_platform_chat_completions(
                model_id="tokenharbor/deepseek-v4.1-flash:free",
                upstream_model="deepseek-v4.1-flash:free",
                provider="TokenHarbor",
                platform_provider_id=PROVIDER,
                messages=[{"role": "user", "content": "no_customer_data"}],
                transport=httpx.MockTransport(fail_with_upstream_status),
            ))

    assert (
        f"tokenharbor_auth_diagnostic upstream_http_status={upstream_http_status} "
        f"credential_shape={credential_shape}"
    ) in caplog.text
    assert fake_key not in caplog.text
    assert "do_not_log_upstream_body" not in caplog.text
    assert "no_customer_data" not in caplog.text
    assert "not_for_logs" not in caplog.text
    if response_kind == "edge_html":
        assert "response_format=html cf_challenge=True error_family=not_json" in caplog.text
    else:
        assert "response_format=json cf_challenge=False error_family=unclassified" in caplog.text


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("upstream_status", [302, 401, 403, 429])
@pytest.mark.parametrize("response_kind", ["plain_html", "invalid_key", "access_denied", "unknown_code"])
def test_tokenharbor_rejection_diagnostic_shared_by_completed_and_stream(
    monkeypatch, caplog, stream, upstream_status, response_kind,
):
    from app.pilot.errors import (
        UpstreamAuthFailed, UpstreamClientError, UpstreamRateLimited,
    )

    synthetic = "thk_" + "a1b2c3d4e5f6g7h8" * 4
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, synthetic)

    def denied(req):
        assert req.headers["authorization"] == "Bearer " + synthetic
        if response_kind == "plain_html":
            return httpx.Response(
                upstream_status,
                headers={"content-type": "text/html", "server": "cloudflare"},
                text="<html>private_vendor_body_do_not_log</html>",
            )
        code = {
            "invalid_key": "invalid_api_key",
            "access_denied": "permission_denied",
            "unknown_code": "vendor_freeform_private_do_not_log",
        }[response_kind]
        return httpx.Response(
            upstream_status,
            headers={"content-type": "application/json", "server": "cloudflare"},
            json={"error": {"code": code, "message": "private_vendor_body_do_not_log"}},
        )

    kwargs = {
        "model_id": "tokenharbor/deepseek-v4.1-flash:free",
        "upstream_model": "deepseek-v4.1-flash:free",
        "provider": "TokenHarbor",
        "platform_provider_id": PROVIDER,
        "messages": [{"role": "user", "content": "private_request_do_not_log"}],
        "transport": httpx.MockTransport(denied),
    }
    exception_type = (
        UpstreamClientError if upstream_status == 302
        else UpstreamRateLimited if upstream_status == 429
        else UpstreamAuthFailed
    )
    async def run():
        if stream:
            return [event async for event in stream_platform_chat_completions(**kwargs)]
        return await call_platform_chat_completions(**kwargs)

    with caplog.at_level("WARNING", logger="korean-ai-platform.pilot.platform"):
        with pytest.raises(exception_type) as exc:
            asyncio.run(run())

    expected_family = {
        "plain_html": "not_json",
        "invalid_key": "invalid_key",
        "access_denied": "access_denied",
        "unknown_code": "unclassified",
    }[response_kind]
    assert (
        f"tokenharbor_auth_diagnostic upstream_http_status={upstream_status} "
        f"credential_shape=expected"
    ) in caplog.text
    assert f"error_family={expected_family}" in caplog.text
    assert "cf_challenge=False" in caplog.text
    assert synthetic not in caplog.text
    assert "private_vendor_body_do_not_log" not in caplog.text
    assert "private_request_do_not_log" not in caplog.text
    assert "vendor_freeform_private_do_not_log" not in caplog.text
    if upstream_status in (401, 403):
        assert "X-Business14-Provider-Key" not in str(exc.value)
        assert "B14 서버" in str(exc.value)


def test_tokenharbor_streaming_non_auth_route_does_not_log_secrets(monkeypatch, caplog):
    from app.pilot.errors import UpstreamAuthFailed
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, "thk_" + "a1b2c3d4e5f6g7h8" * 4)

    def denied(req):
        return httpx.Response(
            403,
            headers={"content-type": "text/html", "cf-ray": "private_ray_do_not_log"},
            text="private_vendor_body_do_not_log",
        )

    async def run():
        return [event async for event in stream_platform_chat_completions(
            model_id="tokenharbor/deepseek-v4.1-flash:free",
            upstream_model="deepseek-v4.1-flash:free",
            provider="TokenHarbor",
            platform_provider_id=PROVIDER,
            messages=[{"role": "user", "content": "safe_test"}],
            transport=httpx.MockTransport(denied),
        )]

    with caplog.at_level("WARNING", logger="korean-ai-platform.pilot.platform"):
        with pytest.raises(UpstreamAuthFailed):
            asyncio.run(run())
    assert "response_format=html cf_challenge=False error_family=not_json" in caplog.text
    assert "private_ray_do_not_log" not in caplog.text
    assert "private_vendor_body_do_not_log" not in caplog.text
