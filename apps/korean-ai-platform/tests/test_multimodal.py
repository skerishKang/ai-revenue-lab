from __future__ import annotations

import base64
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.multimodal_contract import MAX_IMAGE_BYTES, validate_image_data_url
from app.pilot.b14_runtime_config import runtime_config


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
    old_mode = runtime_config.provider_mode
    runtime_config.provider_mode = "mock"
    yield
    runtime_config.provider_mode = old_mode


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


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


def test_valid_multimodal_auto_route_uses_fixed_chain_head(
    client, monkeypatch):

    from app.pilot import platform as plat

    # D14 (#2044): b14/auto no longer filters by image capability; the fixed
    # chain head answers and the validated multimodal array passes through.
    monkeypatch.delenv("PADIEM_SENSENOVA_API_KEY", raising=False)
    monkeypatch.delenv("PADIEM_POOLSIDE_API_KEY", raising=False)
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

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake_call)
    response = post_image(client, business14={"required_capabilities": ["chat"]})
    assert response.status_code == 200
    body = response.json()
    assert body["business14"]["selected_model"] == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
    assert body["business14"]["routing_policy"] == "fixed_chain_v1"
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
    from app.pilot import platform as plat

    calls = 0

    async def should_not_call(**kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("platform adapter must not be called")

    monkeypatch.setattr(plat, "call_platform_chat_completions", should_not_call)
    response = post_image(
        client,
        model="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        business14={"allow_external_fallback": True},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "no_safe_route"
    assert body["error"]["upstream_called"] is False
    assert calls == 0


def test_auto_route_ignores_capability_filter_hook(client, monkeypatch):
    """D14 (#2044): the scorer capability filter is dead for b14/auto."""
    from app.pilot import router_core as rcore

    monkeypatch.delenv("PADIEM_SENSENOVA_API_KEY", raising=False)
    monkeypatch.delenv("PADIEM_POOLSIDE_API_KEY", raising=False)
    monkeypatch.setattr(rcore, "_filter_catalog", lambda **kwargs: [])
    response = post_image(client)
    assert response.status_code == 200
    body = response.json()
    assert body["business14"]["routing_policy"] == "fixed_chain_v1"
    assert body["business14"]["selected_model"] == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"


@pytest.mark.asyncio
async def test_live_platform_body_preserves_validated_multimodal_array():
    from app.pilot import platform as plat

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        assert request.headers.get("authorization") is None
        return httpx.Response(
            200,
            json={
                "id": "live-test",
                "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    runtime_config.provider_mode = "live"
    messages = [{"role": "user", "content": multimodal_content()}]
    result = await plat.call_platform_chat_completions(
        messages=messages,
        temperature=0.2,
        max_tokens=100,
        model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        upstream_model="nvidia/nemotron-3-ultra-550b-a55b:free",
        provider="Kilo Gateway / NVIDIA",
        platform_provider_id="kilo",
        transport=httpx.MockTransport(handler),
    )
    assert result["choices"][0]["message"]["content"] == "ok"
    assert captured["json"]["messages"] == messages
    assert captured["json"]["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert "provider" not in captured["json"]
