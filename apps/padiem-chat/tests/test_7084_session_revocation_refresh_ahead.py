"""#7084: reload the guard's cached session check behind the response.

The revocation guard used to pay the identity authority call inside the request
that happened to arrive after the cache TTL. These regressions bind the cheaper
shape without weakening #5225:

* repeated requests for one session share a single authority call;
* a still-valid entry inside the refresh margin answers immediately and reloads
  on a background task, so the request does not wait for the authority;
* an expired entry is never served (the revocation bound stays the TTL, and an
  authority outage keeps reporting the same retryable failure);
* a revoked session is refused within the TTL;
* a logout invalidation refuses the stored session immediately, and a reload
  that started before the invalidation cannot repopulate the cache.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.auth_validation_cache import SqliteAuthValidationCache
from app.config import Settings
from app.d1_sqlite import SqliteD1, connect
from app.session_revocation_guard import SessionRevocationGuardMiddleware
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

UID = 'usr_' + 'a' * 32
SID = 'sess_' + '1' * 32
SUBJECT = 'sub_' + 'c' * 32
TTL_SECONDS = 30
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
        ttl_seconds=TTL_SECONDS,
        refresh_ahead_seconds=REFRESH_AHEAD_SECONDS,
        clock=lambda: clock[0],
    )
    yield instance, clock, writer
    writer.close()


class Authority:
    def __init__(self, delay: float = 0.0) -> None:
        now = datetime.now(timezone.utc)
        self.sessions = {
            SID: AuthSessionSnapshot(
                session_id=SID,
                product_id='b62',
                subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
                issued_at=now,
                expires_at=now + timedelta(hours=1),
            )
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
        return self.sessions[session_id]


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode='mock',
        auth_mode='password',
        public_base_url='https://chat.example.invalid',
        session_secret='synthetic-refresh-ahead-session-secret-not-production',
    )


def request(cache, authority) -> Request:
    config = settings()
    token = create_session_token(config, UID, canonical_session_id=SID)
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


async def _verdict(cache, authority):
    return await SessionRevocationGuardMiddleware(None).resolve_verdict(
        request(cache, authority).scope
    )


@pytest.mark.asyncio
async def test_consecutive_requests_share_one_authority_call(cache):
    instance, clock, _ = cache
    authority = Authority()

    for _ in range(10):
        verdict = await _verdict(instance, authority)
        assert verdict.authenticated is True
        clock[0] += 1

    assert authority.calls == 1


@pytest.mark.asyncio
async def test_refresh_ahead_answers_before_the_authority_finishes(cache):
    instance, clock, _ = cache
    authority = Authority()
    assert (await _verdict(instance, authority)).authenticated is True
    assert authority.calls == 1

    authority.delay = 0.4
    clock[0] += TTL_SECONDS - REFRESH_AHEAD_SECONDS + 1  # inside the margin, still valid

    started = time.perf_counter()
    verdict = await _verdict(instance, authority)
    elapsed = time.perf_counter() - started

    assert verdict.authenticated is True
    assert elapsed < 0.2
    await asyncio.sleep(0.5)
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_an_expired_entry_is_never_served(cache):
    instance, clock, _ = cache
    authority = Authority()
    assert (await _verdict(instance, authority)).authenticated is True

    authority.unavailable = True
    clock[0] += TTL_SECONDS + 1

    verdict = await _verdict(instance, authority)
    assert verdict.authenticated is False
    assert verdict.reason == 'unavailable'


@pytest.mark.asyncio
async def test_a_revoked_session_is_refused_within_the_ttl(cache):
    instance, clock, _ = cache
    authority = Authority()
    assert (await _verdict(instance, authority)).authenticated is True

    authority.sessions[SID] = replace(
        authority.sessions[SID], state=AuthSessionState.REVOKED, revision=2
    )
    clock[0] += TTL_SECONDS + 1

    verdict = await _verdict(instance, authority)
    assert verdict.authenticated is False
    assert verdict.reason == 'revoked'


@pytest.mark.asyncio
async def test_logout_invalidation_refuses_the_stored_session_immediately(cache):
    instance, _, _ = cache
    authority = Authority()
    assert (await _verdict(instance, authority)).authenticated is True

    authority.sessions[SID] = replace(
        authority.sessions[SID], state=AuthSessionState.REVOKED, revision=2
    )
    await instance.invalidate_session('legacy', UID, SID)

    # No clock advance at all: the invalidated entry is gone, so the guard asks.
    verdict = await _verdict(instance, authority)
    assert verdict.authenticated is False
    assert verdict.reason == 'revoked'
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_a_reload_started_before_the_invalidation_cannot_repopulate(cache):
    instance, clock, writer = cache
    authority = Authority()
    assert (await _verdict(instance, authority)).authenticated is True

    gate = asyncio.Event()

    async def slow_loader():
        await gate.wait()
        return UID, time.time() + 3600

    clock[0] += TTL_SECONDS - REFRESH_AHEAD_SECONDS + 1
    assert (await instance.get_or_load_ahead('legacy', UID, SID, slow_loader, slow_loader)) == UID
    await asyncio.sleep(0)

    await instance.invalidate_session('legacy', UID, SID)
    gate.set()
    await asyncio.sleep(0.05)

    remaining = writer.execute('SELECT COUNT(*) FROM auth_validation_cache').fetchone()[0]
    assert remaining == 0
