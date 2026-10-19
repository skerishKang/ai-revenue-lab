"""#4546 real Home access route: canonical-session Chat+Claw bundle, zero writes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.home_product_access_routes import ACCESS_PATH
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

ORIGIN = "https://chat.example.test"
UID_A = "usr_" + "a" * 32
UID_B = "usr_" + "b" * 32
SID_A = "subject_a"
SID_B = "subject_b"


def _settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="test.apps.googleusercontent.com",
        google_client_secret="fake-for-synthetic-tests",
        session_secret="fake-but-valid-session-secret-for-tests",
        session_max_age_seconds=3600,
    )


def _session(subject_id=SID_A, *, state=AuthSessionState.ACTIVE, product="b62", tenant="tenant_a"):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session_test_a",
        product_id=product,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject_id),
        issued_at=now - timedelta(minutes=3),
        expires_at=now + timedelta(minutes=30),
        state=state,
        revision=3,
        tenant_id=tenant,
    )


class _History:
    def __init__(self):
        self.users={UID_A, UID_B}
        self.reads=[]
    async def get_user(self, user_id):
        self.reads.append(user_id)
        return SimpleNamespace() if user_id in self.users else None


class _Shadow:
    def __init__(self):
        self.records = {}
        self.reads=[]
    async def load_projection(self, product_user_id):
        self.reads.append(product_user_id)
        return self.records.get(product_user_id)


class _Authority:
    def __init__(self, current):
        self.current=current
        self.calls=[]
    def resolve_auth_session(self, *, session_id):
        self.calls.append(session_id)
        return self.current


def _shadow(uid, subject_id=SID_A, current=None):
    current = current or _session(subject_id)
    return IdentityShadowRecord(
        product_user_id=uid,
        canonical_subject_id=subject_id,
        auth_session_id=current.session_id,
        session_revision=1,
        session_state="active",
        session_expires_at=current.expires_at,
        observed_at=datetime.now(timezone.utc),
    )


def _setup(uid=UID_A, *, session=None):
    sess=session or _session()
    settings=_settings()
    history=_History()
    shadow=_Shadow()
    authority=_Authority(sess)
    shadow.records[uid]=_shadow(uid,subject_id=sess.subject.subject_id,current=sess)
    app=create_app(
        settings=settings,
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )
    client=TestClient(app,base_url=ORIGIN)
    client.cookies.set(SESSION_COOKIE,create_session_token(settings,uid),domain="chat.example.test",path="/")
    return client,history,shadow,authority


def test_active_canonical_user_gets_chat_and_claw_bundle_without_second_login():
    client, history, shadow, authority = _setup()
    with client:
        a=client.get(ACCESS_PATH)
        b=client.get(ACCESS_PATH)
    assert a.status_code == b.status_code == 200
    assert a.json()["version"] == "product-access-projection-v1"
    assert [p["product_id"] for p in a.json()["products"]] == ["b62","b54-padiem-claw"]
    assert [p["access"] for p in a.json()["products"]] == ["available","available"]
    assert all(p["authority"] == "padiem-chat-claw-bundle-v1" for p in a.json()["products"])
    assert a.json() == b.json() or all(p["access"]=="available" for p in b.json()["products"])
    assert "no-store" in a.headers["cache-control"]
    assert a.headers["vary"].lower()=="cookie"
    assert all(x not in a.text.lower() for x in ("subject_a","tenant_a","usr_","b66","credential","session_test"))
    assert history.reads == [UID_A,UID_A]
    assert shadow.reads == [UID_A,UID_A]
    assert authority.calls==["session_test_a","session_test_a"]


@pytest.mark.parametrize("status", [AuthSessionState.REVOKED,AuthSessionState.EXPIRED])
def test_revoked_or_expired_canonical_session_is_never_available(status):
    client,*_ = _setup(session=_session(state=status))
    with client:
        r=client.get(ACCESS_PATH)
    assert r.status_code==503 and "products" not in r.json()


def test_guest_and_unknown_product_are_not_granted():
    client,*_= _setup()
    with client:
        client.cookies.clear()
        r=client.get(ACCESS_PATH)
        assert r.status_code==401
        assert "b54" not in r.text
        r=client.get(ACCESS_PATH+"?product_id=b66")
        assert r.status_code==400


def test_cross_user_shadow_mismatch_and_session_subject_switch_are_denied():
    client,_,shadow,authority=_setup()
    authority.current=_session(SID_B)
    with client:
        r=client.get(ACCESS_PATH)
    assert r.status_code==503
    shadow.records[UID_A]=None
    with client:
        r2=client.get(ACCESS_PATH)
    assert r2.status_code==503


def test_product_scope_mismatch_and_revision_rollback_are_denied():
    client,_,shadow,authority=_setup()
    authority.current=_session(product="b54-padiem-claw")
    with client:
        r=client.get(ACCESS_PATH)
    assert r.status_code==503
    authority.current=_session()
    shadow.records[UID_A]=IdentityShadowRecord(
        product_user_id=UID_A, canonical_subject_id=SID_A,
        auth_session_id="session_test_a", session_revision=100,
        session_state="active", session_expires_at=authority.current.expires_at,
        observed_at=datetime.now(timezone.utc),
    )
    with client:
        r2=client.get(ACCESS_PATH)
    assert r2.status_code==503


def test_canonical_source_absent_fails_closed_without_default_allow():
    client,_,shadow,authority=_setup()
    with client:
        client.app.state.control_plane_identity_authority=None
        r=client.get(ACCESS_PATH)
    assert r.status_code==503
    assert "products" not in r.json()


def test_account_switch_rechecks_the_signed_cookie_subject():
    client,_,shadow,authority=_setup()
    with client:
        assert client.get(ACCESS_PATH).status_code==200
        client.cookies.set(SESSION_COOKIE,create_session_token(_settings(),UID_B),domain="chat.example.test",path="/")
        mismatch=client.get(ACCESS_PATH)
    assert mismatch.status_code==503
    assert shadow.reads[-1]==UID_B


def test_no_post_or_unreviewed_product_queries():
    client,_,_,_=_setup()
    with client:
        assert client.post(ACCESS_PATH,json={"approved":True}).status_code==405
        assert client.get(ACCESS_PATH+"?tenant=tenant_a").status_code==400
        assert client.get(ACCESS_PATH+"?email=owner%40example.com").status_code==400


def test_b62_presentation_cookie_without_history_user_cannot_grant():
    client, history, _, authority = _setup()
    history.users.clear()
    with client:
        r=client.get(ACCESS_PATH)
    assert r.status_code==401
    assert authority.calls==[]
