"""Offline HTTPX-MockTransport verification for ExLab's 429 evidence."""
from __future__ import annotations

import logging

import httpx
import pytest

from app.pilot import platform as plt
from app.pilot.errors import UpstreamRateLimited
from app.pilot.exlab_429_diagnostics import classify_exlab_429, log_exlab_429


@pytest.mark.parametrize(("body","group","subtype"), [
    ('{"error":{"code":"insufficient_quota","message":"free_limit_reached: window"}}',
     "quota", "free_limit_reached"),
    ('{"error":{"code":"insufficient_quota","message":"org_rate_limit reached"}}',
     "quota", "org_rate_limit"),
    ('{"error":{"code":"insufficient_quota","message":"org_token_rate_limit_hour: some"}}',
     "quota", "org_token_rate_limit_hour"),
    ('{"error":{"code":"insufficient_quota","message":"key_daily_cap: capped"}}',
     "quota", "key_daily_cap"),
    ('{"error":{"code":"insufficient_quota","message":"private arbitrary text"}}',
     "quota", "none"),
    ('{"error":{"code":"org_under_review","message":"private"}}',
     "org_review", "none"),
    ('{"error":{"code":"unavailable_route"}}',
     "route_unavailable", "none"),
    ('{"error":{"code":"gateway_overloaded"}}',
     "capacity", "none"),
    ('{"error":{"code":"random-key-private-token"}}',
     "unclassified", "none"),
    ('{"error":{"message":"free_limit_reached private"}}',
     "unclassified", "none"),
    ('{"error":{"code":"insufficient_quota","message":"free_limit_reachedEVIL"}}',
     "quota", "none"),
])
def test_exlab_only_documented_error_codes(body, group, subtype):
    classification = classify_exlab_429(
        "experiential", 429,
        httpx.Headers({"content-type":"application/json",
                       "retry-after":"PRIVATE_RETRY",
                       "cf-ray":"PRIVATE_RAY"}),
        body,
    )
    assert classification == {
        "media": "json", "reason_group": group, "quota_subtype": subtype,
        "retry_after_present": True, "cf_ray_present": True,
    }


@pytest.mark.parametrize(("provider","status"), [
    ("atria",429), ("experiential",400), ("experiential",200), ("google",429),
])
def test_never_log_unrelated_errors(provider,status,caplog):
    with caplog.at_level(logging.WARNING):
        log_exlab_429(plt.logger,provider,status,{},'{"error":{"code":"insufficient_quota"}}')
    assert "b14_exlab_429_safe_metadata" not in caplog.text


@pytest.mark.parametrize(("content_type","body","media"), [
    ("text/html", "<html>private</html>", "html"),
    ("application/json", "not json", "json"),
    ("text/plain", "private", "other"),
    ("application/json", "x"*4097, "json"),
])
def test_untrusted_payload_is_never_logged(caplog,content_type,body,media):
    with caplog.at_level(logging.WARNING):
        log_exlab_429(plt.logger,"experiential",429,
                      httpx.Headers({"content-type":content_type}),body)
    assert "reason_group=unclassified" in caplog.text
    assert "media="+media in caplog.text
    assert body not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stream",[False,True])
async def test_httpx_adapter_keeps_429_and_emits_redacted_classification(
    monkeypatch,caplog,stream,
):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(
        plt,"_request_headers",
        lambda spec,model_id="": {"Content-Type":"application/json"},
    )
    secret="PRIVATE_SECRET_NEVER_REPORT_4220"
    async def reply(req):
        assert req.url.host == "api.experientiallabs.ai"
        return httpx.Response(
            429,
            headers={
                "content-type":"application/json",
                "retry-after":secret,
                "cf-ray":secret,
            },
            json={
                "error": {
                    "code":"insufficient_quota",
                    "message":"free_limit_reached: "+secret,
                    "details":{"customer_data":secret},
                },
            },
        )
    kwargs={
        "model_id":"experiential/qwen3.8-flash-next-uncensored",
        "upstream_model":"qwen3.8-flash-next-uncensored",
        "provider":"Experiential Labs",
        "platform_provider_id":"experiential",
        "messages":[{"role":"user","content":"synthetic only"}],
        "transport":httpx.MockTransport(reply),
    }
    with caplog.at_level(logging.WARNING), pytest.raises(UpstreamRateLimited) as exc:
        if stream:
            async for _ in plt.stream_platform_chat_completions(**kwargs):
                pass
        else:
            await plt.call_platform_chat_completions(**kwargs)
    assert exc.value.status_code==429
    assert "b14_exlab_429_safe_metadata" in caplog.text
    assert "reason_group=quota" in caplog.text
    assert "quota_subtype=free_limit_reached" in caplog.text
    assert "retry_after_present=True" in caplog.text
    assert secret not in caplog.text
    assert "insufficient_quota" not in caplog.text
    assert "free_limit_reached:" not in caplog.text


@pytest.mark.asyncio
async def test_200_does_not_emit_429_log(monkeypatch,caplog):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(
        plt,"_request_headers",
        lambda spec,model_id="": {"Content-Type":"application/json"},
    )
    async def reply(req):
        return httpx.Response(200,json={
            "id":"synthetic","model":"qwen3.8-flash-next-uncensored",
            "choices":[{"message":{"role":"assistant","content":"synthetic OK"},
                        "finish_reason":"stop"}],
        })
    with caplog.at_level(logging.WARNING):
        got=await plt.call_platform_chat_completions(
            model_id="experiential/qwen3.8-flash-next-uncensored",
            upstream_model="qwen3.8-flash-next-uncensored",
            provider="Experiential Labs",platform_provider_id="experiential",
            messages=[{"role":"user","content":"synthetic"}],
            transport=httpx.MockTransport(reply),
        )
    assert got["model"]=="qwen3.8-flash-next-uncensored"
    assert "b14_exlab_429_safe_metadata" not in caplog.text
