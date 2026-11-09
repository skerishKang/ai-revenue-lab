"""#7233: a stale identity shadow pointer must be re-pointed at the request's
own verified canonical session.

Defect: the shadow pointer stores one login's canonical session id. After
that session expires or rotates, ``resolve_refreshed_session`` kept failing
on the dead pointer (401 ``control_plane_session_inactive``) and never
re-resolved, so every shared-authority consumer (memory workspace, CP host
session, home product access, candidate review) refused until the next full
login happened to rewrite the pointer. #7232 had to route around the symptom
with a verified-session tenant fallback for PC dispatch.

Fix contract pinned here:

1. expired pointer + the request's own valid session -> the pointer is
   re-validated against that session, rewritten to it, and resolution
   succeeds;
2. another user's session (different canonical subject) and another
   product's session are still refused 403 with the pointer untouched;
3. when the refresh itself fails (inactive current session, authority
   failure), the original error is raised unchanged so the #7232
   verified-session tenant fallback keeps working;
4. a pointer write failure never blocks an authority-validated session (the
   row is non-authoritative by design);
5. an active pointer keeps today's behaviour: no rewrite, no extra authority
   round trip for the cookie session.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_shadow import (
    IdentityShadowRecord,
    request_canonical_session_id,
    resolve_refreshed_session,
)
from app.oracle_mesh_read_return_routes import _dispatch_workspace_id

NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
USER = "usr_" + "a" * 32
SUBJECT = "sub_" + "b" * 32
OTHER_SUBJECT = "sub_" + "e" * 32
TENANT = "tenant-7233"
OLD_SESSION = "authsession:b62:old"
NEW_SESSION = "authsession:b62:new"

SESSION_SECRET = "shadow-refresh-test-secret-not-a-real-credential-000"


def _snapshot(
    session_id: str,
    *,
    subject_id: str = SUBJECT,
    product_id: str = "b62",
    state: AuthSessionState = AuthSessionState.ACTIVE,
    revision: int = 1,
    expires_at: datetime | None = None,
    tenant_id: str | None = TENANT,
) -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id=session_id,
        product_id=product_id,
        subject=CanonicalSubjectRef(SubjectType.USER, subject_id),
        issued_at=NOW - timedelta(hours=2),
        expires_at=expires_at or (NOW + timedelta(hours=1)),
        state=state,
        revision=revision,
        tenant_id=tenant_id,
    )


def _shadow(auth_session_id: str = OLD_SESSION) -> IdentityShadowRecord:
    return IdentityShadowRecord(
        product_user_id=USER,
        canonical_subject_id=SUBJECT,
        auth_session_id=auth_session_id,
        session_revision=1,
        session_state="active",
        session_expires_at=NOW + timedelta(hours=1),
        observed_at=NOW - timedelta(hours=1),
    )


class _Store:
    def __init__(self, record: IdentityShadowRecord, *, fail_write: bool = False) -> None:
        self.record = record
        self.fail_write = fail_write
        self.saved: list[object] = []

    async def load_projection(self, product_user_id: str):
        assert product_user_id == USER
        return self.record

    async def save_projection(self, bridged) -> None:
        if self.fail_write:
            raise RuntimeError("d1 write failed")
        self.saved.append(bridged)
        session = bridged.auth_session
        self.record = IdentityShadowRecord(
            product_user_id=bridged.product_user_id,
            canonical_subject_id=session.subject.subject_id,
            auth_session_id=session.session_id,
            session_revision=session.revision,
            session_state=session.state.value,
            session_expires_at=session.expires_at,
            observed_at=NOW,
        )


class _Authority:
    def __init__(self, sessions: dict[str, AuthSessionSnapshot]) -> None:
        self.sessions = sessions
        self.calls: list[str] = []

    def resolve_auth_session(self, *, session_id: str) -> AuthSessionSnapshot:
        self.calls.append(session_id)
        session = self.sessions.get(session_id)
        if session is None:
            raise RuntimeError("unknown session")
        return session


# --------------------------------------------------------------- contract 1


def test_expired_pointer_is_repointed_at_the_request_session():
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
        NEW_SESSION: _snapshot(NEW_SESSION, revision=1),
    })
    store = _Store(_shadow(OLD_SESSION))

    session = asyncio.run(resolve_refreshed_session(
        authority=authority, store=store, product_user_id=USER,
        now=NOW, current_session_id=NEW_SESSION,
    ))

    assert session.session_id == NEW_SESSION
    assert session.tenant_id == TENANT
    # the dead pointer session was read first, then the request's session
    assert authority.calls == [OLD_SESSION, NEW_SESSION]
    assert len(store.saved) == 1
    saved = store.saved[0]
    assert saved.product_user_id == USER
    assert saved.auth_session.session_id == NEW_SESSION
    # the pointer now names the session that actually made the request
    assert store.record.auth_session_id == NEW_SESSION


def test_refresh_is_skipped_when_the_cookie_session_is_the_same_dead_session():
    """The cookie carrying the pointer's own dead session cannot refresh it:
    there is no valid session to re-point at, so the 401 stands."""
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
    })
    store = _Store(_shadow(OLD_SESSION))

    with pytest.raises(IdentityBridgeError) as excinfo:
        asyncio.run(resolve_refreshed_session(
            authority=authority, store=store, product_user_id=USER,
            now=NOW, current_session_id=OLD_SESSION,
        ))
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "control_plane_session_inactive"
    assert store.saved == []


# --------------------------------------------------------------- contract 2


def test_another_users_session_is_still_refused_and_the_pointer_is_untouched():
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
        NEW_SESSION: _snapshot(NEW_SESSION, subject_id=OTHER_SUBJECT),
    })
    store = _Store(_shadow(OLD_SESSION))

    with pytest.raises(IdentityBridgeError) as excinfo:
        asyncio.run(resolve_refreshed_session(
            authority=authority, store=store, product_user_id=USER,
            now=NOW, current_session_id=NEW_SESSION,
        ))
    assert excinfo.value.status_code == 403
    assert excinfo.value.code == "control_plane_session_mismatch"
    assert store.saved == []
    assert store.record.auth_session_id == OLD_SESSION


def test_another_products_session_is_still_refused():
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
        NEW_SESSION: _snapshot(NEW_SESSION, product_id="b54-padiem-claw"),
    })
    store = _Store(_shadow(OLD_SESSION))

    with pytest.raises(IdentityBridgeError) as excinfo:
        asyncio.run(resolve_refreshed_session(
            authority=authority, store=store, product_user_id=USER,
            now=NOW, current_session_id=NEW_SESSION,
        ))
    assert excinfo.value.status_code == 403
    assert excinfo.value.code == "control_plane_session_mismatch"
    assert store.saved == []


def test_a_non_user_subject_is_still_refused():
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
        NEW_SESSION: _snapshot(NEW_SESSION),  # replaced below with ACCOUNT type
    })
    authority.sessions[NEW_SESSION] = AuthSessionSnapshot(
        session_id=NEW_SESSION, product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.ACCOUNT, SUBJECT),
        issued_at=NOW - timedelta(hours=2), expires_at=NOW + timedelta(hours=1),
    )
    store = _Store(_shadow(OLD_SESSION))

    with pytest.raises(IdentityBridgeError) as excinfo:
        asyncio.run(resolve_refreshed_session(
            authority=authority, store=store, product_user_id=USER,
            now=NOW, current_session_id=NEW_SESSION,
        ))
    assert excinfo.value.status_code == 403
    assert store.saved == []


# --------------------------------------------------------------- contract 3


def test_refresh_failure_keeps_the_original_inactive_error():
    """The request's own session is dead too: the 401 stands unchanged, so
    every #7232-style downstream fallback keeps seeing the same refusal."""
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
        NEW_SESSION: _snapshot(NEW_SESSION, expires_at=NOW - timedelta(minutes=1)),
    })
    store = _Store(_shadow(OLD_SESSION))

    with pytest.raises(IdentityBridgeError) as excinfo:
        asyncio.run(resolve_refreshed_session(
            authority=authority, store=store, product_user_id=USER,
            now=NOW, current_session_id=NEW_SESSION,
        ))
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "control_plane_session_inactive"
    assert store.saved == []


