import logging
import sqlite3

import pytest

from app.history import D1HistoryStore, HistoryConflict, _user_id
from app.shared_profile_provision import provision_shared_profile


class Statement:
    def __init__(self, conn, sql): self.conn, self.sql, self.args = conn, sql, ()
    def bind(self, *args): self.args = args; return self
    async def run(self):
        cursor = self.conn.execute(self.sql, self.args)
        return {'results': [dict(row) for row in cursor.fetchall()] if cursor.description else []}

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, auth_provider TEXT NOT NULL CHECK(auth_provider='google'), provider_subject TEXT NOT NULL, email TEXT NOT NULL, display_name TEXT NOT NULL, picture_url TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(auth_provider,provider_subject))")
    def prepare(self, sql): return Statement(self.conn, sql)

class Verifier:
    def __init__(self, *, account_id='sub_known', amr=None, exc=None):
        self.account_id = account_id
        self.amr = amr
        self.exc = exc
        self.calls = 0

    async def verify(self, token):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        result = {'accountId': self.account_id}
        if self.amr is not None:
            result['amr'] = self.amr
        return result

@pytest.mark.asyncio
async def test_new_user_existing_update_and_legacy_rollback():
    db = Database(); store = D1HistoryStore(db); uid = _user_id('google-verified-sub')
    await store.upsert_shared_user(uid, 'sub_known', 'user@example.invalid', 'Name', '')
    await store.upsert_shared_user(uid, 'sub_known', 'other@example.invalid', 'New', '')
    assert db.conn.execute('SELECT count(*) FROM users').fetchone()[0] == 1
    with pytest.raises(HistoryConflict):
        await store.upsert_shared_user(uid, 'sub_other', 'bad@example.invalid', 'Bad', '')
    await store.upsert_google_user('google-verified-sub', 'user@example.invalid', 'Old', '')
    row = db.conn.execute('SELECT * FROM users').fetchone()
    assert row['id'] == uid and row['provider_subject'] == 'google-verified-sub'

@pytest.mark.asyncio
async def test_profile_requires_verified_matching_identity_before_any_write():
    class Store:
        def __init__(self): self.calls = []
        async def upsert_shared_user(self, *args): self.calls.append(args)
    store = Store(); notified = []
    async def notify(request, uid): notified.append(uid)
    uid = 'usr_' + 'a' * 32
    payload = {'account_id':'sub_known','profile':{'email':'user@example.invalid','email_verified':True,'name':'Name','picture':''}}
    async def run(value, legacy=None):
        await provision_shared_profile(None, uid, 'access', value, verifier=Verifier(), store=store, legacy_user=lambda _:legacy, notify=notify)
    for invalid in ({**payload, 'account_id':'sub_other'}, {**payload, 'profile':{**payload['profile'], 'email_verified':False}}):
        with pytest.raises(ValueError): await run(invalid)
    with pytest.raises(ValueError): await run(payload, legacy='usr_' + 'b' * 32)
    assert store.calls == [] and notified == []
    await run(payload)
    assert store.calls[0][:2] == (uid, 'sub_known') and notified == [uid]


class Recorded:
    def __init__(self):
        self.calls = []

    async def upsert_shared_user(self, *args):
        self.calls.append(args)


PROFILE_BODY = {'email': 'user@example.invalid', 'email_verified': True, 'name': 'Name', 'picture': ''}
USER = 'usr_' + 'a' * 32


async def provide(store, notified, tokens, *, uid=USER, legacy=None, verifier=None, access_token='access'):
    async def notify(request, user):
        notified.append(user)

    await provision_shared_profile(
        None, uid, access_token, tokens, verifier=verifier or Verifier(), store=store,
        legacy_user=lambda _: legacy, notify=notify)


@pytest.mark.asyncio
async def test_a_token_body_that_states_no_account_is_bound_by_the_verified_token():
    # A conforming OAuth /token response carries no account field. Rejecting that
    # used to look exactly like an account mismatch; the verified subject decides.
    store, notified = Recorded(), []
    await provide(store, notified, {'profile': dict(PROFILE_BODY)})
    assert store.calls[0][:2] == (USER, 'sub_known') and notified == [USER]


@pytest.mark.asyncio
async def test_the_camel_case_field_is_the_same_binding_and_still_cross_checked():
    store, notified = Recorded(), []
    await provide(store, notified, {'accountId': 'sub_known', 'profile': dict(PROFILE_BODY)})
    assert store.calls[0][:2] == (USER, 'sub_known')
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'accountId': 'sub_other', 'profile': dict(PROFILE_BODY)})


@pytest.mark.asyncio
async def test_a_stated_account_that_differs_is_still_a_mismatch():
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'account_id': 'sub_other', 'profile': dict(PROFILE_BODY)})


