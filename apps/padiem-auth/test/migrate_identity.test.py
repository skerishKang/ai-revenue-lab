import hashlib
import importlib.util
import sqlite3
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('migration', Path(__file__).resolve().parents[1] / 'migrate_identity.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_plan_apply_and_unmatched_fail_closed():
    with tempfile.TemporaryDirectory() as d:
        chat, authority, target = (str(Path(d) / x) for x in ('chat.db', 'authority.db', 'target.db'))
        uid = 'usr_' + hashlib.sha256(b'google:synthetic').hexdigest()[:32]
        with sqlite3.connect(chat) as db:
            db.execute('CREATE TABLE users(id TEXT,auth_provider TEXT,provider_subject TEXT)')
            db.execute('INSERT INTO users VALUES(?,?,?)', (uid, 'google', 'synthetic'))
        with sqlite3.connect(authority) as db:
            db.execute('CREATE TABLE canonical_identity_subject(provider TEXT,canonical_subject_id TEXT)')
            db.execute('CREATE TABLE canonical_product_identity_link(product_user_id TEXT,canonical_subject_id TEXT,state TEXT)')
            db.execute("INSERT INTO canonical_identity_subject VALUES('google','sub_example')")
            db.execute("INSERT INTO canonical_product_identity_link VALUES(?, 'sub_example', 'active')", (uid,))
        with sqlite3.connect(target) as db:
            db.execute('CREATE TABLE google_accounts(fingerprint TEXT PRIMARY KEY,account_id TEXT UNIQUE,state TEXT)')
        rows = m.plan(chat, authority)
        assert len(rows) == 1
        m.apply(target, rows)
        with sqlite3.connect(target) as db:
            actual = list(db.execute('SELECT fingerprint,account_id,state FROM google_accounts'))
            assert m._hash(actual) == m._hash(rows)
        try:
            m.apply(target, rows)
        except ValueError:
            pass
        else:
            raise AssertionError('nonempty target accepted')
        with sqlite3.connect(authority) as db:
            db.execute("INSERT INTO canonical_identity_subject VALUES('google','sub_missing')")
        try:
            m.plan(chat, authority)
        except ValueError:
            pass
        else:
            raise AssertionError('unmatched identity accepted')


if __name__ == '__main__':
    test_plan_apply_and_unmatched_fail_closed()
    print('migration rehearsal: PASS')
