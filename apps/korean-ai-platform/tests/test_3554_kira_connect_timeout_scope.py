"""#3554 historical Kira transport regression under Owner's later #4442 policy.

The historical provider-specific connect cap is replaced by B14's shared
15s first-byte and 20s stream-idle limits, with unchanged routing.
"""
import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.errors import UpstreamTimeout


def test_connect_timeout_provider_scope_is_exact_and_bounded():
    timeout = plat.build_provider_http_timeout()
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (
        15.0, 20.0, 120.0, 60.0
    )
    # No Provider-specific exception or implicit fallback is installed.


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("provider,model,upstream,expected", [
    ("sensenova", "sensenova/sensenova-6.8-flash-lite", "sensenova-6.8-flash-lite", 15.0),
    ("inception", "inception/mercury-2.5", "mercury-2.5", 15.0),
])
async def test_exact_live_adapter_uses_provider_connect_timeout_once(
        monkeypatch, caplog, stream, provider, model, upstream, expected):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plat, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    native = httpx.AsyncClient
    captured = []
    requests = []

    def local_client(*args, **kwargs):
        timeout = kwargs["timeout"]
        captured.append((timeout.connect, timeout.read, timeout.write, timeout.pool))
        assert isinstance(kwargs.get("transport"), httpx.MockTransport)
        return native(*args, **kwargs)

    async def handler(request):
        requests.append(str(request.url))
        raise httpx.ConnectTimeout("SYNTHETIC_ONLY_NO_CREDENTIAL_OR_EGRESS")

    monkeypatch.setattr(plat.httpx, "AsyncClient", local_client)
    params = {
        "model_id": model,
        "upstream_model": upstream,
        "provider": provider,
        "platform_provider_id": provider,
        "messages": [{"role": "user", "content": "synthetic"}],
        "transport": httpx.MockTransport(handler),
    }
    with caplog.at_level("WARNING"):
        with pytest.raises(UpstreamTimeout):
            if stream:
                async for _ in plat.stream_platform_chat_completions(**params):
                    pass
            else:
                await plat.call_platform_chat_completions(**params)
    assert captured == [(expected, 20.0, 120.0, 60.0)]
    assert len(requests) == 1
    assert f"b14_provider_attempt_timeout provider={provider} reason=first_byte mode={'stream' if stream else 'completed'}" in caplog.text
    assert "SYNTHETIC_ONLY_NO_CREDENTIAL_OR_EGRESS" not in caplog.text
