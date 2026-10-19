"""#4643 Mode 1: route-selected B62/B54 canonical voice sessions (no plan gates)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import auth_routes
from app import voice_stt_routes as voice
from app import b54_canonical_session
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType


def _session(*, product="b62", tenant="tenant_voice_test", state=AuthSessionState.ACTIVE):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="sess_voice_test",
        product_id=product,
        subject=CanonicalSubjectRef(SubjectType.USER, "sub_1234567890abcdef1234567890abcdef"),
        issued_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(minutes=20),
        state=state,
        tenant_id=tenant,
    )


def _request(path, authority):
    app = SimpleNamespace(state=SimpleNamespace(control_plane_identity_authority=authority))
    return Request({"type":"http", "method":"GET", "scheme":"https", "server":("example.org",443),
                    "path":path, "headers":[], "app":app})


class IdentityAuthority:
    def __init__(self, session):
        self.session = session
        self.calls = []
    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.calls.append((product_id, product_user_id))
        return self.session


@pytest.fixture(autouse=True)
def auth_from_existing_cookie(monkeypatch):
    # A verified product user is read from the existing signed PADIEM cookie.
    monkeypatch.setattr(auth_routes, "auth_ready", lambda req: True)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda req: "usr_voice_test")


@pytest.mark.parametrize("path", [voice.IDENTITY_PATH, voice.TRANSCRIBE_PATH])
def test_b62_is_always_resolved_as_b62_not_b54(path):
    authority = IdentityAuthority(_session(product="b62"))
    item = asyncio.run(voice._canonical_session(_request(path, authority)))
    assert item.auth_session.product_id == "b62"
    assert authority.calls == [("b62", "usr_voice_test")]


@pytest.mark.parametrize("bad_session", [
    _session(product="b54-padiem-claw"),
    _session(product="b62", tenant=None),
    _session(product="b62", state=AuthSessionState.REVOKED),
])
def test_chat_refuses_cross_product_no_tenant_and_revoked_before_stt(bad_session):
    authority = IdentityAuthority(bad_session)
    assert asyncio.run(voice._canonical_session(_request(voice.TRANSCRIBE_PATH, authority))) is None
    assert authority.calls == [("b62", "usr_voice_test")]


def test_b62_missing_identity_authority_fail_closed():
    assert asyncio.run(voice._canonical_session(_request(voice.TRANSCRIBE_PATH, None))) is None


@pytest.mark.parametrize("path", [voice.CLAW_IDENTITY_PATH, voice.CLAW_TRANSCRIBE_PATH])
def test_claw_uses_the_existing_validated_b54_lane_only(monkeypatch, path):
    authority = IdentityAuthority(_session(product="b62"))
    invoked = []
    async def b54(request):
        invoked.append(request.url.path)
        return SimpleNamespace(auth_session=_session(product="b54-padiem-claw"))
    monkeypatch.setattr(b54_canonical_session, "resolve_current_b54_canonical_session", b54)
    item = asyncio.run(voice._canonical_session(_request(path, authority)))
    assert item.auth_session.product_id == "b54-padiem-claw"
    assert invoked == [path]
    assert authority.calls == []


def test_unknown_voice_route_has_no_authority():
    assert asyncio.run(voice._canonical_session(_request("/api/voice/unsupported",IdentityAuthority(_session())))) is None
