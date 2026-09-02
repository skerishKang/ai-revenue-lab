"""Network-free contract for B14 MiniMax M3 free candidate (#1442)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.catalog import get_catalog_by_id
from app.pilot.kilo_provider import (
    KILO_BASE_ORIGIN,
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_MINIMAX_M3_UPSTREAM_MODEL,
)
from app.pilot.router_core import resolve_auto_route, resolve_manual_route


def test_minimax_m3_candidate_is_registered_as_explicit_free_route() -> None:
    model = get_catalog_by_id(KILO_MINIMAX_M3_MODEL_ID)
    assert model is not None
    assert model.upstream_model == KILO_MINIMAX_M3_UPSTREAM_MODEL
    assert model.provider == "Kilo Gateway / MiniMax"
    assert model.input_price_usd_per_1m == 0.0
    assert model.output_price_usd_per_1m == 0.0
    assert model.context_window == 1_048_576
    assert "chat" in model.capabilities
    assert "free" in model.capabilities
    assert model.platform_provider_id == "kilo"
    assert model.source_checked_at == "2026-09-02"


def test_minimax_m3_candidate_is_manual_only_and_never_in_b14_auto() -> None:
    manual = resolve_manual_route(KILO_MINIMAX_M3_MODEL_ID)
    assert manual.selected_model == KILO_MINIMAX_M3_MODEL_ID
    assert manual.selected_upstream_model == KILO_MINIMAX_M3_UPSTREAM_MODEL
    assert manual.selected_provider == "Kilo Gateway / MiniMax"
    assert manual.platform_provider_id == "kilo"
    assert manual.credential_available is True
    assert manual.max_attempts == 1
    assert manual.fallback_allowed is False

    auto = resolve_auto_route(
        task_type="general",
        required_capabilities=["chat"],
        optimize_for="balanced",
        allow_external_fallback=True,
    )
    auto_pool = {auto.selected_model, *(item["model_id"] for item in auto.eligible_fallback)}
    assert KILO_MINIMAX_M3_MODEL_ID not in auto_pool


@pytest.mark.asyncio
async def test_minimax_m3_candidate_uses_fixed_keyless_kilo_boundary(monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "minimax-m3-candidate-test",
                "model": KILO_MINIMAX_M3_UPSTREAM_MODEL,
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "후보 테스트 응답"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    response = await plat.call_platform_chat_completions(
        model_id=KILO_MINIMAX_M3_MODEL_ID,
        upstream_model=KILO_MINIMAX_M3_UPSTREAM_MODEL,
        provider="Kilo Gateway / MiniMax",
        platform_provider_id="kilo",
        messages=[{"role": "user", "content": "합성 테스트"}],
        max_tokens=None,
        transport=httpx.MockTransport(handler),
    )

    assert captured["url"] == f"{KILO_BASE_ORIGIN}/chat/completions"
    assert captured["authorization"] is None
    assert captured["body"]["model"] == KILO_MINIMAX_M3_UPSTREAM_MODEL
    assert response["model"] == KILO_MINIMAX_M3_UPSTREAM_MODEL
    assert response["choices"][0]["message"]["content"] == "후보 테스트 응답"
