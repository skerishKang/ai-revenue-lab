"""Short-lived validation reuse without cross-user or logout leakage."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.auth_routes import _revoke_canonical_session, _revoke_all_canonical_sessions
from app.auth_validation_cache import AuthValidationInvalidated, SqliteAuthValidationCache
from app.config import Settings
from app.d1_sqlite import SqliteD1, connect
from app.session_revocation_guard import SessionRevocationGuardMiddleware
from app.shared_auth_adapter import SharedAuthUnavailable, SharedChatAuth
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

UID = 'usr_' + 'a' * 32
OTHER_UID = 'usr_' + 'b' * 32
SID = 'sess_' + '1' * 32
OTHER_SID = 'sess_' + '2' * 32
SUBJECT = 'sub_' + 'c' * 32


@pytest.fixture
def caches(tmp_path):
    path = tmp_path / 'auth.sqlite3'
    writer1, writer2 = connect(str(path)), connect(str(path))
    migration = Path(__file__).parents[1] / 'migrations/087_auth_validation_cache.sql'
    writer1.executescript(migration.read_text())
    clock = [datetime.now(timezone.utc).timestamp()]
    first = SqliteAuthValidationCache(SqliteD1(writer1), clock=lambda: clock[0])
    second = SqliteAuthValidationCache(SqliteD1(writer2), clock=lambda: clock[0])
    yield first, second, clock, writer1
    writer1.close()
    writer2.close()


def settings():
    return Settings.from_values(runtime_mode='mock', auth_mode='password',
        public_base_url='https://chat.example.invalid',
        session_secret='synthetic-cache-test-session-secret-not-production')


class Authority:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.sessions = {sid: AuthSessionSnapshot(session_id=sid, product_id='b62',
            subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
            issued_at=now, expires_at=now + timedelta(hours=1)) for sid in (SID, OTHER_SID)}
        self.calls = 0
        self.unavailable = False

    async def resolve_auth_session(self, *, session_id):
        self.calls += 1
        if self.unavailable:
            raise RuntimeError('synthetic-private-error')
        await asyncio.sleep(0)
        return self.sessions[session_id]

    async def revoke_auth_session(self, *, product_id, session_id):
        self.sessions[session_id] = replace(self.sessions[session_id], state=AuthSessionState.REVOKED)

    async def revoke_all_auth_sessions(self, *, product_id, product_user_id):
        for sid in self.sessions:
            self.sessions[sid] = replace(self.sessions[sid], state=AuthSessionState.REVOKED)


def request(cache, authority=None, uid=UID, sid=SID, *, extra_cookie=''):
    config = settings()
    token = create_session_token(config, uid, canonical_session_id=sid)
    return Request({'type': 'http', 'method': 'GET', 'path': '/api/claw/inbox',
        'query_string': b'', 'headers': [(b'cookie', (SESSION_COOKIE + '=' + token + extra_cookie).encode())],
        'app': SimpleNamespace(state=SimpleNamespace(settings=config,
            control_plane_identity_authority=authority, auth_validation_cache=cache))})


@pytest.mark.asyncio
async def test_guard_reuses_same_session_across_two_worker_connections(caches):
    first, second, clock, _ = caches
    authority, guard = Authority(), SessionRevocationGuardMiddleware(None)
    for cache in (first, second, first, second, first):
        assert (await guard.resolve_verdict(request(cache, authority).scope)).authenticated
    assert authority.calls == 1
    authority.unavailable = True
    clock[0] += 31
    verdict = await guard.resolve_verdict(request(second, authority).scope)
    assert not verdict.authenticated and verdict.reason == 'unavailable'
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_user_and_session_are_both_cache_keys(caches):
    first, second, _, connection = caches
    calls = []
    async def load(uid):
        calls.append(uid)
        return uid, first.clock() + 900
    assert await first.get_or_load('legacy', UID, SID, lambda: load(UID)) == UID
    assert await second.get_or_load('legacy', OTHER_UID, SID, lambda: load(OTHER_UID)) == OTHER_UID
    assert await first.get_or_load('legacy', UID, OTHER_SID, lambda: load(UID)) == UID
    assert calls == [UID, OTHER_UID, UID]
    rows = connection.execute('SELECT * FROM auth_validation_cache').fetchall()
    assert len(rows) == 3
    dump = '\n'.join(connection.iterdump())
    assert SID not in dump and OTHER_SID not in dump
    assert hashlib.sha256(SID.encode()).hexdigest() in dump


@pytest.mark.asyncio
async def test_same_process_parallel_misses_share_one_authority_call(caches):
    first = caches[0]
    calls = []
    async def load():
        calls.append(True)
        await asyncio.sleep(.01)
        return UID, first.clock() + 900
    results = await asyncio.gather(*(first.get_or_load('legacy', UID, SID, load) for _ in range(5)))
    assert results == [UID] * 5 and len(calls) == 1


@pytest.mark.asyncio
async def test_invalidation_fences_a_lookup_started_in_another_worker(caches):
    first, second, _, connection = caches
    started, finish = asyncio.Event(), asyncio.Event()
    async def load():
        started.set()
        await finish.wait()
        return UID, first.clock() + 900
    pending = asyncio.create_task(first.get_or_load('legacy', UID, SID, load))
    await started.wait()
    await second.invalidate_user(UID)
    finish.set()
    with pytest.raises(AuthValidationInvalidated):
        await pending
    assert connection.execute('SELECT COUNT(*) FROM auth_validation_cache').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_logout_invalidates_other_worker_but_keeps_second_device(caches):
    first, second, _, _ = caches
    authority, guard = Authority(), SessionRevocationGuardMiddleware(None)
    assert (await guard.resolve_verdict(request(first, authority).scope)).authenticated
    assert (await guard.resolve_verdict(request(first, authority, sid=OTHER_SID).scope)).authenticated
    assert authority.calls == 2
    assert await _revoke_canonical_session(request(second, authority)) is None
    assert not (await guard.resolve_verdict(request(first, authority).scope)).authenticated
    assert (await guard.resolve_verdict(request(second, authority, sid=OTHER_SID).scope)).authenticated
    assert authority.calls == 3


@pytest.mark.asyncio
async def test_password_change_revokes_all_cached_sessions(caches):
    first, second, _, _ = caches
    authority, guard = Authority(), SessionRevocationGuardMiddleware(None)
    for sid in (SID, OTHER_SID):
        assert (await guard.resolve_verdict(request(first, authority, sid=sid).scope)).authenticated
    assert await _revoke_all_canonical_sessions(request(second, authority), user_id=UID, strict=True) is None
    for sid in (SID, OTHER_SID):
        assert not (await guard.resolve_verdict(request(first, authority, sid=sid).scope)).authenticated


@pytest.mark.asyncio
async def test_cache_cannot_outlive_authority_expiry(caches):
    first, second, clock, _ = caches
    async def load():
        return UID, clock[0] + 5
    await first.get_or_load('legacy', UID, SID, load)
    clock[0] += 6
    async def failed():
        raise RuntimeError('authority unavailable')
    with pytest.raises(RuntimeError):
        await second.get_or_load('legacy', UID, SID, failed)


@pytest.mark.asyncio
async def test_cache_is_reused_by_a_separate_python_process(caches):
    first, _, clock, connection = caches
    async def load():
        return UID, clock[0] + 300
    await first.get_or_load('legacy', UID, SID, load)
    path = connection.execute('PRAGMA database_list').fetchone()[2]
    script = '''
import asyncio, sys
from app.auth_validation_cache import SqliteAuthValidationCache
from app.d1_sqlite import SqliteD1, connect
connection = connect(sys.argv[1])
cache = SqliteAuthValidationCache(SqliteD1(connection), clock=lambda:float(sys.argv[2]))
async def miss():
    raise AssertionError('cache was not shared across processes')
async def check():
    value = await cache.get_or_load('legacy', 'usr_'+'a'*32, 'sess_'+'1'*32, miss)
    assert value == 'usr_'+'a'*32
asyncio.run(check())
connection.close()
print('shared_cache=pass')
'''
    result = subprocess.run([sys.executable, '-c', script, path, str(clock[0])],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'shared_cache=pass'


class SharedVerifier:
    def __init__(self, clock, *, with_session=True):
        self.clock, self.with_session = clock, with_session
    async def verify(self, token):
        if token not in ('synthetic-one', 'synthetic-two'):
            raise ValueError('invalid token')
        claims = {'accountId': SUBJECT, 'expiresAt': int(self.clock() + 300)}
        if self.with_session:
            claims['sessionId'] = SID if token == 'synthetic-one' else OTHER_SID
        return claims


class SharedAuthority:
    calls = 0
    async def resolve_product_user_for_subject(self, **kwargs):
        assert kwargs == {'product_id': 'b62', 'canonical_subject_id': SUBJECT}
        self.calls += 1
        return UID


@pytest.mark.asyncio
async def test_shared_auth_uses_shared_session_cache_and_scoped_logout(caches):
    first, second, _, connection = caches
    authority = SharedAuthority()
    def auth():
        return SharedChatAuth(verifier=SharedVerifier(first.clock), authority=authority,
                              legacy=lambda _: None, clock=first.clock)
    worker1, worker2 = auth(), auth()
    assert await worker1.user_id(request(first), 'synthetic-one') == UID
    assert await worker2.user_id(request(second), 'synthetic-one') == UID
    assert await worker2.user_id(request(second), 'synthetic-two') == UID
    assert authority.calls == 2
    await worker1.invalidate_session(request(first), 'synthetic-one')
    assert await worker2.user_id(request(second), 'synthetic-one') == UID
    assert await worker1.user_id(request(first), 'synthetic-two') == UID
    assert authority.calls == 3
    dump = '\n'.join(connection.iterdump())
    assert 'synthetic-one' not in dump and 'synthetic-two' not in dump
    assert worker1._mapping == worker2._mapping == {}
    with pytest.raises(SharedAuthUnavailable):
        await worker1.user_id(request(first), 'forged')


@pytest.mark.asyncio
async def test_unsigned_missing_session_id_is_never_cached(caches):
    first, _, _, connection = caches
    authority = SharedAuthority()
    auth = SharedChatAuth(verifier=SharedVerifier(first.clock, with_session=False), authority=authority,
                          legacy=lambda _: None, clock=first.clock)
    for _ in range(2):
        assert await auth.user_id(request(first), 'synthetic-one') == UID
    assert authority.calls == 2
    assert connection.execute('SELECT COUNT(*) FROM auth_validation_cache').fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('with_session', [True, False])
async def test_explicit_host_cache_off_never_uses_process_mapping(caches, with_session):
    clock = caches[0].clock
    authority = SharedAuthority()
    auth = SharedChatAuth(verifier=SharedVerifier(clock, with_session=with_session),
                          authority=authority, legacy=lambda _: None, clock=clock)
    auth._mapping[SUBJECT] = (OTHER_UID, clock() + 300)
    req = request(None)  # The host's PADIEM_CHAT_AUTH_CACHE_SECONDS=0 composition.
    for _ in range(2):
        assert await auth.user_id(req, 'synthetic-one') == UID
    assert authority.calls == 2
    assert auth._mapping == {}


@pytest.mark.asyncio
async def test_worker_without_host_cache_setting_keeps_existing_mapping(caches):
    clock = caches[0].clock
    authority = SharedAuthority()
    auth = SharedChatAuth(verifier=SharedVerifier(clock), authority=authority,
                          legacy=lambda _: None, clock=clock)
    req = request(None)
    del req.app.state.auth_validation_cache
    for _ in range(2):
        assert await auth.user_id(req, 'synthetic-one') == UID
    assert authority.calls == 1 and auth._mapping[SUBJECT][0] == UID


@pytest.mark.asyncio
async def test_shared_logout_route_invalidates_before_reporting_success(caches):
    from app.shared_login_flow import SharedLoginFlow, ACCESS_COOKIE, REFRESH_COOKIE
    first, second, _, connection = caches
    auth = SharedChatAuth(verifier=SharedVerifier(first.clock), authority=SharedAuthority(),
                          legacy=lambda _: None, clock=first.clock)
    await auth.user_id(request(first), 'synthetic-one')
    await auth.user_id(request(first), 'synthetic-two')
    revoked = []
    async def revoke(data):
        revoked.append(True)
    async def assertion(now):
        return 'synthetic-assertion'
    flow = object.__new__(SharedLoginFlow)
    flow.public_base_url = 'https://chat.example.invalid'
    flow.client_id, flow.clock, flow.auth = 'b62', first.clock, auth
    flow.revoke_session, flow._assertion = revoke, assertion
    req = request(second, extra_cookie='; '+ACCESS_COOKIE+'=synthetic-one; '+REFRESH_COOKIE+'=synthetic-refresh')
    req.scope['headers'].append((b'origin', flow.public_base_url.encode()))
    response = await flow.logout(req)
    assert response.status_code == 200 and revoked == [True]
    rows = connection.execute('SELECT session_hash FROM auth_validation_cache').fetchall()
    assert [row[0] for row in rows] == [hashlib.sha256(OTHER_SID.encode()).hexdigest()]


@pytest.mark.asyncio
@pytest.mark.parametrize('has_auth_port', [True, False])
async def test_shared_logout_old_auth_port_discards_configured_cache(caches, has_auth_port):
    from app.shared_login_flow import SharedLoginFlow
    first = caches[0]
    async def load():
        return UID, first.clock() + 300
    await first.get_or_load('legacy', UID, SID, load)
    flow = object.__new__(SharedLoginFlow)
    flow.public_base_url = 'https://chat.example.invalid'
    # The old injected auth protocol has no invalidation method.
    if has_auth_port:
        flow.auth = SimpleNamespace(user_id=lambda *_: UID)
    req = request(first)
    req.scope['headers'].append((b'origin', flow.public_base_url.encode()))
    response = await flow.logout(req)
    assert response.status_code == 200
    assert caches[3].execute('SELECT COUNT(*) FROM auth_validation_cache').fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['assign', 'revoke', 'membership'])
async def test_permission_mutation_routes_invalidate_target_cache(caches, monkeypatch, operation):
    from app import platform_admin_routes, b66_admin_routes
    first, second, _, connection = caches
    async def load(uid):
        return uid, first.clock() + 900
    await first.get_or_load('legacy', UID, SID, lambda: load(UID))
    await first.get_or_load('legacy', OTHER_UID, SID, lambda: load(OTHER_UID))
    req = request(second)
    req.scope['method'] = 'POST'
    req.scope['path_params'] = {'user_id': UID}
    req.scope['headers'].append((b'content-type', b'application/json'))
    async def mutation(**kwargs):
        return SimpleNamespace(public_dict=lambda: {'user_id': UID})
    store = SimpleNamespace(assign=mutation, revoke=mutation, set_access=mutation)
    req.app.state.platform_admin_role_store = store
    async def admin(_):
        return OTHER_UID, None
    monkeypatch.setattr(platform_admin_routes, '_require_super_admin', admin)
    if operation == 'assign':
        async def body(_):
            return {'user_id': UID, 'role': 'ADMIN'}
        monkeypatch.setattr(platform_admin_routes, '_json_body', body)
        response = await platform_admin_routes.platform_admin_role_assign(req)
    elif operation == 'revoke':
        response = await platform_admin_routes.platform_admin_role_revoke(req)
    else:
        async def member_admin(_):
            return store, OTHER_UID, None
        async def member_body(*args, **kwargs):
            return json.dumps({'status': 'approved', 'tier': 'FREE', 'expected_revision': 0}).encode()
        async def set_access(**kwargs):
            return {'user_id': UID}
        store.set_access = set_access
        monkeypatch.setattr(b66_admin_routes, '_admin', member_admin)
        monkeypatch.setattr(b66_admin_routes, 'read_bounded_request_body', member_body)
        response = await b66_admin_routes.b66_admin_member_access(req)
    assert response.status_code == 200
    rows = connection.execute('SELECT product_user_id FROM auth_validation_cache').fetchall()
    assert [row[0] for row in rows] == [OTHER_UID]
