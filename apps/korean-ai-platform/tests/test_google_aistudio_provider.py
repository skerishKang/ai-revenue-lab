"""Exact owner-selected Google AI Studio B14 registration, mock-only contract tests.

This suite never sends live model requests or reads real credential values.
"""
import asyncio

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import CATALOG_BY_ID, CATALOG_MODELS, get_catalog_by_id
from app.pilot.google_provider import (
    GOOGLE_ALLOWED_HOST,
    GOOGLE_BASE_ORIGIN,
    GOOGLE_CREDENTIAL_BINDING,
    GOOGLE_PROVIDER_ID,
    register_google_provider,
)
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.platform import call_platform_chat_completions
from app.pilot.errors import PilotNotConfigured

GOOGLE = {
    "google/gemini-3.1-flash-lite": "gemini-3.1-flash-lite",
    "google/gemini-3.5-flash-lite": "gemini-3.5-flash-lite",
    "google/gemma-4-26b-a4b-it": "gemma-4-26b-a4b-it",
    "google/gemma-4-31b-it": "gemma-4-31b-it",
}


def _call(model_id, upstream, messages, transport):
    return asyncio.run(call_platform_chat_completions(
        model_id=model_id,
        upstream_model=upstream,
        provider="Google AI Studio",
        platform_provider_id=GOOGLE_PROVIDER_ID,
        messages=messages,
        max_tokens=None,
        transport=transport,
    ))


def test_exact_owner_four_manual_catalog_only():
    for mid, upstream in GOOGLE.items():
        m=get_catalog_by_id(mid)
        assert m is not None
        assert m.upstream_model == upstream
        assert m.platform_provider_id == "google"
        assert m.enabled is True
        assert mid in CATALOG_BY_ID
        assert mid not in {x.model_id for x in CATALOG_MODELS}
        assert "chat" in m.capabilities
    assert "image" not in get_catalog_by_id("google/gemma-4-31b-it").capabilities
    for mid in set(GOOGLE)-{"google/gemma-4-31b-it"}:
        assert "image" in get_catalog_by_id(mid).capabilities


def test_registered_endpoint_is_fixed_compatible_origin_and_provider_is_idempotent():
    spec=get_platform_provider(GOOGLE_PROVIDER_ID)
    assert spec is not None
    assert spec.base_origin == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert spec.allowed_hosts == ("generativelanguage.googleapis.com",)
    assert spec.credential_binding_name == "PADIEM_GEMINI_API_KEY"
    assert GOOGLE_BASE_ORIGIN == spec.base_origin
    assert GOOGLE_ALLOWED_HOST == spec.allowed_hosts[0]
    assert GOOGLE_CREDENTIAL_BINDING == spec.credential_binding_name
    ids=set(CATALOG_BY_ID)
    register_google_provider()
    assert set(CATALOG_BY_ID) == ids
    with TestClient(create_app()) as client:
        data=client.get("/api/pilot/models").json()
    routes={v["id"]: v for v in data["registered_routes"]}
    for mid in GOOGLE:
        assert routes[mid]["provider_id"] == "google"
        assert routes[mid]["explicit_only"] is True
        assert routes[mid]["auto_eligible"] is False
        assert routes[mid]["free"] is False


@pytest.mark.parametrize("mid,upstream", tuple(GOOGLE.items()))
def test_openai_compatible_bearer_path_and_exact_model_without_real_network(
    mid,upstream,monkeypatch
):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    # Synthetic string is never a real credential; it is only inspected by MockTransport.
    monkeypatch.setenv("PADIEM_GEMINI_API_KEY","synthetic_google_credential_abcdefghijk")
    called=[]
    def mock(req):
        called.append(req)
        assert req.url.scheme=="https"
        assert req.url.host=="generativelanguage.googleapis.com"
        assert req.url.path=="/v1beta/openai/chat/completions"
        assert req.headers["authorization"]=="Bearer synthetic_google_credential_abcdefghijk"
        assert req.headers["content-type"]=="application/json"
        import json
        payload=json.loads(req.content)
        assert payload["model"]==upstream
        assert payload["messages"]==[{"role":"user","content":"fixture"}]
        assert "max_tokens" not in payload
        return httpx.Response(200,json={
            "id":"mock_google_success",
            "object":"chat.completion",
            "model":upstream,
            "choices":[{"index":0,"message":{"role":"assistant","content":"mock-ok"},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":4,"completion_tokens":3,"total_tokens":7},
        })
    result=_call(mid,upstream,[{"role":"user","content":"fixture"}],httpx.MockTransport(mock))
    assert result["_live"] is True  # mock transport, NOT a real upstream call
    assert result["_requested_upstream_model"]==upstream
    assert result["_actual_response_model"]==upstream
    assert result["choices"][0]["message"]["content"]=="mock-ok"
    assert len(called)==1


def test_missing_google_key_fails_closed_before_network(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.delenv("PADIEM_GEMINI_API_KEY",raising=False)
    calls=[]
    def mock(req):
        calls.append(req)
        raise AssertionError("network must not be called")
    with pytest.raises(PilotNotConfigured):
        _call("google/gemini-3.1-flash-lite","gemini-3.1-flash-lite",
              [{"role":"user","content":"fixture"}],httpx.MockTransport(mock))
    assert calls == []


def test_openai_multimodal_image_input_payload_not_image_generation(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setenv("PADIEM_GEMINI_API_KEY","synthetic_google_credential_abcdefghijk")
    import json
    messages=[{"role":"user","content":[
        {"type":"text","text":"Check synthetic image."},
        {"type":"image_url","image_url":{"url":"data:image/png;base64,YQ=="}},
    ]}]
    def mock(req):
        payload=json.loads(req.content)
        assert payload["model"]=="gemini-3.1-flash-lite"
        assert payload["messages"]==messages
        return httpx.Response(200,json={
            "model":"gemini-3.1-flash-lite",
            "choices":[{"message":{"role":"assistant","content":"fixture text"}}],
        })
    result=_call("google/gemini-3.1-flash-lite","gemini-3.1-flash-lite",
                 messages,httpx.MockTransport(mock))
    assert result["choices"][0]["message"]["content"]=="fixture text"
