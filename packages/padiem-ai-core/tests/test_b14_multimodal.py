from __future__ import annotations

import base64

import pytest

from padiem_ai_core.b14_multimodal import (
    B14MultimodalChatRequest,
    MAX_B14_IMAGE_BYTES,
)
from padiem_ai_core.b14_execution import B14ChatRequest, B14RoutingOptions

JPEG = b"\xff\xd8\xff\xe0slice5"
PNG = b"\x89PNG\r\n\x1a\nslice5"
WEBP = b"RIFF\x08\x00\x00\x00WEBPslice5"


def data_url(media_type: str, data: bytes) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def content(media_type="image/png", data=PNG):
    return [
        {"type": "text", "text": "  describe  "},
        {"type": "image_url", "image_url": {"url": data_url(media_type, data)}},
    ]


@pytest.mark.parametrize(
    ("media_type", "data"),
    [("image/jpeg", JPEG), ("image/png", PNG), ("image/webp", WEBP)],
)
def test_multimodal_request_is_b14_request_compatible_and_round_trips(media_type, data) -> None:
    request = B14MultimodalChatRequest(
        messages=(
            {"role": "system", "content": "system"},
            {"role": "user", "content": content(media_type, data)},
        ),
        routing=B14RoutingOptions(required_capabilities=("free", "image")),
    )
    assert isinstance(request, B14ChatRequest)
    payload = request.to_payload()
    assert payload["messages"][1]["content"][0] == {"type": "text", "text": "describe"}
    assert payload["messages"][1]["content"][1]["image_url"]["url"] == data_url(media_type, data)
    assert payload["business14"]["required_capabilities"] == ["free", "image"]


def test_multimodal_request_is_copy_and_freeze_safe() -> None:
    parts = content()
    messages = [{"role": "user", "content": parts}]
    request = B14MultimodalChatRequest(messages=messages)
    parts[0]["text"] = "mutated"
    parts[1]["image_url"]["url"] = "mutated"
    messages.clear()
    payload = request.to_payload()
    assert payload["messages"][0]["content"][0]["text"] == "describe"
    with pytest.raises(TypeError):
        request.messages[0]["content"][0]["text"] = "blocked"  # type: ignore[index]


@pytest.mark.parametrize("role", ["system", "assistant"])
def test_multimodal_rejected_for_non_user_roles(role) -> None:
    with pytest.raises(ValueError, match="only user messages"):
        B14MultimodalChatRequest(messages=({"role": role, "content": content()},))


@pytest.mark.parametrize(
    "parts",
    [
        [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
        [
            {"type": "text", "text": "a"},
            {"type": "image_url", "image_url": {"url": data_url("image/png", PNG)}},
            {"type": "image_url", "image_url": {"url": data_url("image/png", PNG)}},
        ],
        [
            {"type": "text", "text": "a", "extra": True},
            {"type": "image_url", "image_url": {"url": data_url("image/png", PNG)}},
        ],
        [
            {"type": "text", "text": "a"},
            {"type": "audio", "url": "data:audio/wav;base64,AAAA"},
        ],
    ],
)
def test_invalid_multimodal_shapes_fail_closed(parts) -> None:
    with pytest.raises(ValueError):
        B14MultimodalChatRequest(messages=({"role": "user", "content": parts},))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/image.png",
        "data:image/gif;base64,R0lGODlh",
        "data:image/png;base64,not-valid-base64!!",
        data_url("image/jpeg", PNG),
    ],
)
def test_remote_unsupported_bad_base64_and_magic_mismatch_rejected_without_echo(url) -> None:
    with pytest.raises(ValueError) as info:
        B14MultimodalChatRequest(
            messages=(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "x"},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                },
            )
        )
    assert url not in str(info.value)


def test_image_over_4_mib_rejected_without_echo() -> None:
    oversized = b"\x89PNG\r\n\x1a\n" + (b"x" * MAX_B14_IMAGE_BYTES)
    url = data_url("image/png", oversized)
    with pytest.raises(ValueError, match="4 MiB") as info:
        B14MultimodalChatRequest(
            messages=({"role": "user", "content": content("image/png", oversized)},)
        )
    assert url not in str(info.value)


def test_text_only_behavior_remains_equal_to_base_request() -> None:
    messages = ({"role": "user", "content": " hello "},)
    base = B14ChatRequest(messages=messages)
    extended = B14MultimodalChatRequest(messages=messages)
    assert extended.to_payload() == base.to_payload()
