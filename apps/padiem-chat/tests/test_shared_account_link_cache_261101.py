"""A verified subject's Chat account link is reused, then dropped when it moves."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth_validation_cache import AuthValidationInvalidated, SqliteAuthValidationCache
from app.d1_sqlite import SqliteD1, connect
from app.shared_auth_adapter import SharedChatAuth

UID = 'usr_' + 'a' * 32
OTHER_UID = 'usr_' + 'b' * 32
SUBJECT = 'sub_' + 'c' * 32
OTHER_SUBJECT = 'sub_' + 'd' * 32
TOKEN_LIFETIME = 900


@pytest.fixture
def workers(tmp_path):
    path = tmp_path / 'auth.sqlite3'
    first, second = connect(str(path)), connect(str(path))
    migrations = Path(__file__).parents[1] / 'migrations'
    for name in ('087_auth_validation_cache.sql', '088_shared_account_link_cache.sql'):
        first.executescript((migrations / name).read_text())
    clock = [1_800_000_000.0]
    one = SqliteAuthValidationCache(SqliteD1(first), ttl_seconds=30, link_ttl_seconds=600,
                                    clock=lambda: clock[0])
    two = SqliteAuthValidationCache(SqliteD1(second), ttl_seconds=30, link_ttl_seconds=600,
                                    clock=lambda: clock[0])
    yield one, two, clock, first
    first.close()
    second.close()


class Verifier:
    """Claims only a signature has established. Every login carries a new session id."""

    def __init__(self, clock, sessions):
        self.clock, self.sessions = clock, sessions

    async def verify(self, token):
        subject = self.sessions.get(token)
        if subject is None:
            raise ValueError('invalid_token')
        return {'accountId': subject, 'sessionId': 'sid-' + token,
                'expiresAt': int(self.clock() + TOKEN_LIFETIME)}


class Authority:
    def __init__(self, links):
        self.links, self.calls = dict(links), 0

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == 'b62'
        self.calls += 1
        await asyncio.sleep(0)
        user_id = self.links.get(canonical_subject_id)
        if not isinstance(user_id, str) or not user_id:
            raise ValueError('missing_product_link')
        return user_id


def request(cache):
    return Request({'type': 'http', 'method': 'GET', 'path': '/auth/shared/callback',
                    'query_string': b'', 'headers': [],
                    'app': SimpleNamespace(state=SimpleNamespace(auth_validation_cache=cache))})


def auth(clock, sessions, authority):
    return SharedChatAuth(verifier=Verifier(clock, sessions), authority=authority,
                          legacy=lambda _: None, clock=clock)


@pytest.mark.asyncio
async def test_a_second_login_does_not_ask_the_authority_again(workers):
    one, two, _, _ = workers
    authority = Authority({SUBJECT: UID})
    port = auth(one.clock, {'first': SUBJECT, 'second': SUBJECT}, authority)
    assert await port.user_id(request(one), 'first') == UID
    assert await port.user_id(request(two), 'second') == UID
    assert authority.calls == 1


@pytest.mark.asyncio
async def test_the_link_outlives_the_session_and_then_expires_itself(workers):
    one, _, clock, _ = workers
    authority = Authority({SUBJECT: UID})
    port = auth(one.clock, {'first': SUBJECT}, authority)
    assert await port.user_id(request(one), 'first') == UID
    clock[0] += 31
    assert await port.user_id(request(one), 'first') == UID
    assert authority.calls == 1
    clock[0] += 600
    assert await port.user_id(request(one), 'first') == UID
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_one_subject_never_answers_for_another(workers):
    one, _, _, _ = workers
    authority = Authority({SUBJECT: UID, OTHER_SUBJECT: OTHER_UID})
    port = auth(one.clock, {'mine': SUBJECT, 'theirs': OTHER_SUBJECT}, authority)
    assert await port.user_id(request(one), 'mine') == UID
    assert await port.user_id(request(one), 'theirs') == OTHER_UID
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_moving_the_link_drops_the_cached_answer(workers):
    one, two, _, _ = workers
    authority = Authority({SUBJECT: UID})
    port = auth(one.clock, {'first': SUBJECT}, authority)
    assert await port.user_id(request(one), 'first') == UID
    authority.links[SUBJECT] = OTHER_UID
    await two.invalidate_user(UID)
    assert await port.user_id(request(one), 'first') == OTHER_UID
    assert authority.calls == 2


@pytest.mark.asyncio
async def test_logout_clears_that_subject_and_leaves_the_other_one(workers):
    one, two, _, _ = workers
    authority = Authority({SUBJECT: UID, OTHER_SUBJECT: OTHER_UID})
    port = auth(one.clock, {'mine': SUBJECT, 'theirs': OTHER_SUBJECT}, authority)
    assert await port.user_id(request(one), 'mine') == UID
    assert await port.user_id(request(one), 'theirs') == OTHER_UID
    assert authority.calls == 2
    await port.invalidate_session(request(two), 'mine')
    assert await port.user_id(request(one), 'mine') == UID
    assert authority.calls == 3
    assert await port.user_id(request(one), 'theirs') == OTHER_UID
    assert authority.calls == 3


@pytest.mark.asyncio
async def test_parallel_lookups_for_one_subject_share_a_call(workers):
    one = workers[0]
    calls = []
    async def load():
        calls.append(True)
        await asyncio.sleep(.01)
        return UID, one.clock() + TOKEN_LIFETIME
    results = await asyncio.gather(*(one.get_or_load_account_link(SUBJECT, load)
                                     for _ in range(5)))
    assert results == [UID] * 5 and len(calls) == 1


@pytest.mark.asyncio
async def test_an_invalidation_during_a_lookup_refuses_to_cache_it(workers):
    one, two, _, connection = workers
    started, finish = asyncio.Event(), asyncio.Event()
    async def load():
        started.set()
        await finish.wait()
        return UID, one.clock() + TOKEN_LIFETIME
    pending = asyncio.create_task(one.get_or_load_account_link(SUBJECT, load))
    await started.wait()
    await two.invalidate_user(UID)
    finish.set()
    with pytest.raises(AuthValidationInvalidated):
        await pending
    assert connection.execute(
        'SELECT COUNT(*) FROM auth_account_link_cache').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_the_table_holds_no_token_and_no_plain_session_id(workers):
    one, _, _, connection = workers
    authority = Authority({SUBJECT: UID})
    port = auth(one.clock, {'synthetic-access-token-not-for-storage': SUBJECT}, authority)
    assert await port.user_id(request(one), 'synthetic-access-token-not-for-storage') == UID
    dump = '\n'.join(connection.iterdump())
    assert 'synthetic-access-token-not-for-storage' not in dump
    assert 'sid-synthetic' not in dump
    assert SUBJECT in dump


@pytest.mark.asyncio
async def test_a_disabled_cohort_asks_every_time_and_writes_nothing(workers):
    one, _, clock, connection = workers
    off = SqliteAuthValidationCache(one.db, ttl_seconds=30, clock=lambda: clock[0])
    calls = []
    async def load():
        calls.append(True)
        return UID, clock[0] + TOKEN_LIFETIME
    for _ in range(2):
        assert await off.get_or_load_account_link(SUBJECT, load) == UID
    assert len(calls) == 2
    await off.invalidate_user(UID)
    await off.invalidate_session('shared', SUBJECT, 'sid-first')
    await off.invalidate_all()
    assert connection.execute(
        'SELECT COUNT(*) FROM auth_account_link_cache').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_a_disabled_cohort_survives_a_database_without_the_new_table(tmp_path):
    connection = connect(str(tmp_path / 'legacy.sqlite3'))
    connection.executescript((Path(__file__).parents[1] / 'migrations'
                              / '087_auth_validation_cache.sql').read_text())
    off = SqliteAuthValidationCache(SqliteD1(connection), ttl_seconds=30)
    async def load():
        return UID, off.clock() + TOKEN_LIFETIME
    assert await off.get_or_load_account_link(SUBJECT, load) == UID
    await off.invalidate_user(UID)
    await off.invalidate_all()
    connection.close()
