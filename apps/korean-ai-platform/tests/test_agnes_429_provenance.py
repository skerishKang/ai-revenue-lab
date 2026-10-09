"""Agnes upstream 429: diagnostic provenance stays bounded, never exposes body or key.

All tests are OFFLINE using httpx.MockTransport. Runtime error semantics unchanged.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.pilot.agnes_provider import (
    AGNES_MODEL_ID, AGNES_UPSTREAM_MODEL, AGNES_PROVIDER_ID
)
from app.pilot.errors import UpstreamRateLimited
from app.pilot.platform import (
    _log_agnes_429_evidence, call_platform_chat_completions,
    stream_platform_chat_completions,
)

_LOGGER = "korean-ai-platform.pilot.platform"
_KEY = "sk-test-agnes-provenance-NO-REAL-SECRET"


@pytest.fixture(autouse=True)
def _fake_secret(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("PADIEM_AGNES_API_KEY", _KEY)


def _kwargs(transport):
    return dict(
        model_id=AGNES_MODEL_ID,
        upstream_model=AGNES_UPSTREAM_MODEL,
        provider="Agnes AI",
        platform_provider_id=AGNES_PROVIDER_ID,
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.0,
        max_tokens=100,
        transport=transport,
    )


@pytest.mark.asyncio
async def test_agnes_json_rate_limit_stays_http429_and_logs_only_groups(caplog):
    body_secret = "DO_NOT_LOG_UPSTREAM_RAW_123"
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    def handler(req: httpx.Request):
        assert req.headers.get("authorization") == "Bearer " + _KEY
        return httpx.Response(
            429,
            headers={"content-type": "application/json", "retry-after": "60"},
            json={"error": {"type": "rate_limit_error", "message": body_secret}},
        )

    with pytest.raises(UpstreamRateLimited) as exc:
        await call_platform_chat_completions(**_kwargs(httpx.MockTransport(handler)))
    assert exc.value.code == "upstream_rate_limited"
    assert exc.value.status_code == 429
    log = caplog.text
    assert "agnes_upstream_429_provenance" in log
    assert "media=json" in log
    assert "reason_group=rate_limit" in log
    assert "retry_after_present=True" in log
    assert body_secret not in log and _KEY not in log
    assert "60" not in log


@pytest.mark.asyncio
async def test_agnes_html_cf_edge_429_is_not_mislabeled_proven_waf(caplog):
    secret_in_html = "PRIVATE_EDGE_BODY_DO_NOT_LOG"
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    def handler(_):
        return httpx.Response(429, headers={
            "content-type": "text/html",
            "server": "cloudflare",
            "cf-ray": "PRIVATE_RAY_NO_LOG",
        }, text="<html>" + secret_in_html + "</html>")

    with pytest.raises(UpstreamRateLimited):
        await call_platform_chat_completions(**_kwargs(httpx.MockTransport(handler)))
    log = caplog.text
    assert "media=html" in log
    assert "reason_group=unclassified" in log
    assert "cf_ray_present=True" in log
    assert "server_cloudflare=True" in log
    assert secret_in_html not in log
    assert "PRIVATE_RAY_NO_LOG" not in log
    assert _KEY not in log
    assert "waf_blocked" not in log


@pytest.mark.asyncio
async def test_agnes_streaming_429_records_only_safe_shape(caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    def handler(req):
        assert req.headers.get("authorization") == "Bearer " + _KEY
        assert __import__("json").loads(req.content)["stream"] is True
        return httpx.Response(
            429, headers={"content-type": "application/json"},
            json={"error": {"code": "insufficient_quota", "message": "UNSAFE_PRIVATE_MSG"}},
        )
    with pytest.raises(UpstreamRateLimited):
        async for _event in stream_platform_chat_completions(
            **_kwargs(httpx.MockTransport(handler))
        ):
            pass
    assert "reason_group=quota" in caplog.text
    assert "UNSAFE_PRIVATE_MSG" not in caplog.text
    assert _KEY not in caplog.text


@pytest.mark.asyncio
async def test_success_does_not_log_any_429_diagnostic(caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    def handler(req):
        return httpx.Response(200, json={
            "id": "synthetic", "model": AGNES_UPSTREAM_MODEL,
            "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
        })
    result = await call_platform_chat_completions(**_kwargs(httpx.MockTransport(handler)))
    assert result["model"] == AGNES_UPSTREAM_MODEL
    assert "agnes_upstream_429_provenance" not in caplog.text


def test_non_agnes_provider_429_does_not_log_provenance(caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    _log_agnes_429_evidence("sensenova", 429, httpx.Headers({"content-type": "text/html"}), "<html>SECRET</html>")
    assert "agnes_upstream_429_provenance" not in caplog.text