def test_refresh_authority_failure_stays_a_503():
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
        # NEW_SESSION missing -> the authority raises for it
    })
    store = _Store(_shadow(OLD_SESSION))

    with pytest.raises(IdentityBridgeError) as excinfo:
        asyncio.run(resolve_refreshed_session(
            authority=authority, store=store, product_user_id=USER,
            now=NOW, current_session_id=NEW_SESSION,
        ))
    assert excinfo.value.status_code == 503
    assert excinfo.value.code == "control_plane_session_unavailable"
    assert store.saved == []


def test_the_7232_tenant_fallback_still_answers_when_the_refresh_fails():
    """End to end over the #7232 seam: the memory workspace resolution fails
    on the stale pointer (no refresh possible), and the dispatch workspace
    still comes from the verified session's tenant."""
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
    })
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="shadow-refresh-test.apps.googleusercontent.com",
        google_client_secret="synthetic-not-real",
        session_secret=SESSION_SECRET,
    )
    state = SimpleNamespace(
        settings=settings,
        history_store=object(),
        identity_shadow_store=_Store(_shadow(OLD_SESSION)),
        control_plane_identity_authority=authority,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace(), cookies={})
    session = SimpleNamespace(
        session_id="sess-verified", product_id="b62",
        subject=SimpleNamespace(subject_id=SUBJECT),
        tenant_id=TENANT, is_active=lambda *, now: True,
    )

    workspace = asyncio.run(_dispatch_workspace_id(request, USER, session))
    assert workspace == TENANT


