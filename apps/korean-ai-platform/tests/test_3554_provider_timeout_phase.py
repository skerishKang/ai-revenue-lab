"""#3554: offline-only B14 timeout stage logging; no paid provider calls.

#7241 3a: the phase-log allow-list and the specialized-diagnostics Provider are
read from the app module, and the dispatched subject row comes from the
effective registry, so this suite writes no deployment identity.
"""
from __future__ import annotations

import logging
import httpx
import pytest

from app.pilot import platform as plt
from app.pilot.errors import UpstreamTimeout
from app.pilot.provider_timeout_diagnostics import (
    classify_timeout_phase, log_provider_timeout, log_gateway_deadline,
)

from _registry_values import (
    a_dispatchable_row, provider_of, require_owner_document,
    specialized_timeout_log_provider, timeout_log_allowlist,
    timeout_log_allowlist_excluding,
)

# The dispatched subject is a live row of a Provider on the log allow-list;
# which rows are live belongs to the owner's document (#7241 3b).
require_owner_document()

#: The Provider ids the log surface accepts, and the ones on the generic path.
ALLOWED = sorted(timeout_log_allowlist())
GENERIC = timeout_log_allowlist_excluding()
#: The specialized-diagnostics Provider: allow-listed, on the other log key.
SPECIALIZED_ID = specialized_timeout_log_provider()

#: A dispatchable row whose Provider is on the log allow-list. Which rows are
#: live is an owner decision, so the adapter cases are skipped on a host
#: reading the placeholder fixture.
ROW = a_dispatchable_row(provider_ids=timeout_log_allowlist())

if ROW is not None:
    PROVIDER_ID = provider_of(ROW["id"])
else:  # pragma: no cover - placeholder document; those cases are skipped
    PROVIDER_ID = ""


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


@pytest.mark.parametrize("provider", GENERIC)
@pytest.mark.parametrize("mode", ["completed", "stream"])
def test_allowlisted_providers_log_only_safe_phase(caplog, provider, mode):
    with caplog.at_level(logging.WARNING):
        log_provider_timeout(plt.logger, provider,
                             httpx.ReadTimeout("PRIVATE_API_KEY_BEWARE"), mode)
    assert f"b14_safe_timeout provider={provider} phase=read mode={mode}" in caplog.text
    assert "PRIVATE_API_KEY_BEWARE" not in caplog.text


def test_specialized_legacy_log_preserved_and_unknown_provider_silenced(caplog):
    with caplog.at_level(logging.WARNING):
        log_provider_timeout(plt.logger, SPECIALIZED_ID,
                             httpx.ConnectTimeout("PRIVATE_SECRET"), "completed")
        log_provider_timeout(plt.logger, "malicious SECRET ID",
                             httpx.ReadTimeout("PRIVATE"), "completed")
        log_provider_timeout(plt.logger, PROVIDER_ID, ValueError("PRIVATE"), "completed")
    assert (f"{SPECIALIZED_ID}_safe_timeout provider={SPECIALIZED_ID} "
            f"phase=connect mode=completed") in caplog.text
    assert f"b14_safe_timeout provider={SPECIALIZED_ID}" not in caplog.text
    assert "malicious" not in caplog.text
    assert "PRIVATE" not in caplog.text


def test_gateway_deadline_classification_is_distinct_and_safe(caplog):
    with caplog.at_level(logging.WARNING):
        log_gateway_deadline(plt.logger, PROVIDER_ID)
        log_gateway_deadline(plt.logger, "PRIVATE_MODEL_PATH")
    assert f"b14_gateway_deadline provider={PROVIDER_ID} phase=overall" in caplog.text
    assert "PRIVATE_MODEL_PATH" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,reason", [
    (httpx.ConnectTimeout("PRIVATE_VENDOR_SECRET"), "first_byte"),
    # Before response headers/body arrive, a read timeout is still a first-byte
    # failure; post-byte read gaps are classified separately by the body guard.
    (httpx.ReadTimeout("PRIVATE_QUOTE_CONTENT"), "first_byte"),
])
@pytest.mark.parametrize("stream", [False, True])
async def test_real_platform_adapter_classifies_without_real_provider(
        monkeypatch, caplog, exception, reason, stream):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plt, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    async def handler(req):
        raise exception
    args = dict(
        model_id=ROW["id"],
        upstream_model=ROW["upstream_model"],
        provider=PROVIDER_ID,
        platform_provider_id=PROVIDER_ID,
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
    assert (f"b14_provider_attempt_timeout provider={PROVIDER_ID} reason={reason} "
            f"mode={'stream' if stream else 'completed'}") in caplog.text
    assert "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
async def test_successful_response_does_not_log_timeout_or_retry(monkeypatch, caplog):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plt, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    calls = []
    async def handler(req):
        calls.append(1)
        return httpx.Response(200, json={
            "model": ROW["upstream_model"],
            "choices": [{"message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
        })
    with caplog.at_level(logging.WARNING):
        result = await plt.call_platform_chat_completions(
            model_id=ROW["id"],
            upstream_model=ROW["upstream_model"], provider=PROVIDER_ID,
            platform_provider_id=PROVIDER_ID,
            messages=[{"role": "user", "content": "synthetic"}],
            transport=httpx.MockTransport(handler),
        )
    assert result["choices"][0]["message"]["content"] == "OK"
    assert len(calls) == 1
    assert "b14_safe_timeout" not in caplog.text
    assert "b14_gateway_deadline" not in caplog.text