@pytest.mark.asyncio
async def test_a_client_that_opted_out_of_profile_writes_nothing_and_still_signs_in(caplog):
    # apps/padiem-auth discloses profile fields only to clients that list
    # profile_claims; an opted-out client receives a bare token body.
    store, notified = Recorded(), []
    private_key = 'person@example.invalid'
    caplog.set_level(logging.INFO, logger='app.shared_profile_provision')
    await provide(store, notified, {'token_type': 'Bearer', 'expires_in': 900,
                                    'access_token': 'synthetic-oauth-token',
                                    private_key: 'private-response-value'})
    assert store.calls == [] and notified == []
    assert 'body_field_count=4' in caplog.text
    assert private_key not in caplog.text
    assert 'synthetic-oauth-token' not in caplog.text
    assert 'private-response-value' not in caplog.text


@pytest.mark.asyncio
async def test_an_allowlist_subset_of_the_profile_is_valid_and_the_rest_defaults():
    store, notified = Recorded(), []
    await provide(store, notified, {'account_id': 'sub_known',
                                    'profile': {'email': 'user@example.invalid', 'email_verified': True}})
    assert store.calls[0] == (USER, 'sub_known', 'user@example.invalid', '', '')
    assert notified == [USER]


PASSWORD_BODY = {'email': 'user@example.invalid', 'email_verified': False, 'name': '', 'picture': ''}
GOOGLE_FALSE_BODY = {'email': 'user@example.invalid', 'email_verified': False, 'name': 'Real Name', 'picture': 'https://example.invalid/p.png'}


@pytest.mark.asyncio
async def test_password_login_profile_is_provisioned():
    # padiem-auth의 비밀번호 경로는 Chat 내부 비밀번호 확인으로 계정을 증명한 뒤
    # email_verified=false, name='', picture='' 를 하드코딩으로 발행한다.
    # 그 발행 계약 그대로인 프로필만 면제한다.
    store, notified = Recorded(), []
    await provide(store, notified, {'account_id': 'sub_known', 'profile': dict(PASSWORD_BODY)})
    assert store.calls[0] == (USER, 'sub_known', 'user@example.invalid', '', '')
    assert notified == [USER]


@pytest.mark.asyncio
async def test_password_contract_without_picture_key_is_not_exempted():
    # 발행 계약은 name/picture 키가 둘 다 있는 모양이다. 키가 빠지면 면제가 아니라 거절.
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': {'email': 'user@example.invalid',
                                                   'email_verified': False}})
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': {'email': 'user@example.invalid',
                                                   'email_verified': False,
                                                   'name': ''}})


@pytest.mark.asyncio
async def test_password_contract_with_mismatched_subject_is_rejected():
    # 토큰의 주체와 일치하지 않으면 비밀번호 모양이어도 거절한다.
    store = Recorded()
    with pytest.raises(ValueError):
        await provide(store, [], {'account_id': 'sub_other', 'profile': dict(PASSWORD_BODY)})
    assert store.calls == []


@pytest.mark.asyncio
async def test_google_shaped_profile_with_unverified_email_is_rejected():
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': dict(GOOGLE_FALSE_BODY)})


@pytest.mark.asyncio
async def test_google_verified_profile_is_provisioned():
    store, notified = Recorded(), []
    await provide(store, notified, {'profile': dict(PROFILE_BODY)})
    assert store.calls[0] == (USER, 'sub_known', 'user@example.invalid', 'Name', '')
    assert notified == [USER]


@pytest.mark.asyncio
async def test_amr_pwd_with_matching_subject_is_provisioned():
    # amr=['pwd'] + 서명 검증 주체 일치 시 email_verified=False가 면제되며,
    # 향후 name이 채워진 비밀번호 프로필이어도 허용된다.
    store, notified = Recorded(), []
    await provide(
        store,
        notified,
        {'account_id': 'sub_known', 'profile': {'email': 'user@example.invalid', 'email_verified': False, 'name': 'User Name', 'picture': ''}},
        verifier=Verifier(amr=['pwd']),
    )
    assert store.calls[0] == (USER, 'sub_known', 'user@example.invalid', 'User Name', '')
    assert notified == [USER]
    with pytest.raises(ValueError):
        await provide(
            Recorded(),
            [],
            {'account_id': 'sub_other', 'profile': dict(PASSWORD_BODY)},
            verifier=Verifier(amr=['pwd']),
        )


@pytest.mark.asyncio
async def test_amr_google_with_unverified_email_is_rejected_even_if_empty_shape():
    # amr=['google']이면 모양이 빈 문자열(name='', picture='')이어도 email_verified=False는 거절한다.
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': dict(GOOGLE_FALSE_BODY)}, verifier=Verifier(amr=['google']))
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': dict(PASSWORD_BODY)}, verifier=Verifier(amr=['google']))


@pytest.mark.asyncio
async def test_amr_absent_falls_back_to_existing_shape_contract():
    # amr이 없을 때만 기존 발행 모양(name='', picture='')으로 판별한다.
    store, notified = Recorded(), []
    await provide(store, notified, {'profile': dict(PASSWORD_BODY)}, verifier=Verifier(amr=None))
    assert store.calls[0] == (USER, 'sub_known', 'user@example.invalid', '', '')
    assert notified == [USER]
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': dict(GOOGLE_FALSE_BODY)}, verifier=Verifier(amr=None))


