"""First-owner role bootstrap route: self-only, roleless-to-OWNER, once."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import connector_owner_role_bootstrap as bootstrap
from app import control_plane_identity_worker as worker_client
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

NOW = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)
SUBJECT = "subject.canonical.owner.1"
TENANT = "tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class Request:
    def __init__(self, data, state):
        self.app = SimpleNamespace(state=state)
        self.headers = {"content-type": "application/json", "content-length": str(len(json.dumps(data)))}
        self._data = data

    async def body(self):
        return json.dumps(self._data).encode()


def run(handler, request):
    response = asyncio.run(handler(request))
    return response.status_code, json.loads(response.body)


class Csrf:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def verify(self, request):
        del request
        return self.allowed


def membership(*, role=None):
    return TenantMembership(
        tenant_id=TENANT, canonical_subject_id=SUBJECT,
        state=TenantMembershipState.ACTIVE, created_at=NOW, role=role,
    )


class RoleAuthority:
    """Fake private Identity binding: single roleless row unless told otherwise."""

    def __init__(self, *, tenant_ids=(TENANT,), pre_role=None):
        self.tenant_ids = tenant_ids
        self.pre_role = pre_role
        self.calls = []

    async def resolve_active_memberships(self, *, canonical_subject_id):
        self.calls.append(("resolve", canonical_subject_id))
        return tuple(self.tenant_ids)

    async def assign_tenant_membership(self, *, tenant_id, canonical_subject_id, role=None):
        self.calls.append(("assign", tenant_id, canonical_subject_id, role))
        assert tenant_id == TENANT and canonical_subject_id == SUBJECT
        if role is None:
            return membership(role=self.pre_role)
        assert role == TenantMembershipRole.OWNER.value
        return membership(role=TenantMembershipRole.OWNER)


def canonical_session():
    return AuthSessionSnapshot(
        session_id="session.canonical.owner.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
        issued_at=NOW - timedelta(days=1), expires_at=NOW + timedelta(days=30),
        state=AuthSessionState.ACTIVE, tenant_id=TENANT,
    )


def state_for(authority, *, csrf=True):
    from app import claw_connector_enrollment_routes as routes

    return SimpleNamespace(
        control_plane_identity_authority=authority,
        connector_enrollment_browser_csrf=Csrf(csrf),
    )


def setup_auth(monkeypatch):
    from app import claw_connector_enrollment_routes as routes

    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "product-user-1")

    async def resolve(request):
        del request
        return SimpleNamespace(product_user_id="product-user-1", auth_session=canonical_session())

    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", resolve)


def body():
    return {"confirmed": True, "confirmation_version": "pc-enrollment-consent-v1"}


def test_roleless_single_membership_is_promoted_once(monkeypatch):
    setup_auth(monkeypatch)
    authority = RoleAuthority()
    status, result = run(bootstrap.bootstrap_owner_role, Request(body(), state_for(authority)))
    assert status == 200 and result == {"ok": True, "bootstrapped": True}
    assert authority.calls == [
        ("resolve", SUBJECT),
        ("assign", TENANT, SUBJECT, None),
        ("assign", TENANT, SUBJECT, "owner"),
    ]


def test_existing_role_is_never_touched(monkeypatch):
    setup_auth(monkeypatch)
    authority = RoleAuthority(pre_role=TenantMembershipRole.VIEWER)
    status, result = run(bootstrap.bootstrap_owner_role, Request(body(), state_for(authority)))
    assert status == 409 and result["error"]["code"] == "connector_owner_bootstrap_role_present"
    assert authority.calls == [("resolve", SUBJECT), ("assign", TENANT, SUBJECT, None)]


def test_zero_or_ambiguous_memberships_refuse_before_any_write(monkeypatch):
    setup_auth(monkeypatch)
    empty = RoleAuthority(tenant_ids=())
    status, result = run(bootstrap.bootstrap_owner_role, Request(body(), state_for(empty)))
    assert status == 403 and result["error"]["code"] == "connector_owner_bootstrap_no_membership"
    assert empty.calls == [("resolve", SUBJECT)]
    ambiguous = RoleAuthority(tenant_ids=(TENANT, "tenant_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
    status, result = run(bootstrap.bootstrap_owner_role, Request(body(), state_for(ambiguous)))
    assert status == 409 and result["error"]["code"] == "connector_owner_bootstrap_ambiguous"
    assert ambiguous.calls == [("resolve", SUBJECT)]


def test_bootstrap_requires_csrf_and_exact_confirmation(monkeypatch):
    setup_auth(monkeypatch)
    authority = RoleAuthority()
    assert run(bootstrap.bootstrap_owner_role, Request(body(), state_for(authority, csrf=False)))[0] == 403
    assert run(
        bootstrap.bootstrap_owner_role,
        Request({"confirmed": "true", "confirmation_version": "pc-enrollment-consent-v1"}, state_for(authority)),
    )[0] == 400
    assert run(
        bootstrap.bootstrap_owner_role,
        Request({"confirmed": True, "confirmation_version": "pc-enrollment-consent-v1", "role": "owner"}, state_for(authority)),
    )[0] == 400
    assert authority.calls == []


def test_missing_authority_ports_fail_closed(monkeypatch):
    setup_auth(monkeypatch)
    bare = SimpleNamespace(
        control_plane_identity_authority=SimpleNamespace(),
        connector_enrollment_browser_csrf=Csrf(True),
    )
    status, result = run(bootstrap.bootstrap_owner_role, Request(body(), bare))
    assert status == 503


class FakeBinding:
    def __init__(self, role=None):
        self.role = role
        self.sent = []

    async def assign_tenant_membership(self, payload):
        self.sent.append(dict(payload))
        return {
            "ok": True,
            "membership": {
                "tenant_id": TENANT, "canonical_subject_id": SUBJECT,
                "state": "active", "created_at": NOW.isoformat(), "role": self.role,
            },
        }


def test_client_sends_role_only_for_owner_and_returns_membership():
    client = worker_client.CloudflareControlPlaneIdentityAuthority(FakeBinding())
    member = asyncio.run(client.assign_tenant_membership(tenant_id=TENANT, canonical_subject_id=SUBJECT))
    assert member.role is None
    with pytest.raises(ValueError):
        asyncio.run(client.assign_tenant_membership(
            tenant_id=TENANT, canonical_subject_id=SUBJECT, role="viewer",
        ))
    owned = FakeBinding(role="owner")
    owned_client = worker_client.CloudflareControlPlaneIdentityAuthority(owned)
    member = asyncio.run(owned_client.assign_tenant_membership(
        tenant_id=TENANT, canonical_subject_id=SUBJECT, role="owner",
    ))
    assert member.role is TenantMembershipRole.OWNER
    assert owned.sent == [{
        "tenant_id": TENANT, "canonical_subject_id": SUBJECT, "role": "owner",
    }]
