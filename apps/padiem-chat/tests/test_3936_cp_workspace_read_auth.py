"""#3936: canonical membership RPC stays compatible with CP's role-aware producer.

A new password user may sign in without a canonical shadow when the assignment
RPC rejects a legitimate role=None response after the server writes membership.
No live user, D1, or Cloudflare RPC is used by these focused regressions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.auth_routes import _write_identity_shadow_after_login
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority


NOW = datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc)
USER = "usr_0123456789abcdef0123456789abcdef"
SUBJECT = "sub_0123456789abcdef0123456789abcdef"
TENANT = "tenant_0123456789abcdef0123456789abcdef"


class IdentityBinding:
    def __init__(self, membership):
        self.membership = membership
        self.calls = []

    async def resolve_or_create_product_link(self, payload):
        self.calls.append("link")
        return {"ok": True, "link": {
            "product_id": "b62",
            "product_user_id": USER,
            "canonical_subject_id": SUBJECT,
            "state": "active",
        }}

    async def resolve_active_memberships(self, payload):
        self.calls.append("memberships")
        return {"ok": True, "tenant_ids": []}

    async def create_tenant(self, payload):
        self.calls.append("create_tenant")
        return {"ok": True, "tenant": {
            "tenant_id": TENANT, "state": "active", "created_at": NOW.isoformat(),
        }}

    async def assign_tenant_membership(self, payload):
        self.calls.append("assign")
        return {"ok": True, "membership": dict(self.membership)}

    async def establish_auth_session(self, payload):
        self.calls.append("session")
        return {"ok": True, "session": {
            "session_id": "sess_0123456789abcdef0123456789abcdef",
            "product_id": "b62",
            "subject": {"subject_type": "user", "subject_id": SUBJECT},
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "state": "active",
            "revision": 1,
            "tenant_id": TENANT,
        }}


class Shadow:
    def __init__(self):
        self.saved = None

    async def save_projection(self, bridged):
        self.saved = bridged


def membership(**extra):
    return {
        "tenant_id": TENANT,
        "canonical_subject_id": SUBJECT,
        "state": "active",
        "created_at": NOW.isoformat(),
        **extra,
    }


@pytest.mark.parametrize("wire", [membership(), membership(role=None), membership(role="owner")])
async def test_real_cp_membership_response_permits_shadow_persistence(wire):
    binding = IdentityBinding(wire)
    shadow = Shadow()
    state = SimpleNamespace(
        control_plane_identity_authority=CloudflareControlPlaneIdentityAuthority(binding),
        identity_shadow_store=shadow,
    )
    await _write_identity_shadow_after_login(
        SimpleNamespace(app=SimpleNamespace(state=state)),
        product_user_id=USER,
        provider="password",
        provider_subject="synthetic-only",
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        ensure_personal_tenant=True,
    )
    assert shadow.saved is not None, "trusted login must not silently lose canonical shadow"
    assert shadow.saved.auth_session.tenant_id == TENANT
    assert binding.calls == ["link", "memberships", "create_tenant", "assign", "session"]


@pytest.mark.parametrize("extra", [{"role": "superuser"}, {"workspace_id": "injected"}, {"role": None, "owner": USER}])
async def test_unknown_role_or_unreviewed_fields_fail_closed(extra):
    binding = IdentityBinding(membership(**extra))
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    with pytest.raises((IdentityBridgeError, ValueError)):
        await authority.assign_tenant_membership(
            tenant_id=TENANT, canonical_subject_id=SUBJECT
        )
    assert binding.calls == ["assign"]
