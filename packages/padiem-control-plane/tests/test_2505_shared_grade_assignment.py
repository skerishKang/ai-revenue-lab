"""#2505 stage 1: one shared Chat/Claw grade assignment, no free candidate.

The owner decision (2026-10-21) makes Chat and Claw two screens of one AI
product, so the Free/Plus/Pro/Max assignment they read and update is one
shared setting. The same decision keeps OpenCode Go free models out of the
execution candidates.

These are contract tests: no provider call, no D1 and no deployment.
"""
from __future__ import annotations

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
from padiem_control_plane.product_tier_routes import (
    TIER_FALLBACK_B14_MODELS,
    ProductTierLabel,
    active_route_for,
    is_free_execution_candidate,
)

SHARED = "google/shared-grade-model"
SHARED_FALLBACK = "google/shared-grade-fallback"
LEGACY = "google/legacy-claw-model"
FREE_CANDIDATE = "opencode-go/longcat-2.5-preview-free"
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


def test_a_free_candidate_can_never_be_bound_to_a_grade():
    change = TierRouteChange("chat", "FREE", "set", FREE_CANDIDATE, None, True)
    with pytest.raises(ControlPlaneContractError) as exc:
        _check_route_changes((change,), dict(CATALOG, **{FREE_CANDIDATE: CatalogModel(
            FREE_CANDIDATE, True, True, True, True, frozenset({"chat"}),
        )}))
    assert exc.value.code == "model_route_free_candidate"


def test_a_stored_or_static_free_candidate_is_never_served():
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


def test_no_designated_grade_roster_offers_a_free_candidate():
    for tier, roster in TIER_FALLBACK_B14_MODELS.items():
        assert not any(is_free_execution_candidate(model_id) for model_id in roster), tier
    for label in ProductTierLabel:
        route = active_route_for(label)
        assert route is not None
        assert not is_free_execution_candidate(route.model_id)


def test_the_free_candidate_rule_covers_the_owner_free_family_only():
    assert is_free_execution_candidate(FREE_CANDIDATE)
    assert is_free_execution_candidate("opencode-go/beam-free")
    assert not is_free_execution_candidate("opencode-go/muse-spark-1.3-contributor")
    assert not is_free_execution_candidate("google/gemini-3.1-flash-lite")
    # Another provider's free lane keeps its own approval status.
    assert not is_free_execution_candidate("kira/qwen3.8-flash-free")
    assert not is_free_execution_candidate("tokenharbor/deepseek-v4.1-flash:free")
