"""Owner-pinned Free Google default and ordered tier fallback policy.

#7241: no model identity is written here. The roster expectations come from the
effective tier tables (``effective_tier_default`` / ``effective_tier_fallback``),
so the ordering and shape contracts below are still asserted against whatever
document this host reads, while the owner's literal pins ("this exact Google
model", "this exact roster") are owner-decision pins that only make sense on a
host reading the owner's document.
"""
from __future__ import annotations

import pytest

from app.pilot import router_core
from app.pilot.tier_fallback import (
    TIER_DEFAULT_B14_MODEL,
    TIER_FALLBACK_B14_MODELS,
    effective_tier_default,
    effective_tier_fallback,
)
from _registry_values import requires_owner_document

_ROSTER_GRADES = ("free", "plus", "pro", "max", "admin")


@requires_owner_document
def test_google_free_grade_has_exact_owner_backups(monkeypatch):
    _ready(monkeypatch)
    assert TIER_DEFAULT_B14_MODEL == "google/gemini-3.1-flash-lite"
    backups = TIER_FALLBACK_B14_MODELS["free"]
    assert backups == (
        "kilo/stealth/crouton-alpha",
        "openrouter/stealth/crouton-alpha",
        "iteracompute/qwen/qwen3.8-27b",
        "google/gemma-4-31b-it",
        "google/gemini-3.5-flash-lite",
    )
    decision = router_core.resolve_manual_route(
        TIER_DEFAULT_B14_MODEL, product_tier="free",
    )
    assert decision.selected_model == TIER_DEFAULT_B14_MODEL
    assert decision.fallback_allowed
    # #4317: the candidate list is the whole budget. The primary plus
    # every owner-pinned backup is tried, and nothing narrows that list.
    assert len(decision.eligible_fallback) + 1 == 1 + len(backups)
    assert [item["model_id"] for item in decision.eligible_fallback] == list(backups)
    assert "owner_selected_tier_fallback:free" in decision.reason_codes


