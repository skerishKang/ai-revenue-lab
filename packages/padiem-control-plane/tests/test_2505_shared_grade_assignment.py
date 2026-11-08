"""#2505 stage 1: one shared Chat/Claw grade assignment, no free candidate.

The owner decision (2026-10-21) makes Chat and Claw two screens of one AI
product, so the Free/Plus/Pro/Max assignment they read and update is one
shared setting. The same decision keeps OpenCode Go free models out of the
execution candidates.

These are contract tests: no provider call, no D1 and no deployment.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.model_assignment_policy import (
    CatalogModel,
    canonical_product,
    product_scope_set,
)
from padiem_control_plane.model_tier_routes import (
    TierRoute,
    TierRouteChange,
    TierRouteSnapshot,
    _check_route_changes,
    _updated_routes,
    effective_tier_route,
    project_shared_routes,
    static_tier_route,
)
from padiem_control_plane.product_tier_routes import ProductTierLabel
from padiem_control_plane.product_tier_routes_private import (
    effective_is_free_execution_candidate,
)
from padiem_control_plane.product_tier_routes_private import (
    effective_active_route_for,
    tier_fallback_rosters,
)

SHARED = "google/shared-grade-model"
SHARED_FALLBACK = "google/shared-grade-fallback"
LEGACY = "google/legacy-claw-model"
FREE_CANDIDATE = "example-candidates/example-model-free"
CATALOG = {
    model_id: CatalogModel(model_id, True, True, True, True, frozenset({"chat"}))
    for model_id in (SHARED, SHARED_FALLBACK, LEGACY, "google/other-grade-model")
}
TIERS = ("FREE", "PLUS", "PRO", "MAX")


def _resolution(snapshot, tier, product):
    return effective_tier_route(
        snapshot, workspace_id="padiem-global", product=product, tier=tier,
        static_primary="google/other-grade-model",
    )


def test_the_chat_and_claw_surfaces_share_one_grade_setting_for_every_tier():
    for tier in TIERS:
        snapshot = TierRouteSnapshot("padiem-global", 1, (
            TierRoute("chat", tier, SHARED, SHARED_FALLBACK, True),
        ))
        chat = _resolution(snapshot, tier, "chat")
        claw = _resolution(snapshot, tier, "claw")
        assert (chat.ok, chat.model_id, chat.fallback_model_id, chat.source) == (
            True, SHARED, SHARED_FALLBACK, "central",
        )
        assert (claw.ok, claw.model_id, claw.fallback_model_id, claw.source) == (
            True, SHARED, SHARED_FALLBACK, "central",
        )


def test_an_administrator_write_on_either_screen_updates_the_one_shared_setting():
    empty = TierRouteSnapshot("padiem-global", 0, ())
    written = _updated_routes(
        empty, (TierRouteChange("claw", "FREE", "set", SHARED, SHARED_FALLBACK, True),),
    )
    assert [row.key for row in written.routes] == [("chat", "FREE")]
    for product in ("chat", "claw"):
        resolution = _resolution(written, "FREE", product)
        assert (resolution.ok, resolution.model_id, resolution.source) == (
            True, SHARED, "central",
        )


def test_a_legacy_alias_row_governs_until_the_shared_row_is_written():
    legacy = TierRouteSnapshot("padiem-global", 1, (
        TierRoute("claw", "FREE", LEGACY, None, True),
    ))
    for product in ("chat", "claw"):
        resolution = _resolution(legacy, "FREE", product)
        assert (resolution.ok, resolution.model_id) == (True, LEGACY)

    shared = _updated_routes(
        legacy, (TierRouteChange("chat", "FREE", "set", SHARED, None, True),),
    )
    assert [row.key for row in shared.routes] == [("chat", "FREE")]
    for product in ("chat", "claw"):
        resolution = _resolution(shared, "FREE", product)
        assert (resolution.ok, resolution.model_id) == (True, SHARED)


def test_the_admin_view_reports_one_shared_row_and_keeps_b66_its_own():
    snapshot = TierRouteSnapshot("padiem-global", 2, (
        TierRoute("chat", "FREE", SHARED, None, True),
        TierRoute("claw", "PLUS", LEGACY, None, True),
        TierRoute("b66", "FREE", "google/b66-model", None, True),
    ))
    projected = project_shared_routes(snapshot)
    assert [row.key for row in projected] == [
        ("b66", "FREE"), ("chat", "FREE"), ("chat", "PLUS"),
    ]


def test_a_shared_product_decision_never_covers_another_product():
    assert canonical_product("claw") == canonical_product("chat") == "chat"
    assert product_scope_set("claw") == product_scope_set("chat") == {"chat", "claw"}
    assert product_scope_set("b66") == {"b66"}


def test_a_free_candidate_can_never_be_bound_to_a_grade(monkeypatch):
    monkeypatch.setenv("PADIEM_B14_FREE_CANDIDATE_PROVIDERS", "example-candidates")
    change = TierRouteChange("chat", "FREE", "set", FREE_CANDIDATE, None, True)
    with pytest.raises(ControlPlaneContractError) as exc:
        _check_route_changes((change,), dict(CATALOG, **{FREE_CANDIDATE: CatalogModel(
            FREE_CANDIDATE, True, True, True, True, frozenset({"chat"}),
        )}))
    assert exc.value.code == "model_route_free_candidate"


def test_a_stored_or_static_free_candidate_is_never_served(monkeypatch):
    monkeypatch.setenv("PADIEM_B14_FREE_CANDIDATE_PROVIDERS", "example-candidates")
    stored = TierRouteSnapshot("padiem-global", 1, (
        TierRoute("chat", "FREE", FREE_CANDIDATE, None, True),
    ))
    for product in ("chat", "claw"):
        resolution = _resolution(stored, "FREE", product)
        assert (resolution.ok, resolution.reason) == (
            False, "central_route_unavailable",
        )
    static = static_tier_route(FREE_CANDIDATE, None)
    assert (static.ok, static.reason) == (False, "tier_unavailable")


def test_no_designated_grade_roster_offers_a_free_candidate(tmp_path, monkeypatch):
    """Fixture-based (#6828 3단계): the rosters come from the private document."""
    fixture = Path(__file__).parent / "fixtures" / "models_private_fixture.json"
    target = tmp_path / "models-private.json"
    shutil.copyfile(fixture, target)
    os.chmod(target, 0o600)
    monkeypatch.setenv("PADIEM_MODELS_REGISTRY", str(target))
    monkeypatch.setenv("PADIEM_B14_FREE_CANDIDATE_PROVIDERS", "example-candidates")
    for tier, roster in tier_fallback_rosters().items():
        assert not any(effective_is_free_execution_candidate(model_id) for model_id in roster), tier
    for label in ProductTierLabel:
        route = effective_active_route_for(label)
        if route is None:
            continue
        assert not effective_is_free_execution_candidate(route.model_id)


def test_the_free_candidate_rule_is_deployment_scoped_and_value_free(monkeypatch):
    """#6828 3단계: the repository carries no provider or model name. The
    excluded free family is the deployment's own ``-free`` roster of the
    providers listed in the private env variable; with the variable unset the
    rule excludes nothing (a lane such as a free-suffixed direct pilot keeps
    working), and a provider outside the list is never excluded."""
    monkeypatch.setenv("PADIEM_B14_FREE_CANDIDATE_PROVIDERS", "example-candidates")
    assert effective_is_free_execution_candidate(FREE_CANDIDATE)
    assert effective_is_free_execution_candidate("example-candidates/other-free")
    assert not effective_is_free_execution_candidate("example-candidates/paid-model")
    assert not effective_is_free_execution_candidate("other-provider/example-model-free")
    monkeypatch.delenv("PADIEM_B14_FREE_CANDIDATE_PROVIDERS")
    assert not effective_is_free_execution_candidate(FREE_CANDIDATE)
