"""#3922 Atria-only timeout phase logs, synthetic MockTransport."""
import logging
import httpx
import pytest

from app.pilot import platform as plt
from app.pilot.atria_timeout_diagnostics import (
    classify_atria_timeout, log_atria_timeout,
)
from app.pilot.errors import UpstreamTimeout

@pytest.mark.parametrize("exc,phase",[
    (httpx.ConnectTimeout("SECRET_CONNECT"),"connect"),
    (httpx.ReadTimeout("SECRET_READ"),"read"),
    (httpx.WriteTimeout("SECRET_WRITE"),"write"),
    (httpx.PoolTimeout("SECRET_POOL"),"pool"),
    (httpx.TimeoutException("SECRET_UNKNOWN"),"other"),
])
def test_only_fixed_atria_phase_logged(caplog,exc,phase):
    with caplog.at_level(logging.WARNING):
        log_atria_timeout(plt.logger,"atria",exc,"completed")
    assert f"phase={phase}" in caplog.text
    assert "mode=completed" in caplog.text
    assert "SECRET_" not in caplog.text


@pytest.mark.parametrize("provider",["google","agnes-ai","sensenova","experiential"])
def test_other_models_never_logged(caplog,provider):
    with caplog.at_level(logging.WARNING):
        log_atria_timeout(plt.logger,provider,httpx.ConnectTimeout("SECRET"),"completed")
    assert "atria_safe_timeout" not in caplog.text
    assert "SECRET" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stream",[False,True])
@pytest.mark.parametrize("exception,phase",[
    (httpx.ConnectTimeout("PRIVATE_ACCOUNT_ID"),"connect"),
    (httpx.ReadTimeout("PRIVATE_BEARER_SECRET"),"read"),
])
async def test_real_adapter_preserves_timeout_contract_without_leaking(monkeypatch,caplog,stream,exception,phase):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(plt,"_request_headers",lambda spec,model_id="":{"Content-Type":"application/json"})
    async def handler(req):
        raise exception
    kw=dict(
        model_id="atria/Atria-Dawn-Preview",
        upstream_model="Atria-Dawn-Preview",
        provider="Atria",
        platform_provider_id="atria",
        messages=[{"role":"user","content":"synthetic"}],
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(UpstreamTimeout):
            if stream:
                async for _ in plt.stream_platform_chat_completions(**kw):
                    pass
            else:
                await plt.call_platform_chat_completions(**kw)
    assert f"phase={phase}" in caplog.text
    assert ("mode=stream" if stream else "mode=completed") in caplog.text
    assert "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
async def test_atria_nonstream_success_unchanged(monkeypatch,caplog):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(plt,"_request_headers",lambda spec,model_id="":{"Content-Type":"application/json"})
    async def handler(req):
        return httpx.Response(200,json={
            "id":"synthetic","model":"Atria-Dawn-Preview",
            "choices":[{"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],
        })
    with caplog.at_level(logging.WARNING):
        res=await plt.call_platform_chat_completions(
            model_id="atria/Atria-Dawn-Preview",upstream_model="Atria-Dawn-Preview",
            provider="Atria",platform_provider_id="atria",
            messages=[{"role":"user","content":"synthetic"}],
            transport=httpx.MockTransport(handler),
        )
    assert res["choices"][0]["message"]["content"]=="OK"
    assert "atria_safe_timeout" not in caplog.text
