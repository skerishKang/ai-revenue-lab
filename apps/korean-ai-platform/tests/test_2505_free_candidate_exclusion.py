"""#2505 stage 1: an OpenCode Go free model is never an execution candidate.

Owner decision 2026-10-21: the free OpenCode Go models leave every
designated per-grade roster and every automatic candidate list. The paid
OpenCode Go model stays, and another provider's free lane keeps its own
approval status.
"""
from __future__ import annotations

from app.pilot import router_core
from app.pilot.owner_model_exclusions import FREE_CANDIDATE_PROVIDER, free_candidate_excluded_from_execution
from app.pilot.tier_fallback import (
    effective_tier_default,
    effective_tier_fallback,
    TIER_DEFAULT_B14_MODEL,
    TIER_FALLBACK_B14_MODELS,
)
from _registry_values import model_rows, provider_row, registry, requires_owner_document


def _free_model_ids() -> tuple[str, ...]:
    """Every registered identity of the owner-excluded free family."""
    return tuple(
        row["id"] for row in model_rows()
        if free_candidate_excluded_from_execution(row["id"])
    )


def _free_upstream(model_id: str) -> str:
    return next(row["upstream_model"] for row in model_rows() if row["id"] == model_id)


def _a_paid_model_id() -> str:
    """A registered model of the same provider that is not an excluded free lane."""
    return next(
        row["id"] for row in model_rows()
        if row["provider_id"] == FREE_CANDIDATE_PROVIDER
        and not free_candidate_excluded_from_execution(row["id"])
    )


def _ready(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


def test_no_designated_grade_roster_offers_a_free_candidate():
    for tier, roster in effective_tier_fallback().items():
        assert not any(
            free_candidate_excluded_from_execution(model_id) for model_id in roster
        ), tier


def test_the_owner_tier_fallback_candidate_list_has_no_free_model(monkeypatch):
    _ready(monkeypatch)
    decision = router_core.resolve_manual_route(
        effective_tier_default(), product_tier="free",
    )
    offered = [item["model_id"] for item in decision.eligible_fallback]
    assert offered == list(effective_tier_fallback()["free"])
    assert not any(free_candidate_excluded_from_execution(model_id) for model_id in offered)


@requires_owner_document
def test_a_registered_free_lane_is_never_offered_as_a_recovery_candidate(monkeypatch):
    """Registration is not activation: a free lane may stay in the registry.

    The automatic recovery candidates must not offer it, whatever the catalog
    holds.
    """
    from app.pilot import catalog

    _ready(monkeypatch)
    free_model_id = f"{FREE_CANDIDATE_PROVIDER}/synthetic-free"
    free_upstream = "synthetic-free"
    free = catalog.CatalogModel(
        model_id=free_model_id, upstream_model=free_upstream,
        display_name="Synthetic Free Lane", provider="Synthetic Free Provider",
        provider_type="platform",
        input_price_usd_per_1m=0.0, output_price_usd_per_1m=0.0,
        capabilities=frozenset({"chat", "free"}), platform_provider_id=FREE_CANDIDATE_PROVIDER,
        source="test", source_checked_at="2026-10-21", sort_order=0, enabled=True,
    )
    monkeypatch.setattr(catalog, "CATALOG_MODELS", [free])

    decision = router_core.resolve_manual_route(
        effective_tier_default(), product_tier="plus",
    )

    # B5: a non-roster manual route has no recovery candidates at all, so the
    # registered free lane cannot be offered either.
    offered = [item["model_id"] for item in decision.eligible_fallback]
    assert offered == []
    assert free_model_id not in offered


def test_the_free_models_stay_registered_but_are_never_candidates():
    from app.pilot.catalog import CATALOG_BY_ID

    registered_free = [
        model_id for model_id in CATALOG_BY_ID
        if free_candidate_excluded_from_execution(model_id)
    ]
    # Registration is not activation: whichever rows the registry holds, none of
    # them is offered as an execution candidate.
    for model_id in registered_free:
        assert free_candidate_excluded_from_execution(model_id), model_id
        assert not any(
            model_id in roster for roster in effective_tier_fallback().values()
        ), model_id


def test_the_free_candidate_rule_covers_the_owner_free_family_only():
    # The rule is exercised through the family marker the app itself uses, so
    # the assertions hold on a registry that carries the owner's free rows and
    # on one that does not.
    free_model_id = f"{FREE_CANDIDATE_PROVIDER}/synthetic-free"
    paid_model_id = f"{FREE_CANDIDATE_PROVIDER}/synthetic-paid"
    assert free_candidate_excluded_from_execution(free_model_id), free_model_id
    assert not free_candidate_excluded_from_execution(paid_model_id)
    # Another provider's free lane keeps its own approval status: an identity
    # outside the excluded provider carries no exclusion, whatever its suffix.
    other_provider = next(
        name for name in registry()["providers"] if name != FREE_CANDIDATE_PROVIDER
    )
    assert not free_candidate_excluded_from_execution(f"{other_provider}/synthetic-free")
    # Every registered identity of the family, when the registry has any, obeys
    # the rule as well.
    for registered in _free_model_ids():
        assert free_candidate_excluded_from_execution(registered), registered


def _shared_declaration_roster():
    """The shared Control Plane reader of the same per-grade roster.

    The Control Plane declares the shape only; since #7241 3단계 it carries no
    values of its own, and the switch-aware reader beside the declaration
    (``product_tier_routes_private``) resolves the roster from the same document
    B14 installs from, so that is the answer this contract compares.
    """
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane"
    # The reader imports its siblings inside the control-plane package, so the
    # package root goes on the import path for this lookup only.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from padiem_control_plane import product_tier_routes_private

    return product_tier_routes_private.tier_fallback_rosters()


@requires_owner_document
def test_the_execution_roster_matches_the_shared_declaration():
    """The B14 execution roster and the shared product reader stay equal.

    A drift between them would let the product declare a recovery option that
    B14 never executes, or the other way round, with no test noticing. Since
    #7241 3단계 the roster is the effective answer both products read from the
    one document, so the module's own declaration is compared with it as well.
    """
    shared = _shared_declaration_roster()
    assert dict(effective_tier_fallback()) == dict(shared)
    # The repository declaration carries no values any more; it may only be
    # empty, never a second roster that could disagree with the document.
    assert not TIER_FALLBACK_B14_MODELS


def test_every_declared_grade_candidate_is_in_the_real_b14_allow_list():
    """A declared recovery candidate must still be a usable B14 route.

    The router only offers a candidate that is registered, enabled and not
    owner-excluded, so a declared candidate outside that allow list would
    silently remove a grade's recovery option.
    """
    from app.pilot.catalog import get_catalog_by_id
    from app.pilot.owner_model_exclusions import excluded_from_owner_customer_selection

    for tier, roster in effective_tier_fallback().items():
        assert roster, tier
        for model_id in roster:
            model = get_catalog_by_id(model_id)
            assert model is not None, f"{tier}: {model_id} is not registered in B14"
            assert model.enabled, f"{tier}: {model_id} is not enabled in B14"
            assert not excluded_from_owner_customer_selection(model_id), model_id
            assert not free_candidate_excluded_from_execution(model_id), model_id
