"""#1442 MiniMax M3 free candidate contract — RETIRED by #2094/#2097.

The lane stayed registered after #2096 only because fixed_chain_v1 pinned it;
#2097 refreshed the chain and unregistered the lane. These tests pin the
fail-closed retirement behavior for both retired Kilo free lanes. The
keyless-platform boundary test moved to the live Laguna free lane.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import NoSafeRoute
from app.pilot.kilo_provider import (
    KILO_BASE_ORIGIN,
    KILO_HY3_MODEL_ID,
    KILO_LAGUNA_MODEL_ID,
    KILO_LAGUNA_UPSTREAM_MODEL,
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_MINIMAX_M3_UPSTREAM_MODEL,
)
from app.pilot.router_core import resolve_auto_route, resolve_manual_route

RETIRED_LANES = (
    (KILO_MINIMAX_M3_MODEL_ID, KILO_MINIMAX_M3_UPSTREAM_MODEL),
    (KILO_HY3_MODEL_ID, "tencent/hy3:free"),
)


@pytest.mark.parametrize(("model_id", "upstream_model"), RETIRED_LANES)
def test_retired_lane_is_unregistered_from_the_catalog(
    model_id: str,
    upstream_model: str,
) -> None:
    assert get_catalog_by_id(model_id) is None


@pytest.mark.parametrize(("model_id", "upstream_model"), RETIRED_LANES)
def test_retired_lane_manual_resolve_fails_closed(
    model_id: str,
    upstream_model: str,
) -> None:
    with pytest.raises(NoSafeRoute) as exc_info:
        resolve_manual_route(model_id)
    assert exc_info.value.reason_code == "model_not_in_catalog"


def test_retired_lane_is_never_in_b14_auto_pool() -> None:
    auto = resolve_auto_route(
        task_type="general",
        required_capabilities=["chat"],
        optimize_for="balanced",
        allow_external_fallback=True,
    )
    auto_pool = {auto.selected_model, *(item["model_id"] for item in auto.eligible_fallback)}
    for model_id, _ in RETIRED_LANES:
        assert model_id not in auto_pool


@pytest.mark.asyncio
async def test_laguna_free_lane_uses_fixed_keyless_kilo_boundary(monkeypatch) -> None:
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "laguna-free-boundary-test",
                "model": KILO_LAGUNA_UPSTREAM_MODEL,
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "경계 테스트 응답"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    response = await plat.call_platform_chat_completions(
        model_id=KILO_LAGUNA_MODEL_ID,
        upstream_model=KILO_LAGUNA_UPSTREAM_MODEL,
        provider="Kilo Gateway / Poolside",
        platform_provider_id="kilo",
        messages=[{"role": "user", "content": "합성 테스트"}],
        max_tokens=None,
        transport=httpx.MockTransport(handler),
    )

    assert captured["url"] == f"{KILO_BASE_ORIGIN}/chat/completions"
    assert captured["authorization"] is None
    assert captured["body"]["model"] == KILO_LAGUNA_UPSTREAM_MODEL
    assert response["model"] == KILO_LAGUNA_UPSTREAM_MODEL
    assert response["choices"][0]["message"]["content"] == "경계 테스트 응답"
