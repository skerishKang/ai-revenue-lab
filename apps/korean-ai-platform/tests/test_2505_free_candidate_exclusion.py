"""#2505 stage 1: an OpenCode Go free model is never an execution candidate.

Owner decision 2026-10-21: the free OpenCode Go models leave every
designated per-grade roster and every automatic candidate list. The paid
OpenCode Go model stays, and another provider's free lane keeps its own
approval status.
"""
from __future__ import annotations

from app.pilot import router_core
from app.pilot.owner_model_exclusions import free_candidate_excluded_from_execution
from app.pilot.tier_fallback import TIER_DEFAULT_B14_MODEL, TIER_FALLBACK_B14_MODELS

FREE_CANDIDATES = (
    "opencode-go/beam-free",
    "opencode-go/longcat-2.5-preview-free",
    "opencode-go/step-5-preview-free",
    "opencode-go/cat-jam-free",
)


def _ready(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


def test_no_designated_grade_roster_offers_a_free_candidate():
    for tier, roster in TIER_FALLBACK_B14_MODELS.items():
        assert not any(
            free_candidate_excluded_from_execution(model_id) for model_id in roster
        ), tier


def test_the_owner_tier_fallback_candidate_list_has_no_free_model(monkeypatch):
    _ready(monkeypatch)
    decision = router_core.resolve_manual_route(
        TIER_DEFAULT_B14_MODEL, allow_external_fallback=False, product_tier="free",
    )
    offered = [item["model_id"] for item in decision.eligible_fallback]
    assert offered == list(TIER_FALLBACK_B14_MODELS["free"])
    assert not any(free_candidate_excluded_from_execution(model_id) for model_id in offered)


def test_a_registered_free_lane_is_never_offered_as_a_recovery_candidate(monkeypatch):
    """Registration is not activation: a free lane may stay in the registry.

    The automatic recovery candidates must not offer it, whatever the catalog
    holds.
    """
    from app.pilot import catalog

    _ready(monkeypatch)
    free = catalog.CatalogModel(
        model_id="opencode-go/beam-free", upstream_model="beam-free",
        display_name="Beam Free", provider="OpenCode Go", provider_type="platform",
        input_price_usd_per_1m=0.0, output_price_usd_per_1m=0.0,
        capabilities=frozenset({"chat", "free"}), platform_provider_id="opencode-go",
        source="test", source_checked_at="2026-10-21", sort_order=0, enabled=True,
    )
    monkeypatch.setattr(catalog, "CATALOG_MODELS", [free])

    decision = router_core.resolve_manual_route(
        "google/gemini-3.1-flash-lite", allow_external_fallback=True, product_tier="plus",
    )

    offered = [item["model_id"] for item in decision.eligible_fallback]
    assert "opencode-go/beam-free" not in offered


def test_the_free_models_stay_registered_but_are_never_candidates():
    from app.pilot.catalog import CATALOG_BY_ID

    registered_free = [
        model_id for model_id in CATALOG_BY_ID
        if free_candidate_excluded_from_execution(model_id)
    ]
    assert registered_free, "the registry still holds the free rows"


def test_the_free_candidate_rule_covers_the_owner_free_family_only():
    for model_id in FREE_CANDIDATES:
        assert free_candidate_excluded_from_execution(model_id), model_id
    assert not free_candidate_excluded_from_execution(
        "opencode-go/muse-spark-1.3-contributor"
    )
    assert not free_candidate_excluded_from_execution("google/gemini-3.1-flash-lite")
    # Another provider's free lane keeps its own approval status.
    assert not free_candidate_excluded_from_execution("kira/qwen3.8-flash-free")
    assert not free_candidate_excluded_from_execution(
        "tokenharbor/deepseek-v4.1-flash:free"
    )


def _shared_declaration_roster():
    """The shared Control Plane declaration of the same per-grade roster.

    The declaration is stdlib-only, so it is read by path: the platform app
    does not depend on the Control Plane package, and this contract only has
    to compare the two declarations.
    """
    import importlib.util
    import sys
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[3]
        / "packages" / "padiem-control-plane" / "padiem_control_plane"
        / "product_tier_routes.py"
    )
    spec = importlib.util.spec_from_file_location("shared_product_tier_routes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The declaration uses dataclasses, which resolve through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.TIER_FALLBACK_B14_MODELS


def test_the_execution_roster_matches_the_shared_declaration():
    """The B14 execution roster and the shared product declaration stay equal.

    A drift between them would let the product declare a recovery option that
    B14 never executes, or the other way round, with no test noticing.
    """
    assert dict(TIER_FALLBACK_B14_MODELS) == dict(_shared_declaration_roster())


def test_every_declared_grade_candidate_is_in_the_real_b14_allow_list():
    """A declared recovery candidate must still be a usable B14 route.

    The router only offers a candidate that is registered, enabled and not
    owner-excluded, so a declared candidate outside that allow list would
    silently remove a grade's recovery option.
    """
    from app.pilot.catalog import get_catalog_by_id
    from app.pilot.owner_model_exclusions import excluded_from_owner_customer_selection

    for tier, roster in TIER_FALLBACK_B14_MODELS.items():
        assert roster, tier
        for model_id in roster:
            model = get_catalog_by_id(model_id)
            assert model is not None, f"{tier}: {model_id} is not registered in B14"
            assert model.enabled, f"{tier}: {model_id} is not enabled in B14"
            assert not excluded_from_owner_customer_selection(model_id), model_id
            assert not free_candidate_excluded_from_execution(model_id), model_id
