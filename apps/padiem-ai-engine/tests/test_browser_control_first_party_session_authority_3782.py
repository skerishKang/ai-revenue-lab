"""#3782 existing CP identity session RPC -> Engine pending browser ticket.

No additional auth system, impersonation, browser execution or Production
binding. Real Control Plane session snapshots and real AuthSessionScopeAuthority
are used; authoritative CP RPC and shadow are hermetic test ports.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.browser_control_first_party_session_authority import (
    BROWSER_P01_CURRENT_CP_SESSION_WIRED,
    FirstPartyControlPlaneBrowserP01SessionAuthority,
)
from app.browser_control_owner_p01_ticket_issuer import (
    AuthenticatedEngineBrowserP01TicketIssuer,
    CurrentCanonicalHumanSession,
)
from test_browser_control_owner_p01_ticket_issuer_3782 import (
    _OwnerD1,
)
from test_browser_control_p01_receipt_3782 import APP_ID, CONT_REF, setup

USER = "usr_real_3782"
SESSION = "sess_b62_live_3782"
SUBJECT = "owner.3782"
TENANT = "tenant.real.3782"
NOW = datetime.now(timezone.utc)


class _Shadow:
    def __init__(self):
        self.snapshot = SimpleNamespace(
            product_user_id=USER,
            canonical_subject_id=SUBJECT,
            auth_session_id=SESSION,
            session_revision=3,
            session_state="active",
            session_expires_at=NOW + timedelta(minutes=10),
        )
        self.calls = 0

    async def load_projection(self, product_user_id):
        self.calls += 1
        return self.snapshot


class _Cp:
    def __init__(self):
        # Canonical CP public-dict wire contract; no dependency on the
        # independent Control Plane package in Engine standalone CI.
        self.snapshot = {
            "session_id": SESSION,
            "product_id": "b62",
            "subject": {"subject_type": "user", "subject_id": SUBJECT},
            "issued_at": (NOW - timedelta(minutes=3)).isoformat(),
            "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
            "state": "active",
            "revision": 3,
            "tenant_id": TENANT,
        }
        self.calls = 0

    async def resolve_auth_session(self, *, session_id):
        self.calls += 1
        return self.snapshot


def _ports():
    shadow, cp = _Shadow(), _Cp()
    authority = FirstPartyControlPlaneBrowserP01SessionAuthority(
        identity_shadow=shadow, session_client=cp,
    )
    return shadow, cp, authority


def _run(source):
    return asyncio.run(source.resolve_active(
        product_user_id=USER, auth_session_ref=SESSION,
    ))


def test_real_cp_scope_validation_accepts_only_current_shadow_bound_user():
    shadow, cp, source = _ports()
    assert BROWSER_P01_CURRENT_CP_SESSION_WIRED is False
    assert _run(source) == CurrentCanonicalHumanSession(
        product_user_id=USER, canonical_subject_id=SUBJECT,
        workspace_ref=TENANT, auth_session_ref=SESSION,
    )
    assert shadow.calls == cp.calls == 1
    # The CP authority is read freshly on every issuance, not cached.
    assert _run(source) is not None
    assert cp.calls == 2


@pytest.mark.parametrize("broken_field,bad", [
    ("product_user_id", "usr_other"),
    ("auth_session_id", "sess_old"),
    ("canonical_subject_id", "owner.other"),
    ("session_revision", 99),
    ("session_state", "revoked"),
    ("session_expires_at", NOW - timedelta(seconds=1)),
])
def test_foreign_or_inactive_shadow_fails_before_control_plane_rpc(broken_field, bad):
    shadow, cp, source = _ports()
    setattr(shadow.snapshot, broken_field, bad)
    assert _run(source) is None
    if broken_field in {"product_user_id", "auth_session_id", "session_state", "session_expires_at"}:
        assert cp.calls == 0


@pytest.mark.parametrize("bad", [
    {"session_id": "sess_foreign"},
    {"product_id": "engine"},
    {"state": "revoked"},
    {"revision": 1},
    {"tenant_id": None},
    {"tenant_id": SUBJECT},
    {"tenant_id": "b62"},
    {"subject": {"subject_type": "account", "subject_id": SUBJECT}},
    {"subject": {"subject_type": "user", "subject_id": "owner.other"}},
    {"expires_at": (NOW - timedelta(seconds=2)).isoformat()},
    {"extra_field": "unsafe"},
])
def test_current_cp_identity_mismatches_or_payload_extensions_never_grant(bad):
    shadow, cp, source = _ports()
    cp.snapshot = {**cp.snapshot, **bad}
    assert _run(source) is None
    assert shadow.calls == cp.calls == 1


def test_current_cp_unavailable_and_shadow_unlinked_fail_closed():
    shadow, cp, source = _ports()
    cp.snapshot = None
    assert _run(source) is None
    cp.snapshot = _Cp().snapshot
    shadow.snapshot = None
    assert _run(source) is None


def test_invalid_provider_ports_cannot_be_composed():
    with pytest.raises(TypeError):
        FirstPartyControlPlaneBrowserP01SessionAuthority(
            identity_shadow=object(), session_client=object(),
        )


def test_genuine_cp_snapshot_authorizes_only_pending_ticket_not_engine_action():
    engine, service, _receipts, _request = setup(with_human_source=False)
    owner = _OwnerD1()
    _shadow, cp, source = _ports()
    issuer = AuthenticatedEngineBrowserP01TicketIssuer(
        engine_store=service._continuation_store,
        owner_binding=owner,
        session_authority=source,
    )
    try:
        ref = asyncio.run(issuer.issue(
            app_id=APP_ID, continuation_ref=CONT_REF,
            product_user_id=USER, auth_session_ref=SESSION,
        ))
        assert ref.startswith("ticket_")
        row = owner.db.execute(
            "SELECT session_user_id,workspace_ref,engine_owner_subject_id "
            "FROM padiem_browser_control_owner_p01_tickets",
        ).fetchone()
        assert tuple(row) == (USER, TENANT, SUBJECT)
        assert cp.calls == 1
        assert engine.db.execute(
            "SELECT state FROM padiem_engine_continuations WHERE continuation_ref=?",
            (CONT_REF,),
        ).fetchone()[0] == "active"
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_decisions",
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


def test_revoked_cp_session_cannot_create_pending_ticket():
    engine, service, _receipts, _request = setup(with_human_source=False)
    owner = _OwnerD1()
    _shadow, cp, source = _ports()
    cp.snapshot = {**cp.snapshot, "state": "revoked"}
    issuer = AuthenticatedEngineBrowserP01TicketIssuer(
        engine_store=service._continuation_store,
        owner_binding=owner,
        session_authority=source,
    )
    try:
        with pytest.raises(ValueError, match="issuance unavailable"):
            asyncio.run(issuer.issue(
                app_id=APP_ID, continuation_ref=CONT_REF,
                product_user_id=USER, auth_session_ref=SESSION,
            ))
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets",
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


def test_existing_private_cp_service_binding_client_is_reused_for_live_session():
    """Existing Cloudflare CP resolver, not a new identity authority."""
    from app.auth_session_scope_authority import CloudflareControlPlaneAuthSessionClient

    shadow, cp, _unused = _ports()

    class _Binding:
        def __init__(self):
            self.requests = []

        async def resolve_auth_session(self, wire):
            self.requests.append(wire)
            return {"ok": True, "session": cp.snapshot}

    binding = _Binding()
    source = FirstPartyControlPlaneBrowserP01SessionAuthority(
        identity_shadow=shadow,
        session_client=CloudflareControlPlaneAuthSessionClient(binding),
    )
    assert _run(source) == CurrentCanonicalHumanSession(
        product_user_id=USER, canonical_subject_id=SUBJECT,
        workspace_ref=TENANT, auth_session_ref=SESSION,
    )
    assert binding.requests == [{"session_id": SESSION}]
    cp.snapshot = {**cp.snapshot, "state": "revoked"}
    assert _run(source) is None
    assert binding.requests == [{"session_id": SESSION}, {"session_id": SESSION}]
