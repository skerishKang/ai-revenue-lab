"""B14 owner-designated failover is independent of arbitrary router auto mode."""
from __future__ import annotations
import pytest
from app.pilot import router_core
from app.pilot.tier_fallback import TIER_FALLBACK_B14_MODELS

@pytest.mark.parametrize("tier,backup_id",tuple(TIER_FALLBACK_B14_MODELS.items()))
def test_cat_jam_owner_grade_has_one_automatic_backup(monkeypatch,tier,backup_id):
    # Production secret contents must never enter a source test.
    monkeypatch.setattr(router_core,"_credential_status_for",
                        lambda cm:(True,"present","platform_secret",cm.platform_provider_id))
    monkeypatch.setattr(router_core,"_platform_secret_present",lambda cm:True)
    decision=router_core.resolve_manual_route(
        "opencode-go/cat-jam-free",allow_external_fallback=False,product_tier=tier
    )
    assert decision.selected_model=="opencode-go/cat-jam-free"
    assert decision.fallback_allowed is True
    assert decision.max_attempts==2
    assert [candidate["model_id"] for candidate in decision.eligible_fallback]==[backup_id]
    assert "owner_selected_tier_fallback:"+tier in decision.reason_codes

@pytest.mark.parametrize("code,expected",[
    ("upstream_server_error",True),
    ("upstream_rate_limited",True),
    ("upstream_timeout",True),
    ("upstream_auth_failed",False),
    ("upstream_client_error",False),
    ("internal_error",False),
    ("malformed_upstream_response",False),
])
def test_fallback_only_on_recoverable_provider_failures(code,expected):
    assert router_core.is_error_fallback_allowed(code) is expected