@pytest.mark.asyncio
async def test_amr_is_read_only_after_signature_verification():
    # 토큰 본문이나 응답 바디에 amr=['pwd']가 들어 있어도 서명 검증을 통과한 verifier 결과만 읽는다.
    import base64
    import json
    from app.shared_auth_compare_flow import WorkerJwksVerifier
    from shared_es256_test_crypto import TestES256

    forged_header = base64.urlsafe_b64encode(b'{"alg":"ES256","typ":"JWT","kid":"k1"}').rstrip(b'=').decode()
    forged_payload = base64.urlsafe_b64encode(
        json.dumps({
            'iss': 'https://auth.padiem.net', 'aud': 'b62', 'sub': 'sub_known',
            'account_id': 'sub_known', 'sid': 'sid_1', 'amr': ['pwd'],
            'iat': 1000, 'exp': 1900, 'token_use': 'access',
        }).encode()
    ).rstrip(b'=').decode()
    forged_jwt = f'{forged_header}.{forged_payload}.' + base64.urlsafe_b64encode(b'x' * 64).rstrip(b'=').decode()

    # 1) 서명 검증 실패 시 amr=['pwd'] 페이로드여도 즉시 거절되고 저장소 호출은 0회다.
    failing_verifier = Verifier(exc=ValueError('invalid_signature'))
    store = Recorded()
    with pytest.raises(ValueError, match='invalid_signature'):
        await provide(store, [], {'amr': ['pwd'], 'profile': dict(GOOGLE_FALSE_BODY)},
                      verifier=failing_verifier, access_token=forged_jwt)
    assert failing_verifier.calls == 1
    assert store.calls == []

    # 2) 토큰 본문/바디에 amr=['pwd']가 있어도 verifier가 검증한 결과가 amr=['google']이면 거절한다.
    google_verifier = Verifier(amr=['google'])
    with pytest.raises(ValueError, match='invalid_profile'):
        await provide(store, [], {'amr': ['pwd'], 'profile': dict(PASSWORD_BODY)},
                      verifier=google_verifier, access_token=forged_jwt)
    assert google_verifier.calls == 1
    assert store.calls == []

    # 3) WorkerJwksVerifier 실제 ES256 서명 검증: amr 변조 시 invalid_signature로 거절된다.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    priv = ec.generate_private_key(ec.SECP256R1())
    nums = priv.public_key().public_numbers()
    b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
    jwk = {
        'kty': 'EC', 'crv': 'P-256', 'kid': 'k1', 'alg': 'ES256', 'use': 'sig',
        'x': b64u(nums.x.to_bytes(32, 'big')), 'y': b64u(nums.y.to_bytes(32, 'big')),
    }
    real_verifier = WorkerJwksVerifier(crypto=TestES256(), clock=lambda: 1000)
    real_verifier.keys, real_verifier.until = {'keys': [jwk]}, 1300
    signed_input = f'{forged_header}.{forged_payload}'.encode('ascii')
    r, s = decode_dss_signature(priv.sign(signed_input, ec.ECDSA(hashes.SHA256())))
    valid_pwd_jwt = f'{forged_header}.{forged_payload}.' + b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))

    verified_claims = await real_verifier.verify(valid_pwd_jwt)
    assert verified_claims['amr'] == ['pwd']

    # 페이로드의 amr을 바꾼 뒤 원래 서명을 재사용하면 서명 검증에서 거절된다.
    tampered_jwt = f'{forged_header}.{forged_payload}.' + b64u((r ^ 1).to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    with pytest.raises(ValueError, match='invalid_signature'):
        await provide(store, [], {'profile': dict(PASSWORD_BODY)},
                      verifier=real_verifier, access_token=tampered_jwt)
    assert store.calls == []


@pytest.mark.asyncio
async def test_a_profile_field_the_client_never_asked_for_is_still_rejected():
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': {'email': 'user@example.invalid', 'phone': 'x'}})
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': {'email_verified': True}})
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': {'email': 'user@example.invalid', 'email_verified': False}})


@pytest.mark.asyncio
async def test_the_rejected_condition_is_named_without_printing_any_value(caplog):
    caplog.set_level(logging.WARNING)
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': dict(PROFILE_BODY)}, uid='u_short')
    assert 'condition=chat_user_id' in caplog.text
    assert 'user_id=u_+7' in caplog.text         # prefix family and length, nothing else
    assert 'u_short' not in caplog.text
    assert 'sub_known' not in caplog.text
    assert 'user@example.invalid' not in caplog.text

    caplog.clear()
    private_key = 'private@example.invalid'
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': {'email': 'x@example.invalid',
                                                    private_key: 'synthetic-token-marker'}})
    assert 'condition=shape' in caplog.text
    assert 'profile_field_count=2' in caplog.text
    assert 'body_field_count=1' in caplog.text
    assert 'x@example.invalid' not in caplog.text
    assert private_key not in caplog.text
    assert 'synthetic-token-marker' not in caplog.text

    caplog.clear()
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'account_id': 'sub_other', 'profile': dict(PROFILE_BODY)})
    assert 'condition=exchange_mismatch' in caplog.text
    assert 'sub_other' not in caplog.text
