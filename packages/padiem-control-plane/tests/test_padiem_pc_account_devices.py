"""#4139 platform My Devices read and multi-product PC-list denial tests."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.local_agent_pc_access import (
    PcAccessOperation,
    ProductPcAccessGrant, ProductPcAccessPolicy,
)
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentScope
from padiem_control_plane.padiem_pc_account_devices import (
    PC_ACCOUNT_CREATES_PRODUCT_GRANTS,
    PC_ACCOUNT_DECIDES_ONLINE,
    PC_ACCOUNT_DEVICE_MANAGEMENT_CONTRACT,
    PC_ACCOUNT_DEVICE_READ_DEPLOYED,
    PC_ACCOUNT_DEVICE_REVOCATION_WIRED,
    PC_ACCOUNT_DEVICE_ROUTES_MOUNTED,
    account_device_view, product_device_view_for_owner,
)
from padiem_control_plane.tenants import TenantMembershipRole

NOW = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
ACCOUNT = "acct_a"
WORKSPACE = "ws_a"
CLAW = "b54-padiem-claw"
QUOTE = "b66-padiem-quote"
CHAT = "b62"
ENGINE = "padiem-ai-engine"


def signed_owner() -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="session.canonical.owner",
        product_id=CLAW,
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id="subject.owner",
        ),
        tenant_id="tenant.owner",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
    )


def owner_scope() -> ConnectorEnrollmentScope:
    return ConnectorEnrollmentScope(
        owner_subject_id="subject.owner",
        account_ref=ACCOUNT,
        workspace_ref=WORKSPACE,
        product_scoped=False,
    )


def row(device="pc_one", state="paired_offline", session=True):
    result = {
        "canonical_state": state,
        "binding": {
            "binding_ref": "binding_" + device,
            "device_id": device,
            "account_ref": ACCOUNT,
            "workspace_ref": WORKSPACE,
            "credential_generation": 1,
            "issued_at": NOW.isoformat(),
            "credential_expires_at": (NOW + timedelta(days=30)).isoformat(),
            "raw_device_credential": False,
            "credential_digest_exposed": False,
        },
        "session": None,
        "heartbeat_last_seen_at": NOW.isoformat(),
    }
    if session:
        result["session"] = {
            "session_id": "session_" + device,
            "binding_ref": "binding_" + device,
            "device_id": device,
            "account_ref": ACCOUNT,
            "workspace_ref": WORKSPACE,
            "credential_generation": 1,
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "raw_session_secret": False,
        }
    return result


def directory(*rows):
    return {
        "ok": True, "available": True, "owner_scoped": True,
        "device_count": len(rows), "max_devices": 24,
        "devices": list(rows),
    }


def account_view(*, session=None, role=TenantMembershipRole.OWNER,
                 scope=None, broker=None):
    return account_device_view(
        session=signed_owner() if session is None else session,
        membership_role=role,
        scope=owner_scope() if scope is None else scope,
        directory_result=directory(row()) if broker is None else broker,
        now=NOW,
    )


def grant(product, workspace=WORKSPACE):
    return ProductPcAccessGrant(
        product_id=product,
        operations=frozenset({PcAccessOperation.DEVICE_LIST}),
        workspace_ref=workspace,
    )


def product_view(product, policy, *, broker=None):
    return product_device_view_for_owner(
        session=signed_owner(),
        membership_role=TenantMembershipRole.OWNER,
        scope=owner_scope(),
        directory_result=directory(row()) if broker is None else broker,
        policy=policy,
        product_id=product,
        now=NOW,
    )


def test_account_owner_sees_one_shared_device_without_credential_or_identity():
    out = account_view()
    assert out["ok"] is True
    assert out["available"] is True
    assert out["directory_verified"] is True
    assert out["owner_scoped"] is True
    assert out["device_count"] == 1
    assert out["devices"] == [{
        "device_id": "pc_one",
        "canonical_state": "paired_offline",
        "has_session": True,
        "heartbeat_present": True,
        "online_decided_here": False,
    }]
    assert out["dispatch_authorized"] is False
    assert out["grants_read"] is False and out["grants_write"] is False
    text = repr(out)
    for sensitive in ("acct_a", "ws_a", "subject.owner", "binding_pc", "credential_generation",
                      "credential_digest", "raw_session_secret", "token"):
        assert sensitive not in text


def test_owner_can_see_all_owned_devices_in_single_canonical_directory():
    out = account_view(broker=directory(
        row("pc_one"), row("pc_two", state="revoked", session=False),
        row("pc_three", state="credential_expired", session=False),
    ))
    assert out["device_count"] == 3
    assert [x["device_id"] for x in out["devices"]] == ["pc_one", "pc_two", "pc_three"]
    assert out["devices"][1]["canonical_state"] == "revoked"
    assert all(x["online_decided_here"] is False for x in out["devices"])


def test_owner_with_no_bound_device_receives_honest_empty_view():
    result = account_view(broker={
        "ok": True, "available": False, "reason": "no_device_binding",
    })
    assert result["ok"] is True
    assert result["available"] is False
    assert result["directory_verified"] is True
    assert result["device_count"] == 0


@pytest.mark.parametrize("role", [
    TenantMembershipRole.VIEWER, TenantMembershipRole.OPERATOR,
    TenantMembershipRole.APPROVER, None, "owner", True,
])
def test_non_owner_cannot_read_central_account_devices(role):
    result = account_view(role=role)
    assert result["ok"] is False
    assert result["devices"] == []
    assert result["directory_verified"] is False


def test_expired_or_revoked_login_cannot_list_account_devices():
    for state in (AuthSessionState.REVOKED, AuthSessionState.EXPIRED):
        result = account_view(session=replace(signed_owner(), state=state))
        assert result["ok"] is False
        assert result["devices"] == []


@pytest.mark.parametrize("product", ["b62", "b66-padiem-quote", "padiem-engine"])
def test_unreviewed_product_login_does_not_bypass_identity_bridge(product):
    result = account_view(session=replace(signed_owner(), product_id=product))
    assert result["ok"] is False
    assert result["devices"] == []


def test_subject_swap_cannot_see_another_users_directory():
    mismatched = ConnectorEnrollmentScope(
        owner_subject_id="subject.other", account_ref=ACCOUNT, workspace_ref=WORKSPACE,
    )
    result = account_view(scope=mismatched)
    assert result["ok"] is False and result["devices"] == []


@pytest.mark.parametrize("tamper", [
    {"account_ref": "acct_other"},
    {"workspace_ref": "ws_other"},
])
def test_broker_row_from_another_account_or_workspace_refuses_entire_directory(tamper):
    good = row("pc_one")
    swapped = row("pc_two")
    swapped["binding"].update(tamper)
    result = account_view(broker=directory(good, swapped))
    assert result["ok"] is False and result["devices"] == []
    assert result["device_count"] == 0


@pytest.mark.parametrize("bad", [
    {"ok": True, "available": True, "owner_scoped": False, "devices": [row()]},
    {"ok": True, "available": True, "owner_scoped": True, "device_count": 3, "max_devices":24, "devices": [row()]},
    directory(row("pc_one"), row("pc_one")),
    directory(row("pc_one"), row("pc_two", state="online")),
    {"ok": True, "available": False, "reason": "no_device_binding", "devices": [row()]},
    {"ok": False, "error": {"code": "sensitive-owner-ref"}},
    directory(*[row("device_" + str(i)) for i in range(25)]),
])
def test_forged_malformed_or_truncated_directory_fails_closed(bad):
    result = account_view(broker=bad)
    assert result["ok"] is False
    assert result["devices"] == []


def test_product_default_off_even_if_owner_sees_pc():
    assert account_view()["available"] is True
    for product in (CLAW, QUOTE, CHAT, ENGINE):
        result = product_view(product, ProductPcAccessPolicy.default_off())
        assert result["available"] is False
        assert result["devices"] == []
        assert result["dispatch_authorized"] is False


def test_cross_brand_device_not_exposed_even_if_both_products_have_grant():
    policy = ProductPcAccessPolicy(grants=(grant(CLAW), grant(QUOTE)))
    claw = product_view(CLAW, policy)
    quote = product_view(QUOTE, policy)
    assert claw["available"] is True
    assert claw["devices"][0]["device_id"] == "pc_one"
    # This caller only proved its Claw login; a Quote policy does NOT
    # transform it into a Quote login or silently link customer brands.
    assert quote["ok"] is False
    assert quote["reason"] == "product_login_context_mismatch"
    assert quote["devices"] == []
    assert claw["dispatch_authorized"] is False
    assert product_view(CHAT, policy)["devices"] == []


def test_cross_workspace_product_grant_cannot_expose_device():
    policy = ProductPcAccessPolicy(grants=(grant(CLAW, workspace="ws_other"),))
    result = product_view(CLAW, policy)
    assert result["available"] is False
    assert result["devices"] == []


def test_platform_account_directory_does_not_claim_online_or_authorize_revoke():
    assert PC_ACCOUNT_DEVICE_MANAGEMENT_CONTRACT == "padiem.canonical-pc-account-devices.v1"
    assert PC_ACCOUNT_DEVICE_ROUTES_MOUNTED is False
    assert PC_ACCOUNT_DEVICE_READ_DEPLOYED is False
    assert PC_ACCOUNT_DEVICE_REVOCATION_WIRED is False
    assert PC_ACCOUNT_CREATES_PRODUCT_GRANTS is False
    assert PC_ACCOUNT_DECIDES_ONLINE is False
