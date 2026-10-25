"""Owner-pinned Free Google default and ordered tier fallback policy."""
from __future__ import annotations

import pytest

from app.pilot import router_core
from app.pilot.tier_fallback import TIER_DEFAULT_B14_MODEL, TIER_FALLBACK_B14_MODELS


def _ready(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


def test_google_free_grade_has_exact_owner_backups(monkeypatch):
    _ready(monkeypatch)
    assert TIER_DEFAULT_B14_MODEL == "google/gemini-3.1-flash-lite"
    backups = TIER_FALLBACK_B14_MODELS["free"]
    assert backups == (
        "google/gemma-4-26b-a4b-it",
        "google/gemini-3.5-flash-lite",
        "google/gemma-4-31b-it",
    )
    decision = router_core.resolve_manual_route(
        TIER_DEFAULT_B14_MODEL, allow_external_fallback=False, product_tier="free",
    )
    assert decision.selected_model == TIER_DEFAULT_B14_MODEL
    assert decision.fallback_allowed
    # #4317: the candidate list is the whole budget. The primary plus
    # every owner-pinned backup is tried, and nothing narrows that list.
    assert len(decision.eligible_fallback) + 1 == 1 + len(backups)
    assert [item["model_id"] for item in decision.eligible_fallback] == list(backups)
    assert "owner_selected_tier_fallback:free" in decision.reason_codes


@pytest.mark.parametrize("model_id,tier", [
    ("opencode-go/muse-spark-1.3-contributor", "plus"),
    ("google/gemini-3.1-flash-lite", "plus"),
])
def test_other_primary_or_grade_does_not_inherit_free_fallback(monkeypatch, model_id, tier):
    # #2505: a free primary no longer resolves at all, so it is proven
    # refused in test_2505_b14_free_candidate_execution_block.py.
    _ready(monkeypatch)
    decision = router_core.resolve_manual_route(
        model_id, allow_external_fallback=False, product_tier=tier,
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
    ("malformed_upstream_response", False),
])
def test_fallback_only_on_recoverable_errors(code, expected):
    assert router_core.is_error_fallback_allowed(code) is expected


def test_a_caller_cannot_narrow_the_owner_roster_with_an_attempt_count(monkeypatch):
    """#4317: an attempt count no longer shortens the owner roster."""
    _ready(monkeypatch)
    decision = router_core.resolve_route(
        TIER_DEFAULT_B14_MODEL,
        {"product_tier": "free", "allow_external_fallback": False, "max_attempts": 1},
    )
    assert decision.route_mode == "manual"
    assert decision.fallback_allowed is True
    assert [item["model_id"] for item in decision.eligible_fallback] == list(
        TIER_FALLBACK_B14_MODELS["free"]
    )


def test_an_explicit_attempt_count_does_not_narrow_the_nonstreaming_contract(monkeypatch):
    """#4317: the roster is the same whatever number a caller sends."""
    _ready(monkeypatch)
    default = router_core.resolve_route(TIER_DEFAULT_B14_MODEL, {"product_tier": "free"})
    capped = router_core.resolve_route(
        TIER_DEFAULT_B14_MODEL, {"product_tier": "free", "max_attempts": 2},
    )
    assert len(default.eligible_fallback) == len(TIER_FALLBACK_B14_MODELS["free"])
    assert [item["model_id"] for item in capped.eligible_fallback] == [
        item["model_id"] for item in default.eligible_fallback
    ]


def test_b14_accepts_the_attempt_option_but_never_returns_it_as_a_bound():
    """#4317: the option is accepted for wire compatibility only.

    It is not forwarded to the router, so it can no longer narrow the
    candidate list.
    """
    from app.pilot.gateway import _validate_b14_options
    assert "max_attempts" not in _validate_b14_options({"max_attempts": 50})


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "50"])
def test_b14_rejects_invalid_attempt_budget(value):
    from app.pilot.gateway import _InvalidBody, _validate_b14_options
    with pytest.raises(_InvalidBody):
        _validate_b14_options({"max_attempts": value})


@pytest.mark.parametrize("tier", ["plus", "pro", "max", "admin"])
def test_owner_test_phase_google_rosters_have_the_exact_recovery_order(tier):
    assert TIER_FALLBACK_B14_MODELS[tier] == (
        "google/gemini-3.1-flash-lite", "google/gemma-4-31b-it")
