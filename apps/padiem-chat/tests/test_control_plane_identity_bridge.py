from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    IdentityLinkState,
    ProductIdentityLink,
    SubjectType,
)

from app.control_plane_identity import (
    IdentityBridgeError,
    TrustedProductAuthEvidence,
    bridge_trusted_product_auth,
    require_active_canonical_session,
)


NOW = datetime(2026, 9, 3, 0, 30, tzinfo=timezone.utc)


def evidence() -> TrustedProductAuthEvidence:
    return TrustedProductAuthEvidence(
        product_user_id="usr_0123456789abcdef0123456789abcdef",
        provider="google",
        provider_subject="google-subject-123",
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=12),
    )


class Authority:
    def __init__(self) -> None:
        self.link_calls: list[dict] = []
        self.session_calls: list[dict] = []
        self.link = ProductIdentityLink(
            product_id="b62",
            product_user_id=evidence().product_user_id,
            canonical_subject_id="subject:padiem:user:123",
        )
        self.session = AuthSessionSnapshot(
            session_id="authsession:b62:123",
            product_id="b62",
            subject=CanonicalSubjectRef(
                subject_type=SubjectType.USER,
                subject_id="subject:padiem:user:123",
            ),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=6),
        )

    def resolve_or_create_product_link(self, **kwargs):
        self.link_calls.append(kwargs)
        return self.link

    def establish_auth_session(self, **kwargs):
        self.session_calls.append(kwargs)
        return self.session


async def test_trusted_product_auth_resolves_exact_link_and_session() -> None:
    authority = Authority()
    ev = evidence()

    bridged = await bridge_trusted_product_auth(authority, ev, now=NOW + timedelta(minutes=1))

    assert bridged.product_user_id == ev.product_user_id
    assert bridged.identity_link == authority.link
    assert bridged.auth_session == authority.session
    assert bridged.canonical_subject.subject_id == "subject:padiem:user:123"
    assert authority.link_calls == [
        {
            "product_id": "b62",
            "product_user_id": ev.product_user_id,
            "auth_provider": "google",
            "provider_subject": ev.provider_subject,
        }
    ]
    assert authority.session_calls[0]["product_id"] == "b62"
    assert authority.session_calls[0]["subject"] == bridged.canonical_subject
    assert authority.session_calls[0]["authenticated_at"] == ev.authenticated_at
    assert authority.session_calls[0]["not_after"] == ev.expires_at


async def test_bridge_never_uses_browser_plan_paid_or_entitlement_state() -> None:
    authority = Authority()
    ev = evidence()

    await bridge_trusted_product_auth(authority, ev, now=NOW + timedelta(minutes=1))

    link_payload = authority.link_calls[0]
    session_payload = authority.session_calls[0]
    forbidden = {"plan", "paid", "allow", "entitlement", "credit_balance", "access_token"}
    assert forbidden.isdisjoint(link_payload)
    assert forbidden.isdisjoint(session_payload)


async def test_missing_authority_fails_closed() -> None:
    with pytest.raises(IdentityBridgeError) as raised:
        await bridge_trusted_product_auth(None, evidence(), now=NOW)
    assert raised.value.status_code == 503
    assert raised.value.code == "control_plane_identity_unavailable"


async def test_product_user_link_mismatch_fails_closed() -> None:
    authority = Authority()
    authority.link = ProductIdentityLink(
        product_id="b62",
        product_user_id="usr_ffffffffffffffffffffffffffffffff",
        canonical_subject_id="subject:padiem:user:other",
    )

    with pytest.raises(IdentityBridgeError) as raised:
        await bridge_trusted_product_auth(authority, evidence(), now=NOW)
    assert raised.value.status_code == 403
    assert raised.value.code == "control_plane_identity_mismatch"
    assert authority.session_calls == []


async def test_revoked_identity_link_fails_before_session_creation() -> None:
    authority = Authority()
    authority.link = ProductIdentityLink(
        product_id="b62",
        product_user_id=evidence().product_user_id,
        canonical_subject_id="subject:padiem:user:123",
        state=IdentityLinkState.REVOKED,
    )

    with pytest.raises(IdentityBridgeError) as raised:
        await bridge_trusted_product_auth(authority, evidence(), now=NOW)
    assert raised.value.code == "control_plane_identity_mismatch"
    assert authority.session_calls == []


async def test_session_subject_mismatch_fails_closed() -> None:
    authority = Authority()
    authority.session = AuthSessionSnapshot(
        session_id="authsession:b62:other",
        product_id="b62",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER,
            subject_id="subject:padiem:user:other",
        ),
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    with pytest.raises(IdentityBridgeError) as raised:
        await bridge_trusted_product_auth(authority, evidence(), now=NOW)
    assert raised.value.status_code == 403
    assert raised.value.code == "control_plane_session_mismatch"


async def test_canonical_session_cannot_outlive_product_auth_evidence() -> None:
    authority = Authority()
    ev = evidence()
    authority.session = AuthSessionSnapshot(
        session_id="authsession:b62:too-long",
        product_id="b62",
        subject=authority.session.subject,
        issued_at=NOW,
        expires_at=ev.expires_at + timedelta(seconds=1),
    )

    with pytest.raises(IdentityBridgeError) as raised:
        await bridge_trusted_product_auth(authority, ev, now=NOW)
    assert raised.value.code == "control_plane_session_scope_mismatch"


async def test_expired_or_revoked_canonical_session_fails_closed() -> None:
    authority = Authority()
    ev = evidence()
    authority.session = AuthSessionSnapshot(
        session_id="authsession:b62:expired",
        product_id="b62",
        subject=authority.session.subject,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(IdentityBridgeError) as raised:
        await bridge_trusted_product_auth(authority, ev, now=NOW + timedelta(minutes=2))
    assert raised.value.status_code == 401
    assert raised.value.code == "control_plane_session_inactive"

    authority = Authority()
    authority.session = AuthSessionSnapshot(
        session_id="authsession:b62:revoked",
        product_id="b62",
        subject=authority.session.subject,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.REVOKED,
        revision=2,
    )
    with pytest.raises(IdentityBridgeError) as raised:
        await bridge_trusted_product_auth(authority, ev, now=NOW + timedelta(minutes=2))
    assert raised.value.code == "control_plane_session_inactive"


async def test_require_active_session_returns_canonical_subject_and_later_expires() -> None:
    authority = Authority()
    bridged = await bridge_trusted_product_auth(authority, evidence(), now=NOW)

    subject = require_active_canonical_session(bridged, now=NOW + timedelta(hours=1))
    assert subject == bridged.canonical_subject

    with pytest.raises(IdentityBridgeError) as raised:
        require_active_canonical_session(bridged, now=NOW + timedelta(hours=7))
    assert raised.value.code == "control_plane_session_inactive"


def test_trusted_product_auth_evidence_rejects_untrusted_shapes() -> None:
    with pytest.raises(ValueError):
        TrustedProductAuthEvidence(
            product_user_id="browser-user-id",
            provider="google",
            provider_subject="subject",
            authenticated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with pytest.raises(ValueError):
        TrustedProductAuthEvidence(
            product_user_id=evidence().product_user_id,
            provider="client-selected-provider",
            provider_subject="subject",
            authenticated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
