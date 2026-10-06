"""Kilo primary-route contract after the #3579 policy v2 successor change.

The canonical text primary is the owner-selected Ling 3.1 Flash successor;
the vision primary remains pending. The ended Space Bunny lane keeps only
retirement metadata and is no longer registered in the catalog; its
adapter call-shape coverage below stays network-free.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import get_catalog_by_id
from app.pilot.kilo_provider import (
    KILO_LING_MODEL_ID,
    KILO_PROVIDER_ID,
    KILO_SPACE_BUNNY_CREDENTIAL_BINDING,
    KILO_SPACE_BUNNY_MODEL_ID,
    KILO_SPACE_BUNNY_UPSTREAM_MODEL,
)
from app.pilot.router_core import resolve_manual_route

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_PATH = (
    REPO_ROOT
    / "packages"
    / "padiem-ai-core"
    / "padiem_ai_core"
    / "model_primary.py"
)

# Minimal valid PNG bytes (header + payload); the adapter passes messages
# through, so the shape — not the pixels — is what this contract proves.
_TINY_PNG = b"\x89PNG\r\n\x1a\n3209-vision-source"
_TINY_PNG_URL = (
    "data:image/png;base64," + base64.b64encode(_TINY_PNG).decode("ascii")
)


def test_ling_is_text_primary_and_space_bunny_is_unregistered() -> None:
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    assert (
        'TEXT_PRIMARY_DECISION = "Owner successor selection 2026-10-06 (Ling 3.1 Flash, Kilo gateway)"'
        in text
    )
    assert 'TEXT_PRIMARY_PROVIDER_ID = "kilo"' in text
    assert 'TEXT_PRIMARY_MODEL_ID = "kilo/inclusionai-ling-3.1-flash"' in text
    assert 'TEXT_PRIMARY_UPSTREAM_MODEL = "inclusionai/ling-3.1-flash"' in text
    assert 'VISION_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"' in text
    assert "VISION_PRIMARY_MODEL_ID = None" in text
    assert "VISION_PRIMARY_UPSTREAM_MODEL = None" in text
    assert "TEXT_SECONDARY_MODEL_ID = None" in text
    assert "TEXT_FALLBACK_ENABLED = False" in text

    # The ended Space Bunny lane keeps its constants as retirement metadata
    # but is no longer registered in the catalog (#3579 policy v2).
    assert get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID) is None


def test_ling_declares_no_image_capability() -> None:
    model = get_catalog_by_id(KILO_LING_MODEL_ID)
    assert model is not None
    assert {"chat", "free"}.issubset(model.capabilities)
    assert model.capabilities & frozenset(
        {"image", "video", "audio", "multimodal", "vision"}
    ) == frozenset()


def test_ling_manual_route_is_explicit_and_fallback_free() -> None:
    decision = resolve_manual_route(KILO_LING_MODEL_ID)
    assert decision.selected_model == KILO_LING_MODEL_ID
    assert decision.selected_upstream_model == "inclusionai/ling-3.1-flash"
    assert decision.platform_provider_id == KILO_PROVIDER_ID
    assert decision.fallback_allowed is False
    assert decision.eligible_fallback == []
    assert decision.max_attempts == 1


def test_other_provider_registrations_are_preserved_but_not_secondary() -> None:
    for model_id, provider_id in (
        ("sensenova/sensenova-6.8-flash-lite", "sensenova"),
        ("agnes-ai/agnes-3.0-flash", "agnes-ai"),
        ("poolside/laguna-s-2.1", "poolside"),
    ):
        model = get_catalog_by_id(model_id)
        assert model is not None, f"{model_id} provider registration was deleted"
        assert model.platform_provider_id == provider_id
        # None of them is the Space Bunny primary lane.
        assert model.model_id != KILO_SPACE_BUNNY_MODEL_ID

    sensenova = get_catalog_by_id("sensenova/sensenova-6.8-flash-lite")
    assert sensenova is not None
    # SenseNova stays a chat/coding lane only; it is not an active product
    # secondary and carries no image capability from this change.
    assert "image" not in sensenova.capabilities


@pytest.mark.asyncio
async def test_space_bunny_image_payload_reaches_kilo_adapter_with_optional_secret(
    monkeypatch,
) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(
        KILO_SPACE_BUNNY_CREDENTIAL_BINDING,
        "kilo_dummy_binding_value",
    )
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "space-bunny-vision-1",
                "model": KILO_SPACE_BUNNY_UPSTREAM_MODEL,
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "이미지 확인됨"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "이 영수증 금액을 읽어줘"},
                {"type": "image_url", "image_url": {"url": _TINY_PNG_URL}},
            ],
        }
    ]

    response = await plat.call_platform_chat_completions(
        model_id=KILO_SPACE_BUNNY_MODEL_ID,
        upstream_model=KILO_SPACE_BUNNY_UPSTREAM_MODEL,
        provider="Kilo Gateway / Stealth",
        platform_provider_id=KILO_PROVIDER_ID,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=None,
        transport=httpx.MockTransport(handler),
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "stealth/space-bunny-alpha"
    assert body["messages"][0]["content"] == [
        {"type": "text", "text": "이 영수증 금액을 읽어줘"},
        {"type": "image_url", "image_url": {"url": _TINY_PNG_URL}},
    ]
    assert captured["auth"] == "Bearer kilo_dummy_binding_value"
    assert response["choices"][0]["message"]["content"] == "이미지 확인됨"

    spec = ps.get_platform_provider(KILO_PROVIDER_ID)
    assert spec is not None
    assert spec.credential_source == ps.CredentialSource.NONE
    # Policy v2: while the shared binding resolves it authenticates every
    # Kilo lane, including the model-less header build.
    bound = plat._request_headers(spec)
    assert bound["Authorization"] == "Bearer kilo_dummy_binding_value"
    headers = plat._request_headers(spec, model_id=KILO_SPACE_BUNNY_MODEL_ID)
    assert headers["Authorization"] == "Bearer kilo_dummy_binding_value"

    monkeypatch.delenv(KILO_SPACE_BUNNY_CREDENTIAL_BINDING, raising=False)
    anonymous_headers = plat._request_headers(
        spec, model_id=KILO_SPACE_BUNNY_MODEL_ID
    )
    assert anonymous_headers == {"Content-Type": "application/json"}
