"""Tests for the promoted CP managed-cloud quota/admission guard (#1484).

Behavioural cases are ported from the reviewed B54-side suite
(``apps/korean-ai-code-agent/tests/test_cloud_quota.py``) with the
fail-closed admission semantics kept exact. Pure offline validation;
network-free.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.cloud_quota import (
    BILLING_PRICE_CREDIT_AUTHORITY,
    REAL_CONTROL_PLANE_QUOTA_CALLS,
    CloudRunAdmissionRequest,
    CloudRunAdmissionDecision,
    CloudRunQuotaGuard,
    ControlPlaneEntitlementProjection,
    ControlPlaneUsageProjection,
    EntitlementState,
    QuotaDenialReason,
)
from padiem_control_plane.contracts import ControlPlaneContractError

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)
GUARD = CloudRunQuotaGuard()


def entitlement(**kwargs) -> ControlPlaneEntitlementProjection:
    values = dict(
        workspace_id="ws_1",
        entitlement_ref="ent_1",
        state=EntitlementState.ACTIVE,
        max_queued_runs=3,
        max_active_runs=2,
        max_daily_runtime_minutes=120,
        valid_until=NOW + timedelta(hours=1),
    )
    values.update(kwargs)
    return ControlPlaneEntitlementProjection(**values)


def usage(**kwargs) -> ControlPlaneUsageProjection:
    values = dict(
        workspace_id="ws_1",
        usage_ref="usage_1",
        queued_runs=0,
        active_runs=0,
        daily_runtime_minutes=0,
        observed_at=NOW,
    )
    values.update(kwargs)
    return ControlPlaneUsageProjection(**values)


def req(**kwargs) -> CloudRunAdmissionRequest:
    values = dict(request_id="admit_1", workspace_id="ws_1", run_id="run_1", requested_runtime_minutes=30)
    values.update(kwargs)
    return CloudRunAdmissionRequest(**values)


def evaluate(request=None, ent=None, use=None, now=NOW) -> CloudRunAdmissionDecision:
    return GUARD.evaluate(
        request=request or req(),
        entitlement=ent or entitlement(),
        usage=use or usage(),
        now=now,
    )


def test_bounded_active_entitlement_allows_run() -> None:
    decision = evaluate()
    assert decision.allowed is True
    assert decision.denial_reason is None
    safe = decision.safe_dict()
    assert safe["billing_authority"] == "control_plane"
    assert safe["price_or_credit_calculation"] is False
    assert safe["pricing_authority"] is False
    assert safe["credit_debit_authority"] is False


def test_disabled_or_suspended_entitlement_denies() -> None:
    for state in (EntitlementState.DISABLED, EntitlementState.SUSPENDED):
        decision = evaluate(ent=entitlement(state=state))
        assert decision.allowed is False
        assert decision.denial_reason == QuotaDenialReason.ENTITLEMENT_INACTIVE


def test_expired_entitlement_or_stale_usage_fails_closed() -> None:
    expired = evaluate(ent=entitlement(valid_until=NOW - timedelta(seconds=1)))
    assert expired.denial_reason == QuotaDenialReason.ENTITLEMENT_STALE
    stale = evaluate(use=usage(observed_at=NOW - timedelta(seconds=301)))
    assert stale.denial_reason == QuotaDenialReason.ENTITLEMENT_STALE
    future = evaluate(use=usage(observed_at=NOW + timedelta(seconds=1)))
    assert future.denial_reason == QuotaDenialReason.ENTITLEMENT_STALE


def test_queue_concurrency_and_daily_runtime_limits() -> None:
    queue = evaluate(use=usage(queued_runs=3))
    assert queue.denial_reason == QuotaDenialReason.QUEUE_LIMIT
    active = evaluate(use=usage(active_runs=2))
    assert active.denial_reason == QuotaDenialReason.ACTIVE_RUN_LIMIT
    daily = evaluate(use=usage(daily_runtime_minutes=100), request=req(requested_runtime_minutes=21))
    assert daily.denial_reason == QuotaDenialReason.DAILY_RUNTIME_LIMIT
    exact = evaluate(use=usage(daily_runtime_minutes=100), request=req(requested_runtime_minutes=20))
    assert exact.allowed is True


def test_cross_workspace_projection_mix_fails_closed() -> None:
    with pytest.raises(ControlPlaneContractError, match="different workspaces"):
        evaluate(ent=entitlement(workspace_id="ws_2"))
    with pytest.raises(ControlPlaneContractError, match="different workspaces"):
        evaluate(use=usage(workspace_id="ws_2"))


def test_negative_usage_and_invalid_requested_runtime_are_rejected() -> None:
    with pytest.raises(ControlPlaneContractError, match="between 0 and"):
        usage(active_runs=-1)
    with pytest.raises(ControlPlaneContractError, match="between 1 and"):
        req(requested_runtime_minutes=0)
    with pytest.raises(ControlPlaneContractError, match="between 1 and"):
        req(requested_runtime_minutes=1441)


def test_entitlement_state_enum_is_bounded_to_three_values() -> None:
    assert {item.value for item in EntitlementState} == {"active", "disabled", "suspended"}


def test_denial_reason_enum_is_bounded_to_five_values() -> None:
    assert {item.value for item in QuotaDenialReason} == {
        "entitlement_inactive",
        "entitlement_stale",
        "queue_limit",
        "active_run_limit",
        "daily_runtime_limit",
    }


def test_guard_rejects_non_projection_inputs() -> None:
    with pytest.raises(ControlPlaneContractError, match="CloudRunAdmissionRequest"):
        GUARD.evaluate(request="not-a-request", entitlement=entitlement(), usage=usage(), now=NOW)
    with pytest.raises(ControlPlaneContractError, match="entitlement/usage projections"):
        GUARD.evaluate(request=req(), entitlement="not-an-entitlement", usage=usage(), now=NOW)


def test_guard_rejects_naive_now() -> None:
    with pytest.raises(ControlPlaneContractError, match="timezone-aware"):
        GUARD.evaluate(request=req(), entitlement=entitlement(), usage=usage(), now=datetime(2026, 9, 3, 1, 0))


def test_guard_rejects_invalid_max_usage_age() -> None:
    with pytest.raises(ControlPlaneContractError, match="max_usage_age_seconds"):
        GUARD.evaluate(request=req(), entitlement=entitlement(), usage=usage(), now=NOW, max_usage_age_seconds=0)
    with pytest.raises(ControlPlaneContractError, match="max_usage_age_seconds"):
        GUARD.evaluate(request=req(), entitlement=entitlement(), usage=usage(), now=NOW, max_usage_age_seconds=3601)


def test_invalid_entitlement_state_string_is_rejected() -> None:
    with pytest.raises(ControlPlaneContractError, match="invalid entitlement state"):
        ControlPlaneEntitlementProjection(
            workspace_id="ws_1",
            entitlement_ref="ent_1",
            state="unknown",
            max_queued_runs=1,
            max_active_runs=1,
            max_daily_runtime_minutes=60,
            valid_until=NOW,
        )


def test_guard_has_no_billing_authority_or_real_quota_calls() -> None:
    assert BILLING_PRICE_CREDIT_AUTHORITY is False
    assert REAL_CONTROL_PLANE_QUOTA_CALLS == 0
