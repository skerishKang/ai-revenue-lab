"""#1442 MiniMax M3 free candidate contract — RETIRED by #2094/#2097.

The lane stayed registered after #2096 only because fixed_chain_v1 pinned it;
#2097 refreshed the chain and unregistered the lane. These tests pin the
fail-closed retirement behavior for both retired Kilo free lanes. The
keyless-platform boundary is exercised using a synthetic route, never
with the OWNER-excluded Kilo Laguna model.
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
    from app.pilot.catalog import CATALOG_MODELS, CATALOG_BY_ID
    assert not CATALOG_MODELS
    for model_id, _ in RETIRED_LANES:
        assert model_id not in CATALOG_BY_ID
    with pytest.raises(NoSafeRoute) as exc:
        resolve_auto_route(task_type="general",required_capabilities=["free"],
                           optimize_for="balanced",allow_external_fallback=True)
    assert exc.value.upstream_called is False

@pytest.mark.asyncio
async def test_retired_kilo_laguna_never_calls_transport(monkeypatch) -> None:
    from app.pilot.errors import PilotNotConfigured
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    called=[]
    def handler(request):
        called.append(request)
        raise AssertionError("retired provider must not dispatch")
    with pytest.raises(PilotNotConfigured):
        await plat.call_platform_chat_completions(
            model_id="test-fixture/kilo-keyless-chat",
            upstream_model="test-fixture/kilo-keyless-response",
            provider="Kilo Gateway / Poolside",
            platform_provider_id="kilo",
            messages=[{"role":"user","content":"fixture"}],
            transport=httpx.MockTransport(handler))
    assert not called
