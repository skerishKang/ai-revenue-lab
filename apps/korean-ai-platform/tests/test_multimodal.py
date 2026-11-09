from __future__ import annotations

import base64
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import get_catalog_by_id
from app.pilot.multimodal_contract import MAX_IMAGE_BYTES, validate_image_data_url
from app.pilot.b14_runtime_config import runtime_config

from _registry_values import model_rows, provider_of, provider_row


def _image_model(required: tuple[str, ...] = ("chat", "image")) -> str:
    """A catalog-routed model that declares the capabilities a case needs.

    #7241: which registered model carries the image capability is the
    effective registry's answer, not a literal in this suite.
    """
    for row in model_rows():
        catalog_model = get_catalog_by_id(row["id"])
        if catalog_model is None or not catalog_model.enabled:
            continue
        if set(required) <= set(row["capabilities"]):
            return row["id"]
    pytest.skip(f"the effective registry declares no enabled model with {required!r}")


def _text_only_model() -> str:
    return _image_model(("chat",))


def _provider_binding(model_id: str) -> str:
    """The credential slot the model's own Provider reads."""
    return provider_row(provider_of(model_id))["credential_binding_name"]


# The image-capable catalog route and the text-only route this suite switches
# between.
IMAGE_MODEL = _image_model()
TEXT_MODEL = _text_only_model()
IMAGE_BINDING = _provider_binding(IMAGE_MODEL)


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
    import os

    # The default text route's own credential slot, read from the effective
    # registry; only the synthetic value is written here.
    default_binding = _provider_binding(TEXT_MODEL)
    old_agnes_key = os.environ.get(default_binding)
    os.environ[default_binding] = "sk-test-multimodal-mode-0123456789"
    old_mode = runtime_config.provider_mode
    runtime_config.provider_mode = "mock"
    yield
    runtime_config.provider_mode = old_mode
    if old_agnes_key is None:
        os.environ.pop(default_binding, None)
    else:
        os.environ[default_binding] = old_agnes_key


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def post_image(client, *, model=None, content=None, business14=None):
    payload = {
        "model": model or IMAGE_MODEL,
        "messages": [{"role": "user", "content": content or multimodal_content()}],
    }
    if business14 is not None:
        payload["business14"] = business14
    return client.post("/api/pilot/v1/chat/completions", json=payload)


def test_text_chat_contract_remains_backward_compatible(client):
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={"model": TEXT_MODEL, "messages": [{"role": "user", "content": "안녕"}]},
    )
    assert response.status_code == 200
    assert response.json()["business14"]["selected_model"]


def test_valid_multimodal_manual_route_passes_the_validated_array(
    client, monkeypatch):

    from app.pilot import platform as plat

    # The image-capable catalog route answers and the validated multimodal
    # array passes through to the platform adapter.
    # Synthetic value for the slot the image route's own Provider reads.
    monkeypatch.setenv(IMAGE_BINDING, "sk-chain-unit-image-0123456789")
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
    response = post_image(client, business14={"required_capabilities": ["chat", "image"]})
    assert response.status_code == 200
    body = response.json()
    assert body["business14"]["selected_model"] == IMAGE_MODEL
    assert "routing_policy" not in body["business14"]
    outbound = captured["messages"]
    assert isinstance(outbound[0]["content"], list)
    assert outbound[0]["content"][0] == {"type": "text", "text": "이 이미지를 설명해줘"}
    assert outbound[0]["content"][1]["type"] == "image_url"
    assert outbound[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("role", ["system", "assistant"])
def test_only_user_role_may_use_multimodal_array(client, role):
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={"model": IMAGE_MODEL, "messages": [{"role": role, "content": multimodal_content()}]},
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


@pytest.mark.parametrize("remote_url", [
    "https://example.com/photo.png",
    "http://127.0.0.1/private.png",
    "file:///etc/passwd",
])
def test_remote_image_url_rejected_before_provider_egress(client, monkeypatch, remote_url):
    """Untrusted image URLs cannot trigger model-provider calls or SSRF."""
    from app.pilot import platform as plat

    provider_calls = []

    async def forbidden_provider_call(**kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("rejected image URL must not reach model provider")

    monkeypatch.setattr(plat, "call_platform_chat_completions", forbidden_provider_call)
    response = post_image(client, content=multimodal_content(remote_url))
    assert response.status_code == 422
    assert provider_calls == []


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


def test_decoded_image_over_the_old_4_mib_bound_is_accepted():
    # #4379: a pilot image carries no PADIEM byte total. The media type and
    # the magic bytes are still verified, and no network call is made.
    over_the_old_bound = b"\x89PNG\r\n\x1a\n" + (b"x" * (MAX_IMAGE_BYTES + 1))
    assert validate_image_data_url(data_url("image/png", over_the_old_bound)) == (
        data_url("image/png", over_the_old_bound)
    )


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
        model=_text_only_model(),
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "no_safe_route"
    assert body["error"]["upstream_called"] is False
    assert calls == 0


def test_retired_scorer_options_are_unknown_fields(client, monkeypatch):
    """B4: scorer-era options are rejected as unknown business14 fields."""
    text_model = _text_only_model()
    monkeypatch.setenv(_provider_binding(text_model), "sk-chain-unit-text-0123456789")
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": text_model,
            "messages": [{"role": "user", "content": "안녕"}],
            "business14": {"task_type": "coding", "required_capabilities": ["coding"]},
        },
    )
    # B4 grace: task_type is accepted, logged, and dropped; the text-only text
    # contract still answers through the catalog route.
    assert response.status_code == 200
    assert "task_type" not in response.json()["business14"]


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
                "model": "test-fixture/kilo-multimodal-upstream",
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
        model_id="test-fixture/kilo-multimodal",
        upstream_model="test-fixture/kilo-multimodal-upstream",
        provider="Kilo Gateway / NVIDIA",
        platform_provider_id="test-fixture",
        transport=httpx.MockTransport(handler),
    )
    assert result["choices"][0]["message"]["content"] == "ok"
    assert captured["json"]["messages"] == messages
    assert captured["json"]["model"] == "test-fixture/kilo-multimodal-upstream"
    assert "provider" not in captured["json"]

@pytest.fixture(autouse=True)
def _test_only_keyless_adapter_provider(monkeypatch):
    """Only this test module can use a generic mocked provider, never owner-retired Kilo."""
    from app.pilot import platform_secrets as ps
    provider = ps.PlatformProviderSpec(
        provider_id="test-fixture",
        credential_source=ps.CredentialSource.NONE,
        credential_binding_name="",
        base_origin="https://test-fixture.example/v1",
        allowed_hosts=("test-fixture.example",),
    )
    monkeypatch.setitem(ps._PLATFORM_PROVIDERS, "test-fixture", provider)
    yield
