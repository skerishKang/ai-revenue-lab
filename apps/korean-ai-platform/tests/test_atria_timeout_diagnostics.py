"""#3922 Atria-only timeout phase logs, synthetic MockTransport."""
import logging
import httpx
import pytest

from app.pilot import platform as plt
from app.pilot.atria_timeout_diagnostics import (
    classify_atria_timeout, log_atria_timeout,
)
from app.pilot.errors import UpstreamTimeout

from _registry_values import (
    registered_model_id_within,
    registry,
    require_owner_document,
    specialized_timeout_log_provider,
    timeout_log_allowlist,
    timeout_log_allowlist_excluding,
)

# The lane this suite drives (the Provider that owns the specialized timeout
# log contract and the model it serves) is registered only by the owner's
# registry document; the placeholder fixture registers no such Provider, so the
# adapter-level cases have no subject here.
require_owner_document()

#: The one Provider the timeout-log module routes to its own log contract, and
#: the identity the effective document registers for it. Both are read from the
#: app: the module owns the id, the document owns the model (#7241 3b).
LOG_PROVIDER = specialized_timeout_log_provider()
GENERIC_PROVIDERS = timeout_log_allowlist_excluding()
assert set(GENERIC_PROVIDERS) | {LOG_PROVIDER} == set(timeout_log_allowlist())
LANE_MODEL_ID = registered_model_id_within(LOG_PROVIDER)
LANE_UPSTREAM_MODEL = LANE_MODEL_ID.split("/", 1)[1]
#: The adapter's Provider label for this lane, read from the row itself rather
#: than written here (the adapter only echoes it into its evidence).
LANE_PROVIDER_NAME = next(
    row["provider_name"] for row in registry()["models"] if row["id"] == LANE_MODEL_ID
)

@pytest.mark.parametrize("exc,phase",[
    (httpx.ConnectTimeout("SECRET_CONNECT"),"connect"),
    (httpx.ReadTimeout("SECRET_READ"),"read"),
    (httpx.WriteTimeout("SECRET_WRITE"),"write"),
    (httpx.PoolTimeout("SECRET_POOL"),"pool"),
    (httpx.TimeoutException("SECRET_UNKNOWN"),"other"),
])
def test_only_fixed_atria_phase_logged(caplog,exc,phase):
    with caplog.at_level(logging.WARNING):
        log_atria_timeout(plt.logger,LOG_PROVIDER,exc,"completed")
    assert f"phase={phase}" in caplog.text
    assert "mode=completed" in caplog.text
    assert "SECRET_" not in caplog.text


@pytest.mark.parametrize("provider", GENERIC_PROVIDERS)
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
        model_id=LANE_MODEL_ID,
        upstream_model=LANE_UPSTREAM_MODEL,
        provider=LANE_PROVIDER_NAME,
        platform_provider_id=LOG_PROVIDER,
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
    # #6788: the per-attempt first-byte deadline replaced the phase vocabulary.
    assert (f"b14_provider_attempt_timeout provider={LOG_PROVIDER} reason=first_byte "
            f"mode={'stream' if stream else 'completed'}") in caplog.text
    assert "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
async def test_atria_nonstream_success_unchanged(monkeypatch,caplog):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(plt,"_request_headers",lambda spec,model_id="":{"Content-Type":"application/json"})
    async def handler(req):
        return httpx.Response(200,json={
            "id":"synthetic","model":LANE_UPSTREAM_MODEL,
            "choices":[{"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],
        })
    with caplog.at_level(logging.WARNING):
        res=await plt.call_platform_chat_completions(
            model_id=LANE_MODEL_ID,upstream_model=LANE_UPSTREAM_MODEL,
            provider=LANE_PROVIDER_NAME,
            platform_provider_id=LOG_PROVIDER,
            messages=[{"role":"user","content":"synthetic"}],
            transport=httpx.MockTransport(handler),
        )
    assert res["choices"][0]["message"]["content"]=="OK"
    assert "atria_safe_timeout" not in caplog.text