# --------------------------------------------------------------- contract 4


def test_a_failed_pointer_write_does_not_block_the_validated_session():
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
        NEW_SESSION: _snapshot(NEW_SESSION),
    })
    store = _Store(_shadow(OLD_SESSION), fail_write=True)

    session = asyncio.run(resolve_refreshed_session(
        authority=authority, store=store, product_user_id=USER,
        now=NOW, current_session_id=NEW_SESSION,
    ))
    assert session.session_id == NEW_SESSION


# --------------------------------------------------------------- contract 5


def test_an_active_pointer_keeps_today_behaviour_without_a_rewrite():
    authority = _Authority({OLD_SESSION: _snapshot(OLD_SESSION)})
    store = _Store(_shadow(OLD_SESSION))

    session = asyncio.run(resolve_refreshed_session(
        authority=authority, store=store, product_user_id=USER,
        now=NOW, current_session_id=NEW_SESSION,
    ))
    assert session.session_id == OLD_SESSION
    assert authority.calls == [OLD_SESSION]
    assert store.saved == []


def test_no_current_session_id_keeps_the_original_error():
    authority = _Authority({
        OLD_SESSION: _snapshot(OLD_SESSION, expires_at=NOW - timedelta(minutes=1)),
    })
    store = _Store(_shadow(OLD_SESSION))

    with pytest.raises(IdentityBridgeError) as excinfo:
        asyncio.run(resolve_refreshed_session(
            authority=authority, store=store, product_user_id=USER, now=NOW,
        ))
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "control_plane_session_inactive"


# ------------------------------------------------------- cookie sid helper


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock", auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="shadow-refresh-test.apps.googleusercontent.com",
        google_client_secret="synthetic-not-real",
        session_secret=SESSION_SECRET,
    )


def test_request_canonical_session_id_reads_the_signed_cookie_sid():
    token = create_session_token(_settings(), USER, canonical_session_id=NEW_SESSION)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=_settings())),
        cookies={SESSION_COOKIE: token},
    )
    assert request_canonical_session_id(request) == NEW_SESSION


def test_request_canonical_session_id_returns_none_without_a_sid_or_a_cookie():
    token = create_session_token(_settings(), USER)
    bound = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=_settings())),
        cookies={SESSION_COOKIE: token},
    )
    assert request_canonical_session_id(bound) is None

    unbound = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=_settings())),
        cookies={},
    )
    assert request_canonical_session_id(unbound) is None

    forged = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=_settings())),
        cookies={SESSION_COOKIE: "not-a-signed-token"},
    )
    assert request_canonical_session_id(forged) is None
