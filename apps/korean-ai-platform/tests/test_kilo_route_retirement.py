"""#2094/#2097 + LOCAL4: retired Kilo free lanes must be absent from every executable route lane.

The public Gateway model list re-checked on 2026-09-08 no longer offers
``minimax/minimax-m3:free`` or ``tencent/hy3:free``. #2097 unregistered both
from the catalog and removed the minimax position from fixed_chain_v1, so
explicit resolution fails closed with ``unsupported_model`` /
``model_not_in_catalog``. The owner final retirement decision (2026-10-07)
adds the Space Bunny lane to the same retired set: it executes nowhere.
"""

from __future__ import annotations

import pytest

from app.pilot.catalog import get_catalog_by_id, get_catalog_models
from app.pilot.platform_secrets import get_platform_provider

from _registry_values import (
    adapter_declaring_retired, registered_model_id_within,
)


# The retirement roster and the identities the owning adapter retains are its
# own constants; the adapter is selected by that metadata, not by name (#7241).
_OWNER_PROVIDER, _OWNER_ADAPTER, _RETIRED_OR_RETAINED = adapter_declaring_retired("RETIRED")
_RETIRED = next(
    value for name, value in vars(_OWNER_ADAPTER).items()
    if isinstance(value, frozenset) and "RETIRED" in name
)


def test_retired_free_ids_are_declared() -> None:
    assert _RETIRED, "the owning adapter declares no retired roster"
    assert _RETIRED <= _RETIRED_OR_RETAINED


def test_retired_free_ids_are_unregistered_from_the_catalog() -> None:
    public_ids = {model.model_id for model in get_catalog_models()}
    for retired_id in _RETIRED:
        assert retired_id not in public_ids
        assert get_catalog_by_id(retired_id) is None


def test_retired_free_ids_cannot_return_via_a_fixed_chain() -> None:
    # B7: the fixed chain (fixed_chain_v1) is retired entirely, so no retired
    # id can rejoin an executable auto lane.
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.pilot.routing_policy")


def test_owner_removed_remaining_kilo_free_routes_from_catalog() -> None:
    assert get_platform_provider(_OWNER_PROVIDER) is not None
    # The identity the effective document still registers for this Provider is a
    # live catalog row and is not one the adapter retired. The document supplies
    # the identity, so no route is written here (#7241 3a).
    registered = registered_model_id_within(_OWNER_PROVIDER)
    assert registered not in _RETIRED
    assert get_catalog_by_id(registered) is not None
    # Every retired identity the adapter retains stays unregistered, and the
    # effective document registers none of them.
    for model_id in sorted(_RETIRED):
        assert get_catalog_by_id(model_id) is None
        assert model_id not in {m.model_id for m in get_catalog_models()}
