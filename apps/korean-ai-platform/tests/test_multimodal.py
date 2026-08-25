from __future__ import annotations

import base64
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import get_catalog_by_id
from app.pilot.multimodal_contract import MAX_IMAGE_BYTES, validate_image_data_url
from app.pilot.openrouter_config import openrouter_config


PNG = b"\x89PNG\r\n\x1a\n" + b"phase8"
JPEG = b"\xff\xd8\xff\xe0" + b"phase8"
WEBP = b"RIFF\x08\x00\x00\x00WEBP" + b"phase8"


def data_url(media_type: str = "image/png", data: bytes = PNG) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def multimodal_content(url: str | None = None):
    return [
        {"type": "text", "text": "이 이미지를 설명해줘"},
        {"type": "image_url", "image_url": {"url": url or data_url()}},
    ]


@pytest.fixture(autouse=True)
def _mock_openrouter_mode():
    old_mode = openrouter_config.provider_mode
    old_key = openrouter_config.api_key
    old_base = openrouter_config.base_url
    openrouter_config.provider_mode = "mock"
    openrouter_config.api_key = ""
    yield
    openrouter_config.provider_mode = old_mode
    openrouter_config.api_key = old_key
    openrouter_config.base_url = old_base


@pytest.fixture()
def client():
    return TestClient(create_app())


def post_image(client, *, model="b14/auto", content=None, business14=None):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content or multimodal_content()}],
    }
    if business14 is not None:
        payload["business14"] = business14
    return client.post("/api/pilot/v1/chat/completions", json=payload)


def test_text_chat_contract_remains_backward_compatible(client):
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={"model": "b14/auto", "messages": [{"role": "user", "content": "안녕"}]},
    )
    assert response.status_code == 200
    assert response.json()["business14"]["selected_model"]


def test_valid_multimodal_auto_route_selects_image_capable_model(client, monkeypatch):
    from app.pilot import openrouter as orv

    captured = {}

    async def fake_call(**kwargs):
        captured.update(kwargs)
        return {
            "id": "mock-mm",
            "object": "chat.completion",
            "model": kwargs["upstream_model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "이미지 응답"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_actual_response_model": kwargs["upstream_model"],
        }

    monkeypatch.setattr(orv, "call_openrouter_chat_completions", fake_call)
    response = post_image(client, business14={"required_capabilities": ["chat"]})
    assert response.status_code == 200
    body = response.json()
    selected = get_catalog_by_id(body["business14"]["selected_model"])
    assert selected is not None
    assert "image" in selected.capabilities
    assert body["business14"]["selected_model"] == "google/gemini-2.5-flash"
    outbound = captured["messages"]
    assert isinstance(outbound[0]["content"], list)
    assert outbound[0]["content"][0] == {"type": "text", "text": "이 이미지를 설명해줘"}
    assert outbound[0]["content"][1]["type"] == "image_url"
    assert outbound[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("role", ["system", "assistant"])
def test_only_user_role_may_use_multimodal_array(client, role):
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={"model": "b14/auto", "messages": [{"role": role, "content": multimodal_content()}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_body"


@pytest.mark.parametrize(
    "content",
    [
        [{"type": "text", "text": "hi", "extra": "x"}, {"type": "image_url", "image_url": {"url": data_url()}}],
        [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": data_url(), "detail": "high"}}],
        [{"type": "text", "text": "hi"}, {"type": "audio", "data": "x"}],
    ],
)
def test_unknown_multimodal_fields_and_types_rejected(client, content):
    response = post_image(client, content=content)
    assert response.status_code == 422


def test_remote_image_url_rejected(client):
    response = post_image(client, content=multimodal_content("https://example.com/photo.png"))
    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "data:image/png;base64,not base64!!",
        data_url("image/gif", b"GIF89a"),
        data_url("image/jpeg", PNG),
        data_url("image/png", JPEG),
        data_url("image/webp", PNG),
    ],
)
def test_invalid_base64_mime_or_magic_rejected(client, url):
    response = post_image(client, content=multimodal_content(url))
    assert response.status_code == 422


def test_decoded_image_over_4_mib_rejected_without_network():
    too_large = b"\x89PNG\r\n\x1a\n" + (b"x" * MAX_IMAGE_BYTES)
    with pytest.raises(ValueError, match="4 MiB"):
        validate_image_data_url(data_url("image/png", too_large))


def test_manual_text_only_model_fails_before_openrouter_call(client, monkeypatch):
    from app.pilot import openrouter as orv

    calls = 0

    async def should_not_call(**kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("OpenRouter must not be called")

    monkeypatch.setattr(orv, "call_openrouter_chat_completions", should_not_call)
    response = post_image(
        client,
        model="openrouter/free",
        business14={"allow_external_fallback": True},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "no_safe_route"
    assert body["error"]["upstream_called"] is False
    assert calls == 0


def test_no_image_capable_auto_candidate_fails_before_upstream(client, monkeypatch):
    from app.pilot import openrouter as orv
    from app.pilot import router_core as rcore

    calls = 0

    async def should_not_call(**kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("OpenRouter must not be called")

    monkeypatch.setattr(orv, "call_openrouter_chat_completions", should_not_call)
    monkeypatch.setattr(rcore, "_filter_catalog", lambda **kwargs: [])
    response = post_image(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_safe_route"
    assert calls == 0


@pytest.mark.asyncio
async def test_live_openrouter_body_preserves_validated_multimodal_array():
    from app.pilot import openrouter as orv

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "live-test",
                "model": "google/gemini-2.5-flash",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    openrouter_config.provider_mode = "live"
    openrouter_config.api_key = "phase8-fixture-nonsecret-value"
    messages = [{"role": "user", "content": multimodal_content()}]
    result = await orv.call_openrouter_chat_completions(
        messages=messages,
        temperature=0.2,
        max_tokens=100,
        model_id="google/gemini-2.5-flash",
        upstream_model="google/gemini-2.5-flash",
        provider="Google",
        transport=httpx.MockTransport(handler),
    )
    assert result["choices"][0]["message"]["content"] == "ok"
    assert captured["json"]["messages"] == messages
    assert captured["json"]["model"] == "google/gemini-2.5-flash"