def _ready(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


def _primary_and_a_non_free_case() -> list[tuple[str, str]]:
    """(model_id, tier) cases that must not inherit the Free chain.

    The first case is the effective Free default asked under a paid grade; the
    second is a paid grade's own primary asked under another paid grade. Both
    identities come from the effective tier tables, so the case list survives a
    registry change and never collapses when one model serves every grade.
    """
    rosters = effective_tier_fallback()
    cases = [(effective_tier_default(), "plus")]
    for grade in _ROSTER_GRADES:
        roster = rosters.get(grade)
        if grade != "free" and roster:
            cases.append((roster[0], "max"))
            break
    return [case for case in cases if case[0]]


@pytest.mark.parametrize("model_id,tier", _primary_and_a_non_free_case())
def test_other_primary_or_grade_does_not_inherit_free_fallback(monkeypatch, model_id, tier):
    # #2505: a free primary no longer resolves at all, so it is proven
    # refused in test_2505_b14_free_candidate_execution_block.py.
    _ready(monkeypatch)
    decision = router_core.resolve_manual_route(
        model_id, product_tier=tier,
    )
    assert decision.selected_model == model_id
    assert not decision.fallback_allowed
    # No eligible fallback means the candidate list holds only the
    # primary, so the walk is a single attempt without any count.
    assert not decision.eligible_fallback


@pytest.mark.parametrize("code,expected", [
    ("upstream_server_error", True),
    ("upstream_rate_limited", True),
    ("upstream_timeout", True),
    ("upstream_auth_failed", False),
    ("upstream_client_error", False),
    ("internal_error", False),
    ("malformed_upstream_response", True),
])
def test_fallback_only_on_recoverable_errors(code, expected):
    assert router_core.is_error_fallback_allowed(code) is expected


def test_a_caller_cannot_narrow_the_owner_roster_with_an_attempt_count(monkeypatch):
    """#4317: an attempt count no longer shortens the owner roster."""
    _ready(monkeypatch)
    decision = router_core.resolve_route(
        effective_tier_default(),
        {"product_tier": "free", "max_attempts": 1},
    )
    assert decision.route_mode == "manual"
    assert decision.fallback_allowed is True
    assert [item["model_id"] for item in decision.eligible_fallback] == list(
        effective_tier_fallback()["free"]
    )


def test_an_explicit_attempt_count_does_not_narrow_the_nonstreaming_contract(monkeypatch):
    """#4317: the roster is the same whatever number a caller sends."""
    _ready(monkeypatch)
    primary = effective_tier_default()
    default = router_core.resolve_route(primary, {"product_tier": "free"})
    capped = router_core.resolve_route(
        primary, {"product_tier": "free", "max_attempts": 2},
    )
    assert len(default.eligible_fallback) == len(effective_tier_fallback()["free"])
    assert [item["model_id"] for item in capped.eligible_fallback] == [
        item["model_id"] for item in default.eligible_fallback
    ]


def test_b14_still_accepts_the_attempt_option_only_to_drop_it(caplog):
    """B4 grace: the scorer-era attempt option is accepted, logged, and
    dropped — the deployed callers still send it, and it can never reach the
    router. The next B14 release refuses it as an unknown field again.
    """
    import logging

    from app.pilot.gateway import _validate_b14_options
    with caplog.at_level(logging.WARNING, logger="korean-ai-platform.pilot"):
        for value in (50, 0, 1.5, "50"):
            assert "max_attempts" not in _validate_b14_options({"max_attempts": value})
    assert any(
        "b14_deprecated_business14_fields_ignored" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize("tier", _ROSTER_GRADES)
def test_owner_test_phase_rosters_have_the_exact_recovery_order(tier):
    """Owner decision 2026-11-04: the paid grades walk one shared ordered
    roster, and Free walks its own shorter chain.

    The order contract is read from the effective tier tables instead of
    literals: the lane ships exactly the effective roster, no roster repeats a
    candidate, every paid roster is the same tuple with its own grade primary
    at the head, and Free opens on the backups the shared chain carries behind
    its primary. The literal identities are the owner's pin and are asserted,
    unchanged, in ``test_owner_test_phase_rosters_pin_the_owner_identities``.
    """
    rosters = effective_tier_fallback()
    if not rosters.get(tier):
        pytest.skip(f"no roster declared for grade {tier!r}")
    expected = rosters[tier]
    assert TIER_FALLBACK_B14_MODELS[tier] == expected
    assert len(set(expected)) == len(expected)
    paid = {grade: rosters[grade] for grade in _ROSTER_GRADES
            if grade != "free" and rosters.get(grade)}
    if tier == "free":
        assert expected
        shared = next(iter(paid.values())) if paid else ()
        if shared:
            # The free chain opens on backups the paid chain offers behind
            # its primary.
            assert set(expected[:2]) <= set(shared[1:])
        return
    shared = next(iter(paid.values()))
    assert all(roster == shared for roster in paid.values())
    assert expected[0] == rosters[tier][0]
    assert set(expected) == set(shared)


@requires_owner_document
@pytest.mark.parametrize("tier,expected", [
    ("plus", ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free", "kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "iteracompute/qwen/qwen3.8-27b", "google/gemma-4-31b-it")),
    ("pro", ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free", "kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "iteracompute/qwen/qwen3.8-27b", "google/gemma-4-31b-it")),
    ("max", ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free", "kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "iteracompute/qwen/qwen3.8-27b", "google/gemma-4-31b-it")),
    ("admin", ("google/gemini-3.1-flash-lite", "tokenharbor/deepseek-v4.1-flash:free", "kilo/stealth/crouton-alpha", "openrouter/stealth/crouton-alpha", "iteracompute/qwen/qwen3.8-27b", "google/gemma-4-31b-it")),
])
def test_owner_test_phase_rosters_pin_the_owner_identities(tier, expected):
    assert TIER_FALLBACK_B14_MODELS[tier] == expected


def test_lane_roster_and_shared_tier_declaration_do_not_drift():
    """B14 executes what the Control Plane declares, so both rosters must match.

    Reads the declaration as source text instead of importing the shared
    package: this suite runs inside the B14 lane, where the Control Plane
    distribution is not on the path.
    """
    import ast
    from pathlib import Path

    declaration_path = (
        Path(__file__).resolve().parents[3]
        / "packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py"
    )
    tree = ast.parse(declaration_path.read_text(encoding="utf-8"))
    declaration = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TIER_FALLBACK_B14_MODELS"
            for target in node.targets
        )
    )

    assert declaration == TIER_FALLBACK_B14_MODELS
