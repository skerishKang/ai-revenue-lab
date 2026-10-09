"""Synthetic-only Agnes 429 provenance: exact original 429 and secret safety."""
from __future__ import annotations

import logging

import httpx
import pytest

from app.pilot.agnes_429_diagnostics import classify_agnes_429, log_agnes_429
from app.pilot import platform as plt
from app.pilot.errors import UpstreamRateLimited


@pytest.mark.parametrize("content_type,body,category,media", [
    ("application/json", '{"error":{"code":"quota_exceeded"}}', "quota", "json"),
    ("application/json", '{"error":{"type":"rate_limit_error"}}', "rate_limit", "json"),
    ("application/json", '{"error":{"code":"capacity_exceeded"}}', "capacity", "json"),
    ("application/json", '{"error":{"code":"waf_blocked"}}', "policy", "json"),
    ("application/json", '{"error":{"message":"private-secret"}}', "unclassified", "json"),
    ("application/json", "{bad json", "unclassified", "json"),
    ("text/html", "<html>private-secret</html>", "unclassified", "html"),
    ("text/plain", "private-secret", "unclassified", "other"),
])
def test_classifies_only_allowlisted_metadata(content_type, body, category, media):
    data=classify_agnes_429("agnes-ai", 429, httpx.Headers({
        "content-type": content_type, "cf-ray":"PRIVATE-RAY", "server":"cloudflare",
        "retry-after":"PRIVATE-TIME"
    }), body)
    assert data == {
        "media":media, "reason_group":category, "retry_after_present":True,
        "cf_ray_present":True, "server_cloudflare":True,
    }


@pytest.mark.parametrize("provider,status", [
    ("google",429), ("agnes-ai",400), ("sensenova",429), ("agnes-ai",200)
])
def test_nothing_logged_for_other_provider_or_status(provider,status,caplog):
    with caplog.at_level(logging.WARNING):
        log_agnes_429(plt.logger,provider,status,httpx.Headers({}),"SECRET")
    assert "agnes_429_safe_metadata" not in caplog.text
    assert "SECRET" not in caplog.text


def test_no_secret_or_raw_body_or_raw_headers_in_log(caplog):
    secret="PRIVATE_SECRET_DO_NOT_LOG_22"
    body='{"error":{"code":"quota_exceeded","message":"'+secret+'"},"account":"'+secret+'"}'
    headers=httpx.Headers({
        "content-type":"application/json", "cf-ray":secret, "retry-after":secret,
        "authorization":"Bearer "+secret, "server":"cloudflare",
    })
    with caplog.at_level(logging.WARNING):
        log_agnes_429(plt.logger, "agnes-ai", 429,headers,body)
    assert secret not in caplog.text
    assert "quota_exceeded" not in caplog.text
    assert '"account"' not in caplog.text
    assert "agnes_429_safe_metadata" in caplog.text
    assert "reason_group=quota" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False,True])
async def test_real_adapter_429_nonstream_and_stream(monkeypatch,caplog,stream):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(plt,"_request_headers", lambda spec, model_id="": {"Content-Type":"application/json"})
    private_marker="PRIVATE-SENTINEL-SECRET-999"
    async def handler(req):
        return httpx.Response(
            429,
            headers={"content-type":"application/json","cf-ray":private_marker,
                     "retry-after":"21","server":"cloudflare"},
            json={"error":{"code":"quota_exceeded","message":private_marker}},
        )
    kwargs=dict(
        model_id="agnes-ai/agnes-3.0-flash",upstream_model="agnes-3.0-flash",
        provider="Agnes",platform_provider_id="agnes-ai",
        messages=[{"role":"user","content":"synthetic"}],
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(UpstreamRateLimited):
            if stream:
                async for _ in plt.stream_platform_chat_completions(**kwargs):
                    pass
            else:
                await plt.call_platform_chat_completions(**kwargs)
    assert "agnes_429_safe_metadata" in caplog.text
    assert private_marker not in caplog.text
    assert "quota_exceeded" not in caplog.text
    assert "reason_group=quota" in caplog.text


@pytest.mark.asyncio
async def test_agnes_success_does_not_add_provenance_log(monkeypatch,caplog):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(plt,"_request_headers", lambda spec, model_id="": {"Content-Type":"application/json"})
    async def handler(req):
        return httpx.Response(200,json={
            "id":"synthetic", "model":"agnes-3.0-flash",
            "choices":[{"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],
        })
    with caplog.at_level(logging.WARNING):
        result=await plt.call_platform_chat_completions(
            model_id="agnes-ai/agnes-3.0-flash",upstream_model="agnes-3.0-flash",
            provider="Agnes",platform_provider_id="agnes-ai",
            messages=[{"role":"user","content":"synthetic"}],
            transport=httpx.MockTransport(handler),
        )
    assert result["choices"][0]["message"]["content"]=="OK"
    assert "agnes_429_safe_metadata" not in caplog.text
