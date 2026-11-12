"""#7551 — the password RPC tells padiem-auth which credential answered.

The credential's creation time is stable across password change and reset and
changes only when the credential is created again; padiem-auth binds an email
identity to an existing common account only with the credential it was linked
with. The D1 store must read it from the credential row.
"""
from __future__ import annotations

import pytest

from app.history import D1HistoryStore
from test_6446_account_isolation_sweep import ThreadSafeSqliteD1, apply_all_migrations


def _db():
    db = ThreadSafeSqliteD1()
    apply_all_migrations(db)
    return db


@pytest.mark.asyncio
async def test_the_credential_creation_time_survives_a_password_change_and_moves_on_re_creation():
    db = _db()
    conn = db.conn
    store = D1HistoryStore(db)
    profile = await store.register_password_user("owner@example.test", "owner@example.test", "Owner", "hash-1")
    first = await store.find_password_credential("owner@example.test")
    assert first is not None and first.created_at

    await store.update_password_credential(profile.id, "hash-2")
    changed = await store.find_password_credential("owner@example.test")
    assert changed.created_at == first.created_at

    conn.execute("DELETE FROM password_credentials WHERE user_id=?", (profile.id,))
    conn.execute(
        "INSERT INTO password_credentials (user_id, username, password_hash, failed_attempts, locked_until, created_at, updated_at) "
        "VALUES (?, ?, 'hash-3', 0, NULL, '2099-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00')",
        (profile.id, "owner@example.test"),
    )
    recreated = await store.find_password_credential("owner@example.test")
    assert recreated.created_at != first.created_at
