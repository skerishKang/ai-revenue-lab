"""#3554: offline-only B14 timeout stage logging; no paid provider calls."""
from __future__ import annotations

import logging
import httpx
import pytest

from app.pilot import platform as plt
from app.pilot.errors import UpstreamTimeout
from app.pilot.provider_timeout_diagnostics import (
    classify_timeout_phase, log_provider_timeout, log_gateway_deadline,
)


@pytest.mark.parametrize("err,phase", [
    (httpx.ConnectTimeout("PRIVATE_BEARER"), "connect"),
    (httpx.ReadTimeout("PRIVATE_DOCUMENT"), "read"),
    (httpx.WriteTimeout("PRIVATE_BODY"), "write"),
    (httpx.PoolTimeout("PRIVATE_ACCOUNT"), "pool"),
    (httpx.TimeoutException("PRIVATE_PATH"), "other"),
])
def test_fixed_phase_classification_and_non_timeout_blocked(err, phase):
    assert classify_timeout_phase(err) == phase
    assert classify_timeout_phase(ValueError("PRIVATE_ACCOUNT")) is None


@pytest.mark.parametrize("provider", ["kira", "sensenova", "google", "inception"])
@pytest.mark.parametrize("mode", ["completed", "stream"])
def test_allowlisted_providers_log_only_safe_phase(caplog, provider, mode):
    with caplog.at_level(logging.WARNING):
        log_provider_timeout(plt.logger, provider,
                             httpx.ReadTimeout("PRIVATE_API_KEY_BEWARE"), mode)
    assert f"b14_safe_timeout provider={provider} phase=read mode={mode}" in caplog.text
    assert "PRIVATE_API_KEY_BEWARE" not in caplog.text


def test_atria_legacy_log_preserved_and_unknown_provider_silenced(caplog):
    with caplog.at_level(logging.WARNING):
        log_provider_timeout(plt.logger, "atria", httpx.ConnectTimeout("PRIVATE_SECRET"), "completed")
        log_provider_timeout(plt.logger, "malicious SECRET ID", httpx.ReadTimeout("PRIVATE"), "completed")
        log_provider_timeout(plt.logger, "kira", ValueError("PRIVATE"), "completed")
    assert "atria_safe_timeout provider=atria phase=connect mode=completed" in caplog.text
    assert "b14_safe_timeout provider=atria" not in caplog.text
    assert "malicious" not in caplog.text
    assert "PRIVATE" not in caplog.text


def test_gateway_deadline_classification_is_distinct_and_safe(caplog):
    with caplog.at_level(logging.WARNING):
        log_gateway_deadline(plt.logger, "kira")
        log_gateway_deadline(plt.logger, "PRIVATE_MODEL_PATH")
    assert "b14_gateway_deadline provider=kira phase=overall" in caplog.text
    assert "PRIVATE_MODEL_PATH" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,phase", [
    (httpx.ConnectTimeout("PRIVATE_VENDOR_SECRET"), "connect"),
    (httpx.ReadTimeout("PRIVATE_QUOTE_CONTENT"), "read"),
])
@pytest.mark.parametrize("stream", [False, True])
async def test_real_platform_adapter_classifies_kira_without_real_provider(
        monkeypatch, caplog, exception, phase, stream):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plt, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    async def handler(req):
        raise exception
    args = dict(
        model_id="kira/qwen3.8-flash-free",
        upstream_model="qwen3.8-flash-free",
        provider="Kira",
        platform_provider_id="kira",
        messages=[{"role": "user", "content": "synthetic no-provider-call"}],
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(UpstreamTimeout):
            if stream:
                async for _ in plt.stream_platform_chat_completions(**args):
                    pass
            else:
                await plt.call_platform_chat_completions(**args)
    assert f"b14_safe_timeout provider=kira phase={phase} mode={'stream' if stream else 'completed'}" in caplog.text
    assert "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
async def test_successful_kira_response_does_not_log_timeout_or_retry(monkeypatch, caplog):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plt, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    calls = []
    async def handler(req):
        calls.append(1)
        return httpx.Response(200, json={
            "model": "qwen3.8-flash-free",
            "choices": [{"message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
        })
    with caplog.at_level(logging.WARNING):
        result = await plt.call_platform_chat_completions(
            model_id="kira/qwen3.8-flash-free",
            upstream_model="qwen3.8-flash-free", provider="Kira",
            platform_provider_id="kira", messages=[{"role": "user", "content": "synthetic"}],
            transport=httpx.MockTransport(handler),
        )
    assert result["choices"][0]["message"]["content"] == "OK"
    assert len(calls) == 1
    assert "b14_safe_timeout" not in caplog.text
    assert "b14_gateway_deadline" not in caplog.text
