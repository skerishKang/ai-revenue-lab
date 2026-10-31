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
