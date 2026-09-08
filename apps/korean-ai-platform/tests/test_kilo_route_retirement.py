"""#2094/#2097: retired Kilo free lanes must be absent from every executable route lane.

The public Gateway model list re-checked on 2026-09-08 no longer offers
``minimax/minimax-m3:free`` or ``tencent/hy3:free``. #2097 unregistered both
from the catalog and removed the minimax position from fixed_chain_v1, so
explicit resolution fails closed with ``unsupported_model`` /
``model_not_in_catalog``.
"""

from __future__ import annotations

from app.pilot.catalog import get_catalog_by_id, get_catalog_models
from app.pilot.kilo_provider import (
    KILO_HY3_MODEL_ID,
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_NEMOTRON_MODEL_ID,
    KILO_LAGUNA_MODEL_ID,
    RETIRED_KILO_FREE_MODEL_IDS,
)
from app.pilot.routing_policy import B14_AUTO_CHAIN


def test_retired_free_ids_are_declared() -> None:
    assert RETIRED_KILO_FREE_MODEL_IDS == frozenset(
        {KILO_MINIMAX_M3_MODEL_ID, KILO_HY3_MODEL_ID}
    )


def test_retired_free_ids_are_unregistered_from_the_catalog() -> None:
    public_ids = {model.model_id for model in get_catalog_models()}
    for retired_id in RETIRED_KILO_FREE_MODEL_IDS:
        assert retired_id not in public_ids
        assert get_catalog_by_id(retired_id) is None


def test_retired_free_ids_are_absent_from_fixed_chain_v1() -> None:
    for retired_id in RETIRED_KILO_FREE_MODEL_IDS:
        assert retired_id not in B14_AUTO_CHAIN


def test_live_kilo_free_routes_stay_registered_with_zero_price() -> None:
    for model_id, upstream_model in (
        (KILO_NEMOTRON_MODEL_ID, "nvidia/nemotron-3-ultra-550b-a55b:free"),
        (KILO_LAGUNA_MODEL_ID, "poolside/laguna-s-2.1:free"),
    ):
        model = get_catalog_by_id(model_id)
        assert model is not None
        assert model.upstream_model == upstream_model
        assert model.input_price_usd_per_1m == 0.0
        assert model.output_price_usd_per_1m == 0.0
        assert "free" in model.capabilities
        assert "chat" in model.capabilities
