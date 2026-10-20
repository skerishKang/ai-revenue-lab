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
    assert decision.max_attempts == 1 + len(backups)
    assert [item["model_id"] for item in decision.eligible_fallback] == list(backups)
    assert "owner_selected_tier_fallback:free" in decision.reason_codes


@pytest.mark.parametrize("model_id,tier", [
    ("opencode-go/beam-free", "free"),
    ("opencode-go/muse-spark-1.3-contributor", "plus"),
    ("google/gemini-3.1-flash-lite", "plus"),
])
def test_other_primary_or_grade_does_not_inherit_free_fallback(monkeypatch, model_id, tier):
    _ready(monkeypatch)
    decision = router_core.resolve_manual_route(
        model_id, allow_external_fallback=False, product_tier=tier,
    )
    assert decision.selected_model == model_id
    assert not decision.fallback_allowed
    assert not decision.eligible_fallback
    assert decision.max_attempts == 1


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
