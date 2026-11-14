"""Deletion and signed records cannot race into resurrecting withdrawn data."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sqlite3

import httpx
import pytest
from starlette.applications import Starlette

from app.auth_validation_cache import (
    ACCOUNT_DELETION_TTL_SECONDS,
    SqliteAuthValidationCache,
    account_deletion_allowed_sql,
    permanent_account_deletion_statements,
)
from app.bookai_records import (
    BookAIAccountDeleted,
    BookAIRecordsStore,
    RECORDS_PATH,
    install_bookai_records_routes,
)
from app.d1_sqlite import SqliteD1, connect

NOW = 1793534400
SUBJECT = "sub_withdrawal_fixture"
OTHER = "sub_unrelated_fixture"
SECRET = "synthetic-withdrawal-records-signing-key"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture
def database(tmp_path):
    path = str(tmp_path / "records.sqlite3")
    first, second = connect(path), connect(path)
    for name in ("082_bookai_records.sql", "087_auth_validation_cache.sql"):
        first.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    try:
        yield SqliteD1(first), SqliteD1(second)
    finally:
        first.close()
        second.close()


def record(record_id="note-fixture", *, updated_at=100):
    return {"record_id": record_id, "book_id": "book-fixture", "locator": "1.1",
            "kind": "note", "payload": {"text": "synthetic private note"},
            "updated_at": updated_at, "deleted": False}


async def delete(db, subject=SUBJECT, *, now=NOW):
    await db.batch([
        db.prepare("DELETE FROM bookai_records WHERE subject=?").bind(subject),
        *permanent_account_deletion_statements(db, (subject,), now=now),
    ])


def signed(method, body=b"", *, subject=SUBJECT, now=NOW):
    stamp = str(now)
    message = "\n".join((method, RECORDS_PATH, stamp, subject,
                          hashlib.sha256(body).hexdigest()))
    return {"content-type": "application/json", "x-bookai-subject": subject,
            "x-bookai-timestamp": stamp,
            "x-bookai-signature": hmac.new(SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()}


def application(db, clock):
    app = Starlette()
    install_bookai_records_routes(app, env={"BOOKAI_COM2_SYNC_SECRET": SECRET},
                                 db_binding=db, clock=lambda: clock[0])
    return app


@pytest.mark.asyncio
async def test_deletion_marker_is_hashed_atomic_and_shared_by_existing_guard(database):
    db, reader = database
    cache = SqliteAuthValidationCache(db, clock=lambda: NOW)
    await cache.record_allowed_session(session_id="fixture-session", user_id="fixture-user",
                                       account_id=SUBJECT, valid_until=NOW + 3600)
    db.connection.execute(
        "INSERT INTO auth_validation_cache VALUES ('shared', ?, 'fixture', 'other-user', ?)",
        (OTHER, NOW + 100))
    await BookAIRecordsStore(db).merge(SUBJECT, [record()], now=NOW)
    await delete(db)
    rows = db.connection.execute("SELECT * FROM auth_validation_cache WHERE owner_id='deny:del'").fetchall()
    assert len(rows) == 1
    assert rows[0]["session_hash"] == hashlib.sha256(SUBJECT.encode()).hexdigest()
    assert rows[0]["valid_until"] == NOW + ACCOUNT_DELETION_TTL_SECONDS
    assert SUBJECT not in str([dict(row) for row in db.connection.execute("SELECT * FROM auth_validation_cache")])
    assert db.connection.execute("SELECT revision FROM auth_validation_cache_revision").fetchone()[0] == 1
    assert db.connection.execute("SELECT count(*) FROM auth_validation_cache WHERE owner_id=?", (OTHER,)).fetchone()[0] == 1
    shared = SqliteAuthValidationCache(reader, clock=lambda: NOW)
    assert await shared.is_revoked(account_id=SUBJECT, session_ids=("fixture-session",), user_id="fixture-user")
    assert not await shared.is_revoked(account_id=OTHER)


@pytest.mark.asyncio
async def test_existing_longer_hard_deny_is_not_shortened(database):
    db, _ = database
    cache = SqliteAuthValidationCache(db, clock=lambda: NOW)
    await cache.record_revocation(account_ids=(SUBJECT,), permanent=True, ttl_seconds=7200)
    await db.batch(permanent_account_deletion_statements(db, (SUBJECT, SUBJECT), now=NOW))
    rows = db.connection.execute("SELECT valid_until FROM auth_validation_cache WHERE owner_id='deny:del'").fetchall()
    assert [row[0] for row in rows] == [NOW + 7200]


@pytest.mark.asyncio
async def test_retention_covers_access_and_forwarded_request_windows_with_margin(database):
    db, _ = database
    await delete(db)
    assert ACCOUNT_DELETION_TTL_SECONDS > 900 + 300 + 120
    for elapsed in (900, 1200, ACCOUNT_DELETION_TTL_SECONDS - 1):
        allowed, values = account_deletion_allowed_sql(SUBJECT, now=NOW + elapsed)
        assert (await db.prepare(f"SELECT {allowed} AS allowed").bind(*values).first())["allowed"] == 0


@pytest.mark.asyncio
async def test_marker_failure_rolls_back_record_deletion_and_revision(database):
    db, _ = database
    await BookAIRecordsStore(db).merge(SUBJECT, [record()], now=NOW)
    db.connection.executescript("""
        CREATE TRIGGER deny_fixture_failure BEFORE INSERT ON auth_validation_cache
        WHEN NEW.owner_id='deny:del' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END;
    """)
    with pytest.raises(sqlite3.IntegrityError):
        await delete(db)
    assert db.connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 1
    assert db.connection.execute("SELECT revision FROM auth_validation_cache_revision").fetchone()[0] == 0
    assert db.connection.execute("SELECT count(*) FROM auth_validation_cache").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method,empty", [("GET", False), ("POST", False), ("POST", True)])
async def test_signed_requests_after_withdrawal_fail_closed_and_other_owner_works(database, method, empty, caplog):
    db, _ = database
    store = BookAIRecordsStore(db)
    await store.merge(SUBJECT, [record()], now=NOW)
    await store.merge(OTHER, [record()], now=NOW)
    await delete(db)
    clock = [NOW + 901]
    body = b"" if method == "GET" else json.dumps({"records": [] if empty else [record()]}).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application(db, clock)),
                                base_url="https://test.invalid") as client:
        # A fresh forwarded signature is not proof that the old access session
        # is still entitled to recreate data after deletion.
        response = await client.request(method, RECORDS_PATH, content=body,
                                        headers=signed(method, body, now=clock[0]))
        assert response.status_code == 401
        assert response.json() == {"error": "account_deleted"}
        assert response.headers["cache-control"] == "private, no-store"
        other = await client.get(RECORDS_PATH, headers=signed("GET", subject=OTHER, now=clock[0]))
        assert other.status_code == 200
        assert len(other.json()["records"]) == 1
    assert db.connection.execute("SELECT count(*) FROM bookai_records WHERE subject=?", (SUBJECT,)).fetchone()[0] == 0
    for private in (SUBJECT, SECRET, "synthetic private note"):
        assert private not in response.text
        assert private not in caplog.text


class DeleteBeforeBatch:
    """Pause a prepared request immediately before its transaction takes a lock."""
    def __init__(self, db, deletion_db):
        self.db, self.deletion_db = db, deletion_db

    def prepare(self, sql):
        return self.db.prepare(sql)

    async def batch(self, statements):
        await delete(self.deletion_db)
        return await self.db.batch(statements)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read", "insert", "update", "empty"])
async def test_request_prepared_before_deletion_cannot_read_or_resurrect(database, operation):
    db, deletion_db = database
    if operation in {"read", "update"}:
        await BookAIRecordsStore(db).merge(SUBJECT, [record()], now=NOW)
    store = BookAIRecordsStore(DeleteBeforeBatch(db, deletion_db))
    with pytest.raises(BookAIAccountDeleted, match="^account_deleted$") as failure:
        if operation == "read":
            await store.list(SUBJECT, since=0, limit=100, now=NOW)
        else:
            await store.merge(SUBJECT, [] if operation == "empty" else [record(updated_at=200)], now=NOW)
    assert SUBJECT not in repr(failure.value)
    assert db.connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_writer_committed_first_is_removed_by_same_atomic_delete(database):
    db, deletion_db = database
    assert (await BookAIRecordsStore(db).merge(SUBJECT, [record()], now=NOW))["accepted"] == 1
    await delete(deletion_db)
    assert db.connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0
    with pytest.raises(BookAIAccountDeleted):
        await BookAIRecordsStore(db).merge(SUBJECT, [record(updated_at=200)], now=NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_missing_revocation_schema_is_unavailable_and_never_writes(database, method, caplog):
    db, _ = database
    db.connection.execute("DROP TABLE auth_validation_cache")
    body = b"" if method == "GET" else json.dumps({"records": [record()]}).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application(db, [NOW])),
                                base_url="https://test.invalid") as client:
        response = await client.request(method, RECORDS_PATH, content=body, headers=signed(method, body))
    assert response.status_code == 503
    assert response.json() == {"error": "sync_unavailable"}
    assert db.connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0
    assert "auth_validation_cache" not in response.text
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_allowed_session_cannot_override_deleted_subject_for_records(database):
    db, _ = database
    await delete(db)
    cache = SqliteAuthValidationCache(db, clock=lambda: NOW)
    await cache.record_allowed_session(session_id="fresh-fixture", user_id="fixture-user", account_id=SUBJECT)
    with pytest.raises(BookAIAccountDeleted):
        await BookAIRecordsStore(db).merge(SUBJECT, [record()], now=NOW)


@pytest.mark.asyncio
async def test_slow_signed_body_cannot_outlive_deletion_marker(database):
    db, _ = database
    await delete(db)
    clock = [NOW]
    body = json.dumps({"records": [record()]}).encode()

    async def delayed_body():
        yield body[:10]
        clock[0] += ACCOUNT_DELETION_TTL_SECONDS + 1
        yield body[10:]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(application(db, clock)),
                                base_url="https://test.invalid") as client:
        response = await client.post(RECORDS_PATH, content=delayed_body(), headers=signed("POST", body))
    assert response.status_code == 401
    assert response.json() == {"error": "app_signature_expired"}
    assert db.connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0
