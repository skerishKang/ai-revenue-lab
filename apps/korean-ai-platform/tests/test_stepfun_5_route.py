"""StepFun Step 5 manual source route: fixed Kilo no-key transport, no live network."""
import json
import httpx
import pytest
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import KiloFreeRateLimited, PilotNotConfigured
from app.pilot.model_registry_file import read_registry
from app.pilot.platform import call_platform_chat_completions

MID="kilo/stepfun/step-5-preview-free"
UP="stepfun/step-5-preview-free"

def test_step5_owner_trial_is_first_but_never_auto_or_paid():
    registry=read_registry()
    assert registry["models"][0]["id"]==MID
    assert registry["groups"]=={"plus":[],"pro":[],"max":[]}
    model=get_catalog_by_id(MID)
    assert model.upstream_model==UP
    assert model.platform_provider_id=="kilo"
    assert "free" not in model.capabilities  # explicit model, no free-first/Auto admission
    for deleted in ("kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                    "kilo/poolside-laguna-s-2.1-free",
                    "b-ai/qwen3.8-flash",
                    "experiential/gpt-5.6-luna",
                    "infron/motif/motif-3"):
        assert get_catalog_by_id(deleted) is None

@pytest.mark.asyncio
async def test_approved_step5_openai_compatible_request_does_not_expose_secret(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    calls=[]
    def handler(req):
        calls.append(req)
        assert req.url.scheme=="https"
        assert req.url.host=="api.kilo.ai"
        assert req.url.path=="/api/gateway/chat/completions"
        assert "Authorization" not in req.headers
        b=json.loads(req.content)
        assert b["model"]==UP
        assert b["messages"]==[{"role":"user","content":"test only"}]
        return httpx.Response(200,json={
            "id":"cmpl-fixture","model":"stepfun/step-5-preview",
            "choices":[{"index":0,"message":{"role":"assistant","content":"fixture response"},
                        "finish_reason":"stop"}],
            "usage":{"prompt_tokens":4,"completion_tokens":4,"total_tokens":8}
        })
    result=await call_platform_chat_completions(
        model_id=MID,upstream_model=UP,provider="Kilo Gateway / StepFun",
        platform_provider_id="kilo",
        messages=[{"role":"user","content":"test only"}],
        transport=httpx.MockTransport(handler))
    assert len(calls)==1
    assert result["_live"] is True
    assert result["_actual_response_model"]=="stepfun/step-5-preview"
    assert result["choices"][0]["message"]["content"]=="fixture response"

@pytest.mark.asyncio
async def test_step5_rate_limit_single_attempt_no_fallback(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    calls=[]
    def handler(req):
        calls.append(req)
        return httpx.Response(429,json={"error":{"message":"temporary free quota"}})
    with pytest.raises(KiloFreeRateLimited):
        await call_platform_chat_completions(
            model_id=MID,upstream_model=UP,provider="Kilo Gateway / StepFun",
            platform_provider_id="kilo",
            messages=[{"role":"user","content":"test only"}],
            transport=httpx.MockTransport(handler))
    assert len(calls)==1

@pytest.mark.asyncio
async def test_unapproved_stepfun_upstream_cannot_dispatch(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    calls=[]
    def handler(req):
        calls.append(req)
        raise AssertionError("No HTTP allowed for unapproved model")
    with pytest.raises(PilotNotConfigured):
        await call_platform_chat_completions(
            model_id=MID,upstream_model="stepfun/step-3.7-flash",
            provider="Kilo Gateway / StepFun",platform_provider_id="kilo",
            messages=[{"role":"user","content":"test only"}],
            transport=httpx.MockTransport(handler))
    assert calls==[]
