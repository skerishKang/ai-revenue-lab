"""Read-only inventory and isolated SQLite migration; no live DO transport.

Inputs are independently obtained SQLite copies of Chat users and the identity
authority. The source authority stores keyed fingerprints, not Google sub;
the verified join through product_user_id is essential. Never print rows.
"""
import argparse
import base64
import hashlib
import sqlite3
from pathlib import Path


def _ro(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def _fingerprint(sub):
    return base64.urlsafe_b64encode(hashlib.sha256(('google:' + sub).encode()).digest()).rstrip(b'=').decode()


def _hash(rows):
    h = hashlib.sha256()
    for fingerprint, account_id, state in sorted(rows):
        for item in (fingerprint, account_id, state):
            b = item.encode(); h.update(len(b).to_bytes(8, 'big')); h.update(b)
    return h.hexdigest()


def plan(chat_path, authority_path):
    with _ro(chat_path) as chat, _ro(authority_path) as authority:
        users = dict(chat.execute("SELECT id, provider_subject FROM users WHERE auth_provider='google'"))
        subjects = {row[0] for row in authority.execute("SELECT canonical_subject_id FROM canonical_identity_subject WHERE provider='google'")}
        links = list(authority.execute('SELECT product_user_id,canonical_subject_id,state FROM canonical_product_identity_link'))
    mapped = {}
    for user, account_id, state in links:
        if account_id not in subjects or user not in users:
            continue
        if state != 'active':
            raise ValueError('inactive source link requires explicit reconciliation')
        subject = users[user]
        expected = 'usr_' + hashlib.sha256(('google:' + subject).encode()).hexdigest()[:32]
        if expected != user:
            raise ValueError('source user id mismatch')
        key = _fingerprint(subject)
        if key in mapped and mapped[key] != account_id:
            raise ValueError('identity conflict')
        mapped[key] = account_id
    if set(mapped.values()) != subjects or len(set(mapped.values())) != len(mapped):
        raise ValueError('unmatched or ambiguous source identity; no writes')
    return [(key, account, 'active') for key, account in sorted(mapped.items())]


def apply(target_path, rows):
    # Existing target only; never create a production DB by typo.
    db = sqlite3.connect(Path(target_path).resolve().as_uri() + '?mode=rw', uri=True, isolation_level=None)
    try:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT COUNT(*) FROM google_accounts').fetchone()[0]:
            raise ValueError('target is not empty')
        db.executemany('INSERT INTO google_accounts(fingerprint,account_id,state) VALUES(?,?,?)', rows)
        result = list(db.execute('SELECT fingerprint,account_id,state FROM google_accounts'))
        if len(result) != len(rows) or _hash(result) != _hash(rows):
            raise ValueError('verification mismatch')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chat-copy', required=True)
    parser.add_argument('--authority-copy', required=True)
    parser.add_argument('--rehearsal-target')
    args = parser.parse_args()
    rows = plan(args.chat_copy, args.authority_copy)
    if args.rehearsal_target:
        apply(args.rehearsal_target, rows)
    print(f'count={len(rows)} sha256={_hash(rows)} mode={"rehearsal" if args.rehearsal_target else "readonly"}')


if __name__ == '__main__':
    main()
