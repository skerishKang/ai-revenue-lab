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
    async def verify(self, token): return {'accountId':'sub_known'}

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


async def provide(store, notified, tokens, *, uid=USER, legacy=None):
    async def notify(request, user):
        notified.append(user)

    await provision_shared_profile(
        None, uid, 'access', tokens, verifier=Verifier(), store=store,
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
async def test_a_client_that_opted_out_of_profile_writes_nothing_and_still_signs_in():
    # apps/padiem-auth only discloses profile fields to clients that list
    # profile_claims; the production Chat client does not, so the body is bare.
    store, notified = Recorded(), []
    await provide(store, notified, {'token_type': 'Bearer', 'expires_in': 900})
    assert store.calls == [] and notified == []


@pytest.mark.asyncio
async def test_an_allowlist_subset_of_the_profile_is_valid_and_the_rest_defaults():
    store, notified = Recorded(), []
    await provide(store, notified, {'account_id': 'sub_known',
                                    'profile': {'email': 'user@example.invalid', 'email_verified': True}})
    assert store.calls[0] == (USER, 'sub_known', 'user@example.invalid', '', '')
    assert notified == [USER]


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
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'profile': {'email': 'x@example.invalid', 'phone': 'x'}})
    assert 'condition=shape' in caplog.text
    assert 'x@example.invalid' not in caplog.text

    caplog.clear()
    with pytest.raises(ValueError):
        await provide(Recorded(), [], {'account_id': 'sub_other', 'profile': dict(PROFILE_BODY)})
    assert 'condition=exchange_mismatch' in caplog.text
    assert 'sub_other' not in caplog.text
