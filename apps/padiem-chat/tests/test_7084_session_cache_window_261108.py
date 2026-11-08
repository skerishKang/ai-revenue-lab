"""#7084 — reuse a successful canonical session check longer, and drop it on revocation.

The COM2 journal over 7 days recorded 7,736 ``session_revocation_check`` timings,
420 upstream ``resolve_auth_session`` calls (mean 1,217 ms) and 783 checks over
500 ms. These regressions pin the fix without weakening #5225:

* a successful session check is reused for the configured session window
  (300 s by default) instead of the 30 s shared-account window;
* the shared account mapping keeps its own short window — the change is scoped
  to the guard's 'legacy' rows;
* every revocation event this host serves (logout, account deletion) deletes the
  entry before it answers, so the next request is refused with no clock advance;
* an expired entry reaches the authority again, and an authority outage keeps
  the pre-existing fail-closed verdict;
* a refusal is never cached, so the #7176 canonical-session renewal takes effect
  on the very next request;
* the host wires the window from ``PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS``.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import local_cpython
from app.auth import SESSION_COOKIE, create_session_token
from app.auth_validation_cache import SqliteAuthValidationCache, invalidate_auth_cache
from app.config import Settings
from app.d1_sqlite import SqliteD1, connect
from app.session_revocation_guard import SessionRevocationGuardMiddleware
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

UID = 'usr_' + 'a' * 32
SID = 'sess_' + '1' * 32
OTHER_SID = 'sess_' + '2' * 32
SUBJECT = 'sub_' + 'c' * 32
MAPPING_SECONDS = 30
WINDOW_SECONDS = 300
REFRESH_AHEAD_SECONDS = 5


@pytest.fixture
def cache(tmp_path):
    path = tmp_path / 'auth.sqlite3'
    writer = connect(str(path))
    migration = Path(__file__).parents[1] / 'migrations/087_auth_validation_cache.sql'
    writer.executescript(migration.read_text())
    clock = [datetime.now(timezone.utc).timestamp()]
    instance = SqliteAuthValidationCache(
        SqliteD1(writer),
        ttl_seconds=MAPPING_SECONDS,
        session_ttl_seconds=WINDOW_SECONDS,
        refresh_ahead_seconds=REFRESH_AHEAD_SECONDS,
        clock=lambda: clock[0],
    )
    yield instance, clock, writer
    writer.close()


class AuthorityError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Authority:
    """The private identity authority surface the guard calls."""

    def __init__(self, delay: float = 0.0) -> None:
        now = datetime.now(timezone.utc)
        self.sessions = {
            sid: AuthSessionSnapshot(
                session_id=sid,
                product_id='b62',
                subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
                issued_at=now,
                expires_at=now + timedelta(hours=1),
            )
            for sid in (SID, OTHER_SID)
        }
        self.calls = 0
        self.delay = delay
        self.unavailable = False

    async def resolve_auth_session(self, *, session_id):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.unavailable:
            raise RuntimeError('synthetic-private-error')
        session = self.sessions.get(session_id)
        if session is None:
            raise AuthorityError('canonical_auth_session_not_found')
        return session


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode='mock',
        auth_mode='password',
        public_base_url='https://chat.example.invalid',
        session_secret='synthetic-session-window-secret-not-production',
    )


def request(cache, authority, *, uid=UID, sid=SID) -> Request:
    config = settings()
    token = create_session_token(config, uid, canonical_session_id=sid)
    return Request(
        {
            'type': 'http',
            'method': 'GET',
            'path': '/api/claw/inbox',
            'query_string': b'',
            'headers': [(b'cookie', (SESSION_COOKIE + '=' + token).encode())],
            'app': SimpleNamespace(
                state=SimpleNamespace(
                    settings=config,
                    control_plane_identity_authority=authority,
                    auth_validation_cache=cache,
                )
            ),
        }
    )


def cache_request(cache, authority):
    """The object ``invalidate_auth_cache`` needs from a live request."""
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                control_plane_identity_authority=authority,
                auth_validation_cache=cache,
            )
        )
    )


async def _verdict(cache, authority, **kwargs):
    return await SessionRevocationGuardMiddleware(None).resolve_verdict(
        request(cache, authority, **kwargs).scope
    )


@pytest.mark.asyncio
async def test_one_authority_call_serves_the_whole_session_window(cache):
    instance, clock, _ = cache
    authority = Authority()

    for _ in range(WINDOW_SECONDS - REFRESH_AHEAD_SECONDS):
        verdict = await _verdict(instance, authority)
        assert verdict.authenticated is True
        clock[0] += 1

    assert authority.calls == 1


@pytest.mark.asyncio
async def test_a_logout_refuses_the_stored_session_with_no_clock_advance(cache):
    instance, _, _ = cache
    authority = Authority()
    assert (await _verdict(instance, authority)).authenticated is True

    authority.sessions[SID] = replace(
        authority.sessions[SID], state=AuthSessionState.REVOKED, revision=2
    )
    await invalidate_auth_cache(cache_request(instance, authority), user_id=UID, session_id=SID)

    verdict = await _verdict(instance, authority)
    assert verdict.authenticated is False
    assert verdict.reason == 'revoked'
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_an_account_deletion_refuses_every_session_of_the_account_at_once(cache):
    instance, _, _ = cache
    authority = Authority()
    assert (await _verdict(instance, authority, sid=SID)).authenticated is True
    assert (await _verdict(instance, authority, sid=OTHER_SID)).authenticated is True
    assert authority.calls == 2

    for sid in (SID, OTHER_SID):
        authority.sessions[sid] = replace(
            authority.sessions[sid], state=AuthSessionState.REVOKED, revision=2
        )
    # account_deletion.py deletes the rows first and then invalidates the caches.
    await invalidate_auth_cache(cache_request(instance, authority), user_id=UID)

    for sid in (SID, OTHER_SID):
        verdict = await _verdict(instance, authority, sid=sid)
        assert verdict.authenticated is False
        assert verdict.reason == 'revoked'
    assert authority.calls == 4


@pytest.mark.asyncio
async def test_the_window_expiry_asks_the_authority_again(cache):
    instance, clock, _ = cache
    authority = Authority()
    assert (await _verdict(instance, authority)).authenticated is True

    clock[0] += WINDOW_SECONDS + 1
    assert (await _verdict(instance, authority)).authenticated is True
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_an_authority_outage_keeps_the_existing_verdict(cache):
    instance, clock, _ = cache
    authority = Authority()
    assert (await _verdict(instance, authority)).authenticated is True

    authority.unavailable = True
    # A still-valid entry answers, exactly as before the window change.
    assert (await _verdict(instance, authority)).authenticated is True
    assert authority.calls == 1

    clock[0] += WINDOW_SECONDS + 1
    verdict = await _verdict(instance, authority)
    assert verdict.authenticated is False
    assert verdict.reason == 'unavailable'
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_a_missing_session_is_not_cached_so_the_renewal_applies_at_once(cache):
    instance, clock, _ = cache
    authority = Authority()
    missing = authority.sessions.pop(SID)

    # #7161: the canonical session had expired and nothing had re-established it.
    verdict = await _verdict(instance, authority)
    assert verdict.authenticated is False
    assert verdict.reason == 'revoked'

    # #7176 re-establishes it behind the next verified request.
    authority.sessions[SID] = missing
    clock[0] += 1
    verdict = await _verdict(instance, authority)
    assert verdict.authenticated is True
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_the_shared_account_mapping_keeps_its_short_window(cache):
    instance, clock, _ = cache
    calls = []

    async def loader():
        calls.append(clock[0])
        return UID, clock[0] + 10_000

    assert await instance.get_or_load('shared', SUBJECT, SID, loader) == UID
    clock[0] += MAPPING_SECONDS + 1
    assert await instance.get_or_load('shared', SUBJECT, SID, loader) == UID

    assert len(calls) == 2
    assert instance.session_ttl_seconds == WINDOW_SECONDS


@pytest.mark.parametrize('configured,expected', [(None, 300), ('60', 60), ('0', MAPPING_SECONDS)])
def test_the_host_wires_the_session_window_from_its_env(
        tmp_path, monkeypatch, configured, expected):
    for name, value in {
        'PADIEM_LOCAL_DEV': '1', 'PADIEM_CHAT_RUNTIME_MODE': 'mock',
        'PADIEM_CHAT_AUTH_MODE': 'off', 'PADIEM_CHAT_WEB_PROVIDER': 'off',
        'PADIEM_CHAT_PUBLIC_BASE_URL': 'http://127.0.0.1:8773',
        'PADIEM_CHAT_LOCAL_DATA_DIR': str(tmp_path),
        'PADIEM_CHAT_SESSION_SECRET': 'test-local-secret-0123456789abcdef',
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('PC_QUEUE_BACKEND', raising=False)
    if configured is None:
        monkeypatch.delenv('PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS', raising=False)
    else:
        monkeypatch.setenv('PADIEM_CHAT_AUTH_SESSION_CACHE_SECONDS', configured)
    databases = []
    original = local_cpython.SqliteD1

    def capture(*args, **kwargs):
        db = original(*args, **kwargs)
        databases.append(db)
        return db

    monkeypatch.setattr(local_cpython, 'SqliteD1', capture)
    app = local_cpython.build_app()
    db = databases[0]
    cache = app.state.auth_validation_cache
    assert cache.session_ttl_seconds == expected
    assert cache.ttl_seconds == MAPPING_SECONDS
    db.connection.close()


# --- #7207: the signed account-delete RPC ends the window too -----------------

PASSWORD_RPC_SECRET = 'chat-test-password-rpc-secret-value-000000'
NL = bytes((10,))


class _Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return _Statement(self.db, self.sql, params)

    async def first(self):
        if 'FROM users WHERE id' in self.sql:
            return {'id': self.params[0], 'provider_subject': None}
        return None

    async def run(self):
        return SimpleNamespace(results=[], meta={'changes': 0})


class _AccountStore:
    """The account store side of ``/internal/account-delete``.

    The deletion SQL itself is #6659's contract
    (``tests/test_account_deletion_261103.py``); this stand-in records that the
    route reached its batch, so the assertions here stay about the cache and the
    next request.
    """

    def __init__(self):
        self.batches = 0

    def prepare(self, sql):
        return _Statement(self, sql)

    async def batch(self, statements):
        self.batches += 1
        return [SimpleNamespace(results=[], meta={'changes': 0}) for _ in statements]


class _ServiceIds:
    async def consume_service_id(self, service_id, expires_at):
        return True


def _rpc_scope(instance, authority, account_store, *, at=None, body=None):
    raw = json.dumps(
        body if body is not None else {'product_user_id': UID},
        separators=(',', ':'), sort_keys=True).encode('utf-8')
    at_value = int(time.time()) if at is None else at
    service_id = str(uuid.uuid4())
    signed = NL.join((
        b'v2', b'POST', b'/internal/account-delete',
        str(at_value).encode('ascii'), service_id.encode('utf-8'), raw,
    ))
    proof = 'v2=' + hmac.new(
        PASSWORD_RPC_SECRET.encode('utf-8'), signed, hashlib.sha256).hexdigest()
    sent = {'done': False}

    async def receive():
        if sent['done']:
            return {'type': 'http.disconnect'}
        sent['done'] = True
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    config = Settings.from_values(
        runtime_mode='mock',
        auth_mode='password',
        public_base_url='https://chat.example.invalid',
        session_secret='synthetic-session-window-secret-not-production',
        password_rpc_secret=PASSWORD_RPC_SECRET,
    )
    return {
        'type': 'http', 'http_version': '1.1', 'method': 'POST',
        'scheme': 'https', 'server': ('chat.example.test', 443),
        'path': '/internal/account-delete',
        'raw_path': b'/internal/account-delete',
        'query_string': b'',
        'headers': [
            (b'content-type', b'application/json'),
            (b'content-length', str(len(raw)).encode('ascii')),
            (b'x-padiem-service-at', str(at_value).encode('ascii')),
            (b'x-padiem-service-id', service_id.encode('utf-8')),
            (b'x-padiem-service-proof', proof.encode('ascii')),
        ],
        'receive': receive,
        'app': SimpleNamespace(state=SimpleNamespace(
            settings=config,
            control_plane_identity_authority=authority,
            auth_validation_cache=instance,
            history_store=_ServiceIds(),
            account_data_db=account_store,
        )),
    }


@pytest.mark.asyncio
async def test_the_signed_account_delete_rpc_ends_every_session_at_once(cache):
    from app.account_deletion import chat_account_delete_rpc

    instance, clock, writer = cache
    authority = Authority()
    store = _AccountStore()
    for sid in (SID, OTHER_SID):
        assert (await _verdict(instance, authority, sid=sid)).authenticated is True
    assert authority.calls == 2

    scope = _rpc_scope(instance, authority, store)
    response = await chat_account_delete_rpc(Request(scope, scope['receive']))

    assert response.status_code == 200
    assert json.loads(bytes(response.body)) == {
        'ok': True, 'deleted': True, 'already_deleted': False}
    assert store.batches == 1

    # The tombstone path deletes the rows; the window cannot keep them alive.
    remaining = writer.execute(
        'SELECT COUNT(*) FROM auth_validation_cache WHERE owner_id=?', (UID,)).fetchone()[0]
    assert remaining == 0
    revision = writer.execute(
        'SELECT revision FROM auth_validation_cache_revision WHERE id=1').fetchone()[0]
    assert revision >= 1

    for sid in (SID, OTHER_SID):
        authority.sessions[sid] = replace(
            authority.sessions[sid], state=AuthSessionState.REVOKED, revision=2)
        verdict = await _verdict(instance, authority, sid=sid)
        assert verdict.authenticated is False
        assert verdict.reason == 'revoked'
    assert authority.calls == 4
