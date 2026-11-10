"""Retirement contract for the historical Space Bunny B14 lane (LOCAL4 final).

Owner final decision (2026-10-07): the Space Bunny lane executes nowhere —
no product execution, no manual execution, no auto route, no fallback. These
tests pin that end state without any live provider call:

- the historical identity constants survive as metadata only;
- the lane is absent from the Provider's free routes and from the catalog, and
  is declared in that Provider's retired roster;
- manual resolution fails closed (model_not_in_catalog);
- the model-scoped auth special-case is gone from the platform adapter;
- the retired automatic chain stays absent;
- Business 66 browser sources still carry no model/provider identity.

#7241 3단계: the retirement roster, the Provider that owns it and the identities
it no longer serves are read from the app's own adapter metadata, so no model,
Provider or host value is written in this file. The identity constants and the
served-lane assertions are owner pins and skip on a placeholder document.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import CATALOG_MODELS, get_catalog_by_id
from app.pilot.router_core import resolve_manual_route

from _registry_values import (
    a_dispatchable_row,
    adapter_declaring_retired,
    requires_owner_document,
)

#: The adapter that owns the retirement roster for this Provider family, and
#: every identity that roster no longer serves. Both are read from the app, so
#: neither the adapter nor its model ids are written here (#7241 3a).
RETIRED_PROVIDER_ID, RETIRED_ADAPTER, ROSTER_IDS = adapter_declaring_retired()
#: The roster the adapter declares as retired, as distinct from the identities
#: its own constants still retain for historical metadata.
DECLARED_RETIRED_IDS = frozenset(
    item
    for name, value in vars(RETIRED_ADAPTER).items()
    if isinstance(value, frozenset) and "RETIRED" in name
    for item in value
)
#: The lanes this contract pins at the end state: every identity the adapter
#: no longer serves, declared or merely retained as evidence metadata.
RETIRED_LANES = sorted(ROSTER_IDS)

#: A live identity the same Provider still serves: the lane's absence from the
#: catalog above is a retirement fact, not an empty catalog.
LIVE_ROW = a_dispatchable_row(provider_ids=frozenset({RETIRED_PROVIDER_ID}))

#: The Provider's own free-route table, addressed by the id the adapter declares.
FREE_ROUTES = getattr(RETIRED_ADAPTER, RETIRED_PROVIDER_ID.upper() + "_FREE_ROUTES", ())


def _require_served_provider() -> None:
    """Skip when the effective document no longer registers this Provider.

    The retirement contract also pins the Provider's *remaining* state (its
    platform row exists and one live identity is still installed). That is the
    owner document's fact; a placeholder document registers neither, so those
    two assertions skip rather than fail on an absent lane (#7241 3b).
    """
    if ps.get_platform_provider(RETIRED_PROVIDER_ID) is None or LIVE_ROW is None:
        pytest.skip(
            "the effective registry registers no served lane for this Provider "
            "(placeholder fixture)"
        )

B66_BROWSER_DIR = (
    Path(__file__).resolve().parents[3]
    / "reference"
    / "business-66-padiem-quote-v1"
)

# Business 66 browser code must never learn which model or provider runs the
# extraction. The forbidden names are the retired identities plus the field
# names this change introduces, assembled from the app's own metadata so the
# file carries no deployment value (#7241 3a).
_HEAD = RETIRED_PROVIDER_ID + "/"
FORBIDDEN_BROWSER_TOKENS = tuple(
    sorted(
        {
            *(identity for identity in ROSTER_IDS if identity.startswith(_HEAD)),
            *(identity.split("/", 1)[1] for identity in ROSTER_IDS
              if identity.startswith(_HEAD)),
            RETIRED_PROVIDER_ID.upper() + "_PROVIDER_ID",
            "platform_provider_id",
        }
    )
)


def _browser_sources() -> list[Path]:
    return sorted(
        path
        for path in B66_BROWSER_DIR.iterdir()
        if path.is_file() and path.suffix in {".js", ".html", ".css"}
    )


@requires_owner_document
def test_retired_identity_survives_only_as_historical_metadata() -> None:
    # The historical identity is preserved for audit/evidence purposes.
    assert all(isinstance(identity, str) and identity for identity in RETIRED_LANES)
    _require_served_provider()
    assert LIVE_ROW["id"] not in ROSTER_IDS


def test_retired_lane_is_absent_from_routes_and_catalog() -> None:
    # No adapter metadata, no provider call: this holds on any document.
    route_ids = {route.model_id for route in FREE_ROUTES}
    catalog_ids = {model.model_id for model in CATALOG_MODELS}
    for model_id in RETIRED_LANES:
        assert model_id not in route_ids
        assert model_id not in catalog_ids
        assert get_catalog_by_id(model_id) is None


def test_retired_lane_is_declared_in_the_retired_set() -> None:
    assert DECLARED_RETIRED_IDS
    assert DECLARED_RETIRED_IDS <= set(RETIRED_LANES)
    # A retained identity is either declared retired or still absent from the
    # catalog; nothing on the roster is an executable lane.
    for model_id in RETIRED_LANES:
        assert model_id in DECLARED_RETIRED_IDS or get_catalog_by_id(model_id) is None


@pytest.mark.parametrize("lane_index", range(3))
def test_retired_lane_manual_resolution_fails_closed(lane_index) -> None:
    # SPACE_BUNNY_MANUAL_RESOLVE=FAIL_CLOSED: the retired lane is not in the
    # catalog, so explicit resolution raises NoSafeRoute before any upstream
    # call and never falls back.
    from app.pilot.errors import NoSafeRoute

    lanes = RETIRED_LANES[:3]
    if lane_index >= len(lanes):
        pytest.skip("the retirement roster carries fewer lanes than this pin")
    with pytest.raises(NoSafeRoute) as info:
        resolve_manual_route(lanes[lane_index])
    assert info.value.reason_code == "model_not_in_catalog"
    assert info.value.upstream_called is False


def test_retired_lane_cannot_return_via_an_auto_chain() -> None:
    # B7: the fixed chain is retired entirely, so the retired lane cannot
    # rejoin an executable auto route.
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.pilot.routing_policy")


@requires_owner_document
def test_platform_adapter_has_no_retired_lane_auth_special_case() -> None:
    import inspect

    source = inspect.getsource(plat._request_headers)
    # The retired lane's own family marker (its identity is derived from the
    # roster the adapter still carries, so the marker is not written here).
    marker = RETIRED_LANES[0].split("/", 1)[1].split("-")[0].upper()
    for constant in (marker, marker.replace("_", "-")):
        assert constant not in source
    _require_served_provider()
    assert get_catalog_by_id(LIVE_ROW["id"]) is not None
    for model_id in RETIRED_LANES:
        assert get_catalog_by_id(model_id) is None


@requires_owner_document
def test_owner_removed_all_remaining_free_routes() -> None:
    assert FREE_ROUTES == ()
    for model_id in RETIRED_LANES:
        assert get_catalog_by_id(model_id) is None
    _require_served_provider()
    assert get_catalog_by_id(LIVE_ROW["id"]) is not None


def test_business_66_browser_sources_carry_no_model_or_provider_identity() -> None:
    sources = _browser_sources()
    assert sources, f"no Business 66 browser sources found under {B66_BROWSER_DIR}"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_BROWSER_TOKENS:
            assert token not in text, f"{token!r} leaked into {path.name}"
