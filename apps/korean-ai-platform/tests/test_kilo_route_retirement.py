"""#2094/#2097 + LOCAL4: retired Kilo free lanes must be absent from every executable route lane.

The public Gateway model list re-checked on 2026-09-08 no longer offers
``minimax/minimax-m3:free`` or ``tencent/hy3:free``. #2097 unregistered both
from the catalog and removed the minimax position from fixed_chain_v1, so
explicit resolution fails closed with ``unsupported_model`` /
``model_not_in_catalog``. The owner final retirement decision (2026-10-07)
adds the Space Bunny lane to the same retired set: it executes nowhere.
"""

from __future__ import annotations

from app.pilot.catalog import get_catalog_by_id, get_catalog_models
from app.pilot.kilo_provider import (
    KILO_HY3_MODEL_ID,
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_NEMOTRON_MODEL_ID,
    KILO_LAGUNA_MODEL_ID,
    KILO_SPACE_BUNNY_MODEL_ID,
    RETIRED_KILO_FREE_MODEL_IDS,
)
from app.pilot.routing_policy import B14_AUTO_CHAIN


def test_retired_free_ids_are_declared() -> None:
    assert RETIRED_KILO_FREE_MODEL_IDS == frozenset(
        {KILO_MINIMAX_M3_MODEL_ID, KILO_HY3_MODEL_ID, KILO_SPACE_BUNNY_MODEL_ID}
    )


def test_retired_free_ids_are_unregistered_from_the_catalog() -> None:
    public_ids = {model.model_id for model in get_catalog_models()}
    for retired_id in RETIRED_KILO_FREE_MODEL_IDS:
        assert retired_id not in public_ids
        assert get_catalog_by_id(retired_id) is None


def test_retired_free_ids_are_absent_from_fixed_chain_v1() -> None:
    for retired_id in RETIRED_KILO_FREE_MODEL_IDS:
        assert retired_id not in B14_AUTO_CHAIN


def test_owner_removed_remaining_kilo_free_routes_from_catalog() -> None:
    from app.pilot.platform_secrets import get_platform_provider
    assert get_platform_provider("kilo") is None
    for model_id in (KILO_NEMOTRON_MODEL_ID,KILO_LAGUNA_MODEL_ID):
        assert get_catalog_by_id(model_id) is None
        assert model_id not in {m.model_id for m in get_catalog_models()}
