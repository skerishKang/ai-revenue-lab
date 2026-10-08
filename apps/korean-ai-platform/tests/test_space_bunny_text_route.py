"""Retirement contract for the historical Space Bunny B14 lane (LOCAL4 final).

Owner final decision (2026-10-07): the Space Bunny lane executes nowhere —
no product execution, no manual execution, no auto route, no fallback. These
tests pin that end state without any live provider call:

- the historical identity constants survive as metadata only;
- the lane is absent from KILO_FREE_ROUTES, from the catalog, and from the
  fixed b14/auto chain, and is declared in RETIRED_KILO_FREE_MODEL_IDS;
- manual resolution fails closed (model_not_in_catalog);
- the model-scoped auth special-case is gone from the platform adapter;
- the global b14/auto chain and its fallback set stay unchanged;
- Business 66 browser sources still carry no model/provider identity.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import CATALOG_MODELS, get_catalog_by_id
from app.pilot.kilo_provider import (
    KILO_FREE_ROUTES,
    KILO_HY3_MODEL_ID,
    KILO_LAGUNA_MODEL_ID,
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_NEMOTRON_MODEL_ID,
    KILO_SPACE_BUNNY_CREDENTIAL_BINDING,
    KILO_SPACE_BUNNY_MODEL_ID,
    KILO_SPACE_BUNNY_SOURCE_CHECKED_AT,
    KILO_SPACE_BUNNY_UPSTREAM_MODEL,
    RETIRED_KILO_FREE_MODEL_IDS,
)
from app.pilot.routing_policy import B14_AUTO_CHAIN
from app.pilot.router_core import resolve_auto_route, resolve_manual_route

B66_BROWSER_DIR = (
    Path(__file__).resolve().parents[3]
    / "reference"
    / "business-66-padiem-quote-v1"
)

# Business 66 browser code must never learn which model or provider runs the
# extraction. These are the exact strings this change introduces.
FORBIDDEN_BROWSER_TOKENS = (
    "stealth/space-bunny-alpha",
    "kilo/stealth-space-bunny-alpha",
    "space-bunny",
    "KILO_PROVIDER_ID",
    "platform_provider_id",
)


def _browser_sources() -> list[Path]:
    return sorted(
        path
        for path in B66_BROWSER_DIR.iterdir()
        if path.is_file() and path.suffix in {".js", ".html", ".css"}
    )


def test_space_bunny_identity_survives_only_as_historical_metadata() -> None:
    # Historical constants are preserved for audit/evidence purposes.
    assert KILO_SPACE_BUNNY_MODEL_ID == "kilo/stealth-space-bunny-alpha"
    assert KILO_SPACE_BUNNY_UPSTREAM_MODEL == "stealth/space-bunny-alpha"
    assert KILO_SPACE_BUNNY_SOURCE_CHECKED_AT == "2026-09-28"
    assert KILO_SPACE_BUNNY_CREDENTIAL_BINDING == "PADIEM_KILO_API_KEY"


def test_space_bunny_is_absent_from_routes_catalog_and_chain() -> None:
    route_ids = {route.model_id for route in KILO_FREE_ROUTES}
    assert KILO_SPACE_BUNNY_MODEL_ID not in route_ids
    assert get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID) is None
    assert KILO_SPACE_BUNNY_MODEL_ID not in B14_AUTO_CHAIN
    assert KILO_SPACE_BUNNY_MODEL_ID not in {m.model_id for m in CATALOG_MODELS}


def test_space_bunny_is_declared_in_the_retired_set() -> None:
    assert KILO_SPACE_BUNNY_MODEL_ID in RETIRED_KILO_FREE_MODEL_IDS
    # The previously retired lanes stay retired alongside it.
    assert {KILO_MINIMAX_M3_MODEL_ID, KILO_HY3_MODEL_ID} <= RETIRED_KILO_FREE_MODEL_IDS


def test_space_bunny_manual_resolution_fails_closed() -> None:
    # SPACE_BUNNY_MANUAL_RESOLVE=FAIL_CLOSED: the retired lane is not in the
    # catalog, so explicit resolution raises NoSafeRoute before any upstream
    # call and never falls back.
    from app.pilot.errors import NoSafeRoute

    with pytest.raises(NoSafeRoute) as info:
        resolve_manual_route(KILO_SPACE_BUNNY_MODEL_ID)
    assert info.value.reason_code == "model_not_in_catalog"
    assert info.value.upstream_called is False


def test_space_bunny_absent_from_auto_chain_and_fallback() -> None:
    from app.pilot.errors import NoSafeRoute
    assert KILO_SPACE_BUNNY_MODEL_ID not in B14_AUTO_CHAIN
    with pytest.raises(NoSafeRoute) as exc:
        resolve_auto_route(task_type="general",required_capabilities=["free"],
                           optimize_for="balanced",allow_external_fallback=True,max_attempts=3)
    assert exc.value.upstream_called is False

def test_platform_adapter_has_no_space_bunny_auth_special_case() -> None:
    import inspect
    assert "KILO_SPACE_BUNNY" not in inspect.getsource(plat._request_headers)
    assert get_catalog_by_id("kilo/stepfun/step-5-preview-free") is not None
    assert get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID) is None

def test_owner_removed_all_remaining_kilo_free_routes() -> None:
    assert KILO_FREE_ROUTES == ()
    for mid in (KILO_NEMOTRON_MODEL_ID,KILO_LAGUNA_MODEL_ID,
                KILO_HY3_MODEL_ID,KILO_MINIMAX_M3_MODEL_ID):
        assert get_catalog_by_id(mid) is None
    assert get_catalog_by_id("kilo/stepfun/step-5-preview-free") is not None

def test_business_66_browser_sources_carry_no_model_or_provider_identity() -> None:
    sources = _browser_sources()
    assert sources, f"no Business 66 browser sources found under {B66_BROWSER_DIR}"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_BROWSER_TOKENS:
            assert token not in text, f"{token!r} leaked into {path.name}"
