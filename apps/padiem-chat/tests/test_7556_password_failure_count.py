"""#7556 — concurrent wrong passwords are all counted, so the lock cannot be outrun.

Covered:

- CONCURRENT_FAILURES_COUNTED: 20 wrong-password logins that all read the
  credential before any of them writes are all counted and set the lock
- LOCK_HOLDS_AFTER_BURST: after the burst the right password is refused too
- SEQUENTIAL_UNCHANGED: five sequential failures still lock, a success still
  resets, and a lapsed lock still restarts the count at one
- RPC_PATH: the common-login password check counts the same way, also
  through the queue-forwarding store wrapper
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_5441_password_reset import (  # noqa: E402
    BASE,
    CURRENT_PASSWORD,
    MEMBER_EMAIL,
    build_app,
    seed_db,
)

BURST = 20


def _row(db, user_id):
    return db.conn.execute(
        "SELECT failed_attempts, locked_until FROM password_credentials WHERE user_id=?",
        (user_id,),
    ).fetchone()


async def _logins(app, passwords):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        return await asyncio.gather(*(
            client.post(
                "/api/auth/password/login",
                json={"identifier": MEMBER_EMAIL, "password": password},
            )
            for password in passwords
        ))


def _all_read_before_any_write(app, count):
    """Hold every login at its credential read until all of them have read it.

    This is the interleaving that loses failures: each request sees the same
    count before any of them records its failure.
    """
    store = app.state.history_store
    real_find = store.find_password_credential
    barrier = asyncio.Barrier(count)

    async def find(identifier):
        credential = await real_find(identifier)
        await barrier.wait()
        return credential

    store.find_password_credential = find
    return lambda: setattr(store, "find_password_credential", real_find)


def test_concurrent_wrong_passwords_are_all_counted_and_lock_the_account():
    db, ids = seed_db()
    app, _settings = build_app(db)
    wrong = [f"wrong guess number {i:02d}" for i in range(BURST)]
    release = _all_read_before_any_write(app, BURST)

    answers = asyncio.run(_logins(app, wrong))
    release()

    assert all(a.status_code == 401 for a in answers)
    row = _row(db, ids["member"])
    # Every request saw the account unlocked, so every failure counts.
    assert row["failed_attempts"] == BURST
    assert row["locked_until"] is not None
    # The lock holds: the right password is refused right after the burst.
    after = asyncio.run(_logins(app, [CURRENT_PASSWORD]))
    assert after[0].status_code == 401


def test_sequential_failures_still_lock_at_the_limit_and_success_resets():
    db, ids = seed_db()
    app, _settings = build_app(db)

    for i in range(4):
        asyncio.run(_logins(app, [f"wrong {i}"]))
    assert _row(db, ids["member"])["failed_attempts"] == 4
    assert _row(db, ids["member"])["locked_until"] is None
    ok = asyncio.run(_logins(app, [CURRENT_PASSWORD]))
    assert ok[0].status_code == 200
    assert _row(db, ids["member"])["failed_attempts"] == 0

    for i in range(5):
        asyncio.run(_logins(app, [f"wrong again {i}"]))
    row = _row(db, ids["member"])
    assert row["failed_attempts"] == 5 and row["locked_until"] is not None


def test_a_lapsed_lock_restarts_the_count_once_even_under_concurrency():
    db, ids = seed_db()
    app, _settings = build_app(db)
    db.conn.execute(
        "UPDATE password_credentials SET failed_attempts=5, locked_until='2026-01-01T00:00:00+00:00' "
        "WHERE user_id=?",
        (ids["member"],),
    )

    answers = asyncio.run(_logins(app, ["wrong a", "wrong b", "wrong c"]))

    assert all(a.status_code == 401 for a in answers)
    row = _row(db, ids["member"])
    # One restart to 1, then the two other failures on top: never 5+3.
    assert row["failed_attempts"] == 3
    assert row["locked_until"] is None


def test_the_store_statements_are_single_step(tmp_path):
    from app.d1_sqlite import SqliteD1, connect
    from app.history import D1HistoryStore

    db, ids = seed_db()
    store = D1HistoryStore(db)

    async def run():
        counts = await asyncio.gather(*(store.increment_password_failures(ids["member"]) for _ in range(BURST)))
        return sorted(counts)

    assert asyncio.run(run()) == list(range(1, BURST + 1))
    assert asyncio.run(store.increment_password_failures("usr_" + "0" * 32)) is None
    asyncio.run(store.lock_password_credential(ids["member"], lock_until="2099-01-01T00:00:00+00:00", min_failures=5))
    asyncio.run(store.lock_password_credential(ids["member"], lock_until="2098-01-01T00:00:00+00:00", min_failures=5))
    assert _row(db, ids["member"])["locked_until"] == "2099-01-01T00:00:00+00:00"
    assert asyncio.run(store.restart_password_failures_after_lapsed_lock(
        ids["member"], expected_locked_until="2000-01-01T00:00:00+00:00")) is False
    assert asyncio.run(store.restart_password_failures_after_lapsed_lock(
        ids["member"], expected_locked_until="2099-01-01T00:00:00+00:00")) is True
    assert _row(db, ids["member"])["failed_attempts"] == 1


@pytest.mark.parametrize("helper", ["missing", "present"])
def test_a_store_without_the_new_statements_keeps_the_earlier_write(helper):
    from types import SimpleNamespace

    from app.password_failure_count import record_failed_password_attempt

    writes = []

    class LegacyStore:
        async def record_password_failure(self, user_id, failures, lock_until):
            writes.append((user_id, failures, lock_until))

    credential = SimpleNamespace(user=SimpleNamespace(id="usr_x"), failed_attempts=4, locked_until=None)
    result = asyncio.run(record_failed_password_attempt(
        LegacyStore(), credential, limit=5, lock_until_for=lambda: "LOCK", lock_has_lapsed=helper == "present",
    ))
    if helper == "missing":
        assert result == 5 and writes == [("usr_x", 5, "LOCK")]
    else:
        assert result == 1 and writes == [("usr_x", 1, None)]


@pytest.mark.parametrize("queue_wrapped", [False, True])
def test_the_common_login_password_check_counts_concurrent_failures(queue_wrapped):
    import json

    from test_password_rpc_261106 import (
        BASE as RPC_BASE,
        EMAIL,
        SECRET,
        VERIFY_PATH,
        build as build_rpc,
        failed_attempts,
        proof_headers,
    )

    app, db = build_rpc(queue_wrapped=queue_wrapped)
    release = _all_read_before_any_write(app, BURST)

    async def burst():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=RPC_BASE) as client:
            calls = []
            for i in range(BURST):
                body = json.dumps({"email": EMAIL, "password": f"wrong guess {i:02d}"},
                                  separators=(",", ":")).encode()
                calls.append(client.post(VERIFY_PATH, content=body,
                                         headers=proof_headers(SECRET, VERIFY_PATH, body)))
            return await asyncio.gather(*calls)

    answers = asyncio.run(burst())
    release()

    assert all(a.status_code == 401 for a in answers)
    failures, locked_until = failed_attempts(db)
    assert failures == BURST
    assert locked_until is not None
