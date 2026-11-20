"""Feedback SQL over local SQLite; no browser, HTTP service or remote storage."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

from app.account_deletion import _delete_batch
from app.d1_sqlite import SqliteD1
from app.feedback_store import D1FeedbackStore, FeedbackDailyLimit, FeedbackUnavailable, FeedbackOwnerMissing
from _support.feedback_store import OWNER, OTHER, BODY, database


def test_submission_owner_isolation_status_and_versioned_read():
    async def scenario():
        db, store = database()
        try:
            row = await store.submit(OWNER, BODY)
            await store.submit(OTHER, 'foreign fixture')
            mine, cursor = await store.list_entries(user_id=OWNER)
            assert [r.id for r in mine] == [row.id] and cursor is None
            assert await store.mark_read(OTHER, row.id, 1) is None
            fixed = await store.set_status(row.id, 'fixed')
            assert fixed.fixed_version == 1 and fixed.public()['unread_fixed']
            assert await store.unread_count(OWNER) == 1
            assert (await store.set_status(row.id, 'fixed')).fixed_version == 1
            await store.set_status(row.id, 'reviewing')
            fixed = await store.set_status(row.id, 'fixed')
            assert fixed.fixed_version == 2
            stale = await store.mark_read(OWNER, row.id, 1)
            assert stale.public()['unread_fixed']
            assert not (await store.mark_read(OWNER, row.id, 2)).public()['unread_fixed']
            assert await store.unread_count(OWNER) == 0
            assert OWNER not in repr(row) and BODY not in repr(row)
            # #8035 ②: the admin view carries the sender identity; the
            # non-admin view never does.
            assert fixed.public(admin=True)['sender_user_id'] == OWNER
            assert 'user_id' not in fixed.public()
        finally:
            db.close()
    asyncio.run(scenario())


def test_daily_limit_is_atomic_across_independent_database_connections(tmp_path):
    path = tmp_path / 'quota.sqlite3'
    db, _ = database(path)
    db.close()
    barrier = threading.Barrier(16)
    def writer(_):
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        store = D1FeedbackStore(SqliteD1(conn))
        barrier.wait(timeout=15)
        try:
            asyncio.run(store.submit(OWNER, BODY, daily_limit=10))
            return 'saved'
        except FeedbackDailyLimit:
            return 'limited'
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(writer, range(16)))
    assert results.count('saved') == 10 and results.count('limited') == 6
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute('SELECT count(*) FROM product_feedback').fetchone()[0] == 10
        conn.execute("UPDATE product_feedback SET created_day=date('now','-1 day')")
        store = D1FeedbackStore(SqliteD1(conn))
        assert asyncio.run(store.submit(OWNER, BODY)).id
        assert asyncio.run(store.submit(OTHER, BODY)).id
    finally:
        conn.close()


def test_ack_races_new_fixed_revision_without_consuming_it(tmp_path):
    path = tmp_path / 'read.sqlite3'
    db, store = database(path)
    row = asyncio.run(store.submit(OWNER, BODY))
    asyncio.run(store.set_status(row.id, 'fixed'))
    db.close()
    barrier = threading.Barrier(2)
    def change(ack):
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        store = D1FeedbackStore(SqliteD1(conn))
        async def scenario():
            if ack:
                await store.mark_read(OWNER, row.id, 1)
            else:
                await store.set_status(row.id, 'reviewing')
                await store.set_status(row.id, 'fixed')
        barrier.wait(timeout=15)
        try:
            asyncio.run(scenario())
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(change, (True, False)))
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        record = asyncio.run(D1FeedbackStore(SqliteD1(conn)).list_entries(user_id=OWNER))[0][0]
        assert record.fixed_version == 2 and record.read_version <= 1
        assert record.public()['unread_fixed']
    finally:
        conn.close()


def test_cursor_and_unread_count_are_owner_scoped():
    async def scenario():
        db, store = database()
        try:
            for n in range(105):
                await store.submit(OWNER, str(n), daily_limit=200)
            foreign = await store.submit(OTHER, BODY)
            first, cursor = await store.list_entries(user_id=OWNER)
            second, end = await store.list_entries(user_id=OWNER, cursor=cursor)
            assert len(first) == 100 and len(second) == 5 and end is None
            assert not set(r.id for r in first) & set(r.id for r in second)
            assert (await store.list_entries(user_id=OWNER, cursor=foreign.id))[0] == []
        finally:
            db.close()
    asyncio.run(scenario())


def test_account_delete_explicitly_deletes_feedback_without_foreign_keys():
    async def scenario():
        conn, store = database(full=True)
        try:
            mine = await store.submit(OWNER, BODY)
            other = await store.submit(OTHER, BODY)
            db = SqliteD1(conn)
            assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 0
            await db.batch(_delete_batch(db, OWNER))
            assert conn.execute('SELECT id FROM product_feedback WHERE id=?', (mine.id,)).fetchone() is None
            assert conn.execute('SELECT id FROM product_feedback WHERE id=?', (other.id,)).fetchone()
            # The session could have been authenticated before this deletion.
            # A late writer must not recreate rows after the deletion batch.
            with pytest.raises(FeedbackOwnerMissing):
                await store.submit(OWNER, BODY)
            assert (await store.list_entries(user_id=OWNER))[0] == []
        finally:
            conn.close()
    asyncio.run(scenario())


def test_storage_failures_do_not_retain_sensitive_exception_arguments(caplog, capsys):
    class Broken:
        def prepare(self, _):
            raise RuntimeError(BODY + OWNER)
    async def scenario():
        store = D1FeedbackStore(Broken())
        with pytest.raises(FeedbackUnavailable) as caught:
            await store.submit(OWNER, BODY)
        exposed = repr(caught.value) + str(caught.value) + repr(store)
        assert BODY not in exposed and OWNER not in exposed
    asyncio.run(scenario())
    assert BODY not in caplog.text + capsys.readouterr().out
