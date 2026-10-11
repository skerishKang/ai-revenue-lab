"""#3385: same-account Cloudflare Secrets Store web credentials, mock-only."""
from __future__ import annotations

import pytest

from app.config import ConfigError
from app.worker_config import (
    resolve_web_secrets_store_keys,
    settings_from_worker_bindings,
)


class SecretCapability:
    def __init__(self, value="only-in-memory-key", *, fail=False):
        self.value = value
        self.fail = fail
        self.called = 0

    async def get(self):
        self.called += 1
        if self.fail:
            raise RuntimeError("private key material must not escape")
        return self.value


def live_env(**overrides):
    result = {
        "PADIEM_CHAT_RUNTIME_MODE": "b14",
        "PADIEM_CHAT_LIVE_ENABLED": "true",
        "PADIEM_CHAT_B14_BASE_URL": "https://b14.example",
    }
    result.update(overrides)
    return result


@pytest.mark.asyncio
async def test_priority_both_async_same_account_secrets():
    tf = SecretCapability("tf-confidential")
    daum = SecretCapability("daum-confidential")
    env = live_env(TINYFISH_API_KEY=tf, PADIEM_CHAT_DAUM_REST_API_KEY=daum)
    resolved = await resolve_web_secrets_store_keys(env)
    settings = settings_from_worker_bindings(env, resolved_web_keys=resolved)
    assert settings.web_provider == "tinyfish_daum"
    assert settings.tinyfish_api_key == "tf-confidential"
    assert settings.daum_rest_api_key == "daum-confidential"
    assert tf.called == daum.called == 1
    assert "confidential" not in repr(settings)


@pytest.mark.asyncio
async def test_mock_or_explicit_off_never_queries_secrets_store():
    tf, daum = SecretCapability(fail=True), SecretCapability(fail=True)
    for env in [
        {"TINYFISH_API_KEY": tf, "PADIEM_CHAT_DAUM_REST_API_KEY": daum},
        live_env(PADIEM_CHAT_WEB_PROVIDER="off", TINYFISH_API_KEY=tf, PADIEM_CHAT_DAUM_REST_API_KEY=daum),
        live_env(PADIEM_CHAT_LIVE_ENABLED="false", TINYFISH_API_KEY=tf, PADIEM_CHAT_DAUM_REST_API_KEY=daum),
    ]:
        assert await resolve_web_secrets_store_keys(env) == {}
        assert settings_from_worker_bindings(env, resolved_web_keys={}).web_provider == "off"
    assert tf.called == daum.called == 0


@pytest.mark.asyncio
async def test_explicit_daum_reads_only_daum_and_keeps_direct_secret_compat():
    tf, daum = SecretCapability(fail=True), SecretCapability("direct-test-key")
    env = live_env(PADIEM_CHAT_WEB_PROVIDER="daum", TINYFISH_API_KEY=tf, PADIEM_CHAT_DAUM_REST_API_KEY=daum)
    got = await resolve_web_secrets_store_keys(env)
    assert got == {"PADIEM_CHAT_DAUM_REST_API_KEY": "direct-test-key"}
    assert tf.called == 0 and daum.called == 1
    configured = settings_from_worker_bindings(env, resolved_web_keys=got)
    assert configured.web_provider == "daum" and configured.tinyfish_api_key is None

    direct_env = live_env(
        PADIEM_CHAT_WEB_PROVIDER="tinyfish",
        TINYFISH_API_KEY="already-worker-secret-text",
    )
    assert (await resolve_web_secrets_store_keys(direct_env))["TINYFISH_API_KEY"] == "already-worker-secret-text"


@pytest.mark.asyncio
async def test_unbound_or_wrong_typed_fail_closed_without_key_leak():
    unbound = live_env()
    got = await resolve_web_secrets_store_keys(unbound)
    with pytest.raises(ConfigError):
        settings_from_worker_bindings(unbound, resolved_web_keys=got)
    bad = live_env(
        TINYFISH_API_KEY=SecretCapability(fail=True),
        PADIEM_CHAT_DAUM_REST_API_KEY=SecretCapability("daum-secret"),
    )
    with pytest.raises(ConfigError) as err:
        await resolve_web_secrets_store_keys(bad)
    assert "private key" not in str(err.value)
    assert "daum-secret" not in str(err.value)

    class NonAsyncSecret:
        def get(self):
            return "bad-sync-secret"
    bad["TINYFISH_API_KEY"] = NonAsyncSecret()
    with pytest.raises(ConfigError):
        await resolve_web_secrets_store_keys(bad)


@pytest.mark.asyncio
async def test_keys_never_dispatched_or_queried_for_unknown_provider():
    secret = SecretCapability(fail=True)
    for provider in ["off", "firecrawl", "unknown-provider"]:
        env = live_env(PADIEM_CHAT_WEB_PROVIDER=provider, TINYFISH_API_KEY=secret)
        assert await resolve_web_secrets_store_keys(env) == {}
    assert secret.called == 0
