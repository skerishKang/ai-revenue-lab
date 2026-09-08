"""#2094: retired Kilo free lanes must never appear in executable route lanes.

The public Gateway model list re-checked on 2026-09-08 no longer offers
``minimax/minimax-m3:free`` or ``tencent/hy3:free``. These tests pin the
retirement contract inside the B14 catalog registration itself.
"""

from __future__ import annotations

from app.pilot.catalog import get_catalog_by_id, get_catalog_models
from app.pilot.kilo_provider import (
    KILO_HY3_MODEL_ID,
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_NEMOTRON_MODEL_ID,
    RETIRED_KILO_FREE_MODEL_IDS,
)


def test_retired_free_ids_are_declared() -> None:
    assert RETIRED_KILO_FREE_MODEL_IDS == frozenset(
        {KILO_MINIMAX_M3_MODEL_ID, KILO_HY3_MODEL_ID}
    )


def test_retired_free_ids_are_absent_from_public_auto_lane() -> None:
    public_ids = {model.model_id for model in get_catalog_models()}
    for retired_id in RETIRED_KILO_FREE_MODEL_IDS:
        assert retired_id not in public_ids


def test_retired_free_ids_are_explicit_only_and_never_auto_eligible() -> None:
    for retired_id in RETIRED_KILO_FREE_MODEL_IDS:
        model = get_catalog_by_id(retired_id)
        assert model is not None
        assert model.model_id not in {m.model_id for m in get_catalog_models()}


def test_live_kilo_free_default_route_stays_registered_with_zero_price() -> None:
    model = get_catalog_by_id(KILO_NEMOTRON_MODEL_ID)
    assert model is not None
    assert model.upstream_model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert model.input_price_usd_per_1m == 0.0
    assert model.output_price_usd_per_1m == 0.0
    assert "free" in model.capabilities
    assert "chat" in model.capabilities
