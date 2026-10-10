"""B14 shared timeout policy: only offline SenseNova/Inception mock requests.

Explicitly excludes Kira and ModelScope as the Owner requested. The Cloudflare
Python Fetch/HTTPX patch is *not* simulated here. Tests check effective B14
configuration, response wrappers, SSE path and deadline ordering only.
"""
import asyncio
import logging

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot import gateway as gw
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.b14_timeout_policy import (
    CONNECT_SECONDS, READ_SECONDS, WRITE_SECONDS, POOL_SECONDS,
    GATEWAY_WALL_SECONDS, ENGINE_CURRENT_WALL_SECONDS,
    build_provider_http_timeout,
)
from app.pilot.errors import UpstreamTimeout

FIXED = (30.0, 40.0, 20.0, 10.0)


def values(timeout):
    return timeout.connect, timeout.read, timeout.write, timeout.pool


def test_single_source_all_surfaces_and_engine_budget_remain_bounded():
    assert (CONNECT_SECONDS, READ_SECONDS, WRITE_SECONDS, POOL_SECONDS) == FIXED
    assert values(build_provider_http_timeout()) == FIXED
    assert values(runtime_config.build_http_timeout()) == FIXED
    assert gw._UPSTREAM_RETRY_BUDGET_SECONDS == GATEWAY_WALL_SECONDS == 45.0
    assert ENGINE_CURRENT_WALL_SECONDS == 60.0
    assert 0 < min(FIXED) and max(FIXED) < GATEWAY_WALL_SECONDS
    assert gw._UPSTREAM_RETRY_MAX_RETRIES == 2
    assert values(build_provider_http_timeout()) == values(build_provider_http_timeout())


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("provider,model,upstream", [
    ("sensenova", "sensenova/sensenova-6.8-flash-lite", "sensenova-6.8-flash-lite"),
    ("inception", "inception/mercury-2.5", "mercury-2.5"),
])
async def test_actual_adapter_has_shared_phase_values_and_exact_upstream(
    monkeypatch, stream, provider, model, upstream,
):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plat, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    native_client = httpx.AsyncClient
    effective = []
    urls = []

    def client(*args, **kwargs):
        t=kwargs["timeout"]
        effective.append(values(t))
        assert isinstance(kwargs.get("transport"), httpx.MockTransport)
        return native_client(*args, **kwargs)

    async def handler(request):
        urls.append(str(request.url))
        assert request.headers["Content-Type"] == "application/json"
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        import json
        obj=json.loads(request.content)
        assert obj["model"] == upstream
        assert obj["messages"] == [{"role":"user","content":"safe synthetic"}]
        assert obj.get("stream") is True if stream else "stream" not in obj
        if stream:
            return httpx.Response(
                200, content=(
                    'data: {"id":"mock-one","model":"'+upstream+
                    '","choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\n'
                    'data: [DONE]\n\n'
                ).encode(),
            )
        return httpx.Response(
            200, json={"id":"mock-one","model":upstream,
                       "choices":[{"message":{"role":"assistant","content":"OK"},
                                   "finish_reason":"stop"}]},
        )

    monkeypatch.setattr(plat.httpx, "AsyncClient", client)
    kwargs=dict(model_id=model, upstream_model=upstream, provider=provider,
                platform_provider_id=provider,
                messages=[{"role":"user","content":"safe synthetic"}],
                transport=httpx.MockTransport(handler))
    if stream:
        chunks=[c async for c in plat.stream_platform_chat_completions(**kwargs)]
        assert any(c.done is True for c in chunks)
    else:
        result=await plat.call_platform_chat_completions(**kwargs)
        assert result["choices"][0]["message"]["content"] == "OK"
    assert effective == [FIXED]
    assert len(urls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_sensenova_timeout_is_logged_without_exception_secrets(
    monkeypatch, caplog, stream,
):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(plat, "_request_headers",
                        lambda spec, model_id="": {"Content-Type": "application/json"})
    calls=[]

    async def handler(request):
        calls.append(1)
        raise httpx.ConnectTimeout("PRIVATE_TOKEN_AND_MODEL_OUTPUT")
    kwargs=dict(model_id="sensenova/sensenova-6.8-flash-lite",
                upstream_model="sensenova-6.8-flash-lite",
                platform_provider_id="sensenova",provider="sensenova",
                messages=[{"role":"user","content":"safe synthetic"}],
                transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.WARNING):
        with pytest.raises(UpstreamTimeout):
            if stream:
                async for _ in plat.stream_platform_chat_completions(**kwargs):
                    pass
            else:
                await plat.call_platform_chat_completions(**kwargs)
    assert len(calls)==1
    assert f"b14_safe_timeout provider=sensenova phase=connect mode={'stream' if stream else 'completed'}" in caplog.text
    assert "PRIVATE_TOKEN_AND_MODEL_OUTPUT" not in caplog.text
