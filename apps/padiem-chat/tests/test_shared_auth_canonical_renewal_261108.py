"""#7161 — the shared login session must carry its canonical sessions.

2026-11-08 13:00 운영 실측: Claw 실행·MCP pc_shell이 전부
canonical_auth_session_not_found. 원인은 정본(B62·B54 canonical) 세션을
만드는 경로가 레거시 로그인뿐(auth_routes.py:538·:805·:924)이고, 프론트
컷오버 이후 실제 로그인인 공용 플로우(/auth/shared/*)는 쿠키만 발급하며
(auth.user_id는 역방향 링크 조회만), /auth/shared/refresh도 재교환+쿠키
재발급이라는 것. 마지막 레거시 로그인 때 만들어진 정본 세션이 만료된 13시부터
조회가 전부 not_found이고, 재로그인(공용 플로우 경유)도 세션을 만들지 않아
소비처가 계속 실패했다.

이 계약은 어댑터의 경계 갱신을 고정한다:
- 검증된 요청(토큰·역방향 링크 모두 통과)에서 정본 세션이 없으면 서버 값
  (verifier claim 주체, 서버 시계, 배포 수명)으로 다시 확립한다.
- not_found 이외의 실패는 소비처의 fail-closed를 그대로 둔다.
- 기본 배선(수명 미지정)에서는 아무 RPC도 추가되지 않는다 — 기존 배포와
  동일.
- 실패·성공 저널은 고정 코드만 담는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import unittest
from datetime import datetime, timedelta, timezone

from app.chat_pc_drive import ChatPCDriveError, _pc_owner_journal
from app.control_plane_identity import IdentityBridgeError
from app.shared_auth_adapter import SharedChatAuth
from padiem_control_plane import CanonicalSubjectRef, SubjectType

LIFETIME = 3600
NOT_FOUND = "canonical_auth_session_not_found"


class Verifier:
    def verify(self, token):
        if token != 'valid':
            raise ValueError('bad signature')
        return {'accountId': 'sub_synthetic', 'expiresAt': 1100}


class RenewalAuthority:
    """The bridge surface the renewal touches, with per-product answers."""

    def __init__(self, *, resolve_codes=(), fail_establish_with=None):
        # product -> code; a product absent from the dict resolves ok.
        self.resolve_codes = dict(resolve_codes)
        self.fail_establish_with = fail_establish_with
        self.resolve_calls = []
        self.establish_calls = []

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == 'b62'
        return 'existing-chat-user'

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.resolve_calls.append(product_id)
        code = self.resolve_codes.get(product_id)
        if code is None:
            return object()
        raise IdentityBridgeError(401, code, 'unavailable')

    async def establish_auth_session(self, *, product_id, subject,
                                     authenticated_at, not_after):
        self.establish_calls.append((product_id, subject.subject_id, not_after))
        if self.fail_establish_with is not None:
            raise IdentityBridgeError(503, self.fail_establish_with, 'unavailable')
        return object()


def _auth(authority, **kwargs):
    return SharedChatAuth(verifier=Verifier(), authority=authority,
                          legacy=lambda _: None, clock=lambda: 1000,
                          canonical_session_lifetime_seconds=kwargs.pop(
                              'canonical_session_lifetime_seconds', LIFETIME),
                          **kwargs)


def test_the_missing_canonical_sessions_are_re_established_behind_a_verified_request():
    authority = RenewalAuthority(resolve_codes={'b62': NOT_FOUND, 'b54-padiem-claw': NOT_FOUND})
    user = asyncio.run(_auth(authority).user_id(None, 'valid'))
    assert user == 'existing-chat-user'
    assert [(p, s) for p, s, _ in authority.establish_calls] == [
        ('b62', 'sub_synthetic'), ('b54-padiem-claw', 'sub_synthetic')]
    # The window is server-derived: started at the server clock, sized by the
    # deployment lifetime — the token's own expiry never widens it.
    started = datetime.fromtimestamp(1000, tz=timezone.utc)
    for _, _, not_after in authority.establish_calls:
        assert not_after == started + timedelta(seconds=LIFETIME)


def test_a_live_canonical_session_is_never_established_again():
    authority = RenewalAuthority()
    asyncio.run(_auth(authority).user_id(None, 'valid'))
    assert authority.establish_calls == []
    assert authority.resolve_calls == ['b62', 'b54-padiem-claw']


def test_an_expired_session_renews_again_on_the_next_request():
    authority = RenewalAuthority()
    auth = _auth(authority)
    asyncio.run(auth.user_id(None, 'valid'))
    # The canonical session expires (the 13:00 incident): the same verified
    # subject now resolves not_found, and the next request renews it.
    authority.resolve_codes = {'b62': NOT_FOUND, 'b54-padiem-claw': NOT_FOUND}
    asyncio.run(auth.user_id(None, 'valid'))
    assert [p for p, _, _ in authority.establish_calls] == ['b62', 'b54-padiem-claw']


def test_a_failed_renewal_never_turns_a_verified_request_into_a_failure():
    authority = RenewalAuthority(
        resolve_codes={'b62': NOT_FOUND, 'b54-padiem-claw': NOT_FOUND},
        fail_establish_with='identity_authority_link_missing')
    user = asyncio.run(_auth(authority).user_id(None, 'valid'))
    assert user == 'existing-chat-user'
    # The renewal was attempted, not skipped.
    assert len(authority.establish_calls) == 2


def test_the_renewal_is_opt_in_and_the_default_wiring_stays_unchanged():
    authority = RenewalAuthority()
    auth = SharedChatAuth(verifier=Verifier(), authority=authority,
                          legacy=lambda _: None, clock=lambda: 1000)
    user = asyncio.run(auth.user_id(None, 'valid'))
    assert user == 'existing-chat-user'
    assert authority.resolve_calls == [] and authority.establish_calls == []


def test_a_non_positive_lifetime_is_a_configuration_error():
    for bad in (0, -1, True):
        try:
            SharedChatAuth(verifier=Verifier(), authority=RenewalAuthority(),
                           legacy=lambda _: None, clock=lambda: 1000,
                           canonical_session_lifetime_seconds=bad)
        except ValueError:
            continue
        raise AssertionError('a non-positive lifetime must not compose')


def test_the_renewal_journal_carries_closed_codes_only():
    authority = RenewalAuthority(
        resolve_codes={'b62': NOT_FOUND, 'b54-padiem-claw': NOT_FOUND},
        fail_establish_with='identity_authority_link_missing')
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        asyncio.run(_auth(authority).user_id(None, 'valid'))
    printed = buffer.getvalue()
    assert 'canonical_session_renewal product=b62 outcome=' in printed
    assert 'canonical_session_renewal product=b54-padiem-claw outcome=' in printed
    # No identity value travels: not the subject, not the product user.
    assert 'sub_synthetic' not in printed
    assert 'usr_' not in printed and 'existing-chat-user' not in printed


class _OwnerRequest:
    def __init__(self, authority):
        self.app = type('App', (), {'state': type('State', (), {
            'control_plane_identity_authority': authority})()})()


def test_the_pc_owner_journal_names_the_failing_stage_and_closed_code():
    authority = RenewalAuthority(resolve_codes={'b62': NOT_FOUND})
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            asyncio.run(_journaled_owner(authority))
        except ChatPCDriveError:
            pass
    printed = buffer.getvalue()
    assert 'pc_owner_identity stage=resolve_b62 outcome=canonical_auth_session_not_found' in printed


async def _journaled_owner(authority):
    from app.chat_pc_drive import _resolve_chat_owner
    await _resolve_chat_owner(_OwnerRequest(authority), 'usr_owner')


def test_the_pc_owner_journal_never_echoes_unsafe_labels():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _pc_owner_journal('resolve_b62', 'not a safe label 42')
        _pc_owner_journal('bad stage with spaces', NOT_FOUND)
    assert 'pc_owner_identity stage=resolve_b62 outcome=other' in buffer.getvalue()
    assert 'pc_owner_identity stage=other outcome=canonical_auth_session_not_found' in buffer.getvalue()


# ---------------------------------------------------------------------------
# CI 회귀(2026-11-08): test_shared_account_link_cache_261101 10건.
# get_or_load는 product_user_id "문자열"을 돌려주는데 갱신 배선이 튜플로
# 언팩해 ValueError → shared_auth_failed로 번졌다. 실제 캐시와 최소 authority
# 로 같은 모양을 고정한다.

import asyncio  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.auth_validation_cache import SqliteAuthValidationCache  # noqa: E402
from app.d1_sqlite import SqliteD1, connect  # noqa: E402
from app.shared_auth_adapter import SharedAuthUnavailable  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CACHE_CLOCK = [1_800_000_000.0]


class MinimalAuthority:
    """The CI shape: the link lookup only — no canonical-session surface."""

    def __init__(self):
        self.calls = 0

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == 'b62'
        self.calls += 1
        return 'usr_cache-user'


class CacheVerifier:
    async def verify(self, token):
        if token != 'valid':
            raise ValueError('bad signature')
        return {'accountId': 'sub_cacheuser', 'sessionId': 'sid-1',
                'expiresAt': int(CACHE_CLOCK[0] + 900)}


def _cache_request(cache):
    from starlette.requests import Request as StarletteRequest
    return StarletteRequest({'type': 'http', 'method': 'GET', 'path': '/x',
                             'query_string': b'', 'headers': [],
                             'app': SimpleNamespace(state=SimpleNamespace(
                                 auth_validation_cache=cache))})


def _sqlite_cache(tmp_path):
    connection = connect(str(tmp_path / 'auth.sqlite3'))
    migrations = REPO / 'migrations'
    for name in ('087_auth_validation_cache.sql', '088_shared_account_link_cache.sql'):
        connection.executescript((migrations / name).read_text())
    return SqliteAuthValidationCache(SqliteD1(connection), ttl_seconds=30,
                                     link_ttl_seconds=600, clock=lambda: CACHE_CLOCK[0])


def test_the_cached_session_branch_keeps_its_original_contract_with_renewal_on(tmp_path):
    cache = _sqlite_cache(tmp_path)
    authority = MinimalAuthority()
    auth = SharedChatAuth(verifier=CacheVerifier(), authority=authority,
                          legacy=lambda _: None, clock=lambda: CACHE_CLOCK[0],
                          canonical_session_lifetime_seconds=LIFETIME)
    request = _cache_request(cache)
    user = asyncio.run(auth.user_id(request, 'valid'))
    # The branch answers the authority's own product user id, as before.
    assert user == 'usr_cache-user'
    assert asyncio.run(auth.user_id(request, 'valid')) == 'usr_cache-user'


def test_the_renewal_containment_holds_for_any_authority_exception(tmp_path):
    cache = _sqlite_cache(tmp_path)

    class BrokenAuthority(MinimalAuthority):
        async def resolve_current_auth_session(self, **_kwargs):
            raise RuntimeError('authority exploded without a code attribute')

        async def establish_auth_session(self, **_kwargs):
            raise RuntimeError('establish exploded without a code attribute')

    auth = SharedChatAuth(verifier=CacheVerifier(), authority=BrokenAuthority(),
                          legacy=lambda _: None, clock=lambda: CACHE_CLOCK[0],
                          canonical_session_lifetime_seconds=LIFETIME)
    user = asyncio.run(auth.user_id(_cache_request(cache), 'valid'))
    assert user == 'usr_cache-user'


def test_the_renewal_containment_holds_even_when_its_own_window_overflows(tmp_path):
    cache = _sqlite_cache(tmp_path)
    # A lifetime no timedelta can represent blows up inside the renewal's own
    # scaffolding — the verified request still answers exactly as before.
    auth = SharedChatAuth(verifier=CacheVerifier(), authority=MinimalAuthority(),
                          legacy=lambda _: None, clock=lambda: CACHE_CLOCK[0],
                          canonical_session_lifetime_seconds=10 ** 18)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        user = asyncio.run(auth.user_id(_cache_request(cache), 'valid'))
    assert user == 'usr_cache-user'
    assert 'canonical_session_renewal product=none outcome=OverflowError' in buffer.getvalue()
