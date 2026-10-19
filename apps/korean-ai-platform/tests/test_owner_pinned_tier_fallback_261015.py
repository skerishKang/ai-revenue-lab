"""Owner-pinned Beam default and ordered tier fallback policy."""
from __future__ import annotations
import pytest
from app.pilot import router_core
from app.pilot.tier_fallback import TIER_DEFAULT_B14_MODEL, TIER_FALLBACK_B14_MODELS

@pytest.mark.parametrize("tier,backups",tuple(TIER_FALLBACK_B14_MODELS.items()))
def test_beam_grade_has_exact_owner_backups(monkeypatch,tier,backups):
    monkeypatch.setattr(router_core,"_credential_status_for",lambda cm:(True,"present","platform_secret",cm.platform_provider_id))
    monkeypatch.setattr(router_core,"_platform_secret_present",lambda cm:True)
    decision=router_core.resolve_manual_route(TIER_DEFAULT_B14_MODEL,allow_external_fallback=False,product_tier=tier)
    assert decision.selected_model==TIER_DEFAULT_B14_MODEL
    assert decision.fallback_allowed
    assert decision.max_attempts==1+len(backups)
    assert [candidate["model_id"] for candidate in decision.eligible_fallback]==list(backups)
    assert "owner_selected_tier_fallback:"+tier in decision.reason_codes

@pytest.mark.parametrize("code,expected",[("upstream_server_error",True),("upstream_rate_limited",True),("upstream_timeout",True),("upstream_auth_failed",False),("upstream_client_error",False),("internal_error",False),("malformed_upstream_response",False)])
def test_fallback_only_on_recoverable_errors(code,expected):
    assert router_core.is_error_fallback_allowed(code) is expected
