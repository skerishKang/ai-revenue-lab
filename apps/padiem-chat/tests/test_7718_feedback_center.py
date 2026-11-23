"""#7718 1단계 store contracts: reply thread, read marker, AI flag, deletion."""
import asyncio

import pytest

from app.account_deletion import _delete_batch
from app.d1_sqlite import SqliteD1
from _support.feedback_store import BODY, OTHER, OWNER, database


def test_reply_thread_owner_isolation_unread_marker_and_read_race():
    async def scenario():
        db, store = database()
        try:
            row = await store.submit(OWNER, BODY)
            ops = await store.add_reply(row.id, 'ops', 'operator reply', now='2026-11-14T01:00:00.000Z')
            assert ops.side == 'ops'
            mine = await store.add_reply(row.id, 'user', 'user follow-up', user_id=OWNER,
                                         now='2026-11-14T02:00:00.000Z')
            assert mine.side == 'user'
            assert await store.add_reply(row.id, 'user', 'foreign follow-up', user_id=OTHER) is None
            record = await store.get_record(row.id)
            assert [reply.side for reply in record.replies] == ['ops', 'user']
            assert record.unread_ops_replies() == 1
            assert await store.unread_replies_count(OWNER) == 1
            await store.mark_replies_read(OWNER, [row.id], now='2026-11-14T03:00:00.000Z')
            assert (await store.get_record(row.id)).unread_ops_replies() == 0
            assert await store.unread_replies_count(OWNER) == 0
            await store.add_reply(row.id, 'ops', 'later reply', now='2026-11-14T04:00:00.000Z')
            assert (await store.get_record(row.id)).unread_ops_replies() == 1
            assert BODY not in repr(record) and OWNER not in repr(record)
            assert 'operator reply' not in repr(record)
        finally:
            db.close()
    asyncio.run(scenario())


def test_admin_list_marks_ai_tester_without_user_leak():
    async def scenario():
        db, store = database()
        try:
            row = await store.submit(OWNER, BODY)
            await store.set_ai_tester(row.id, True)
            admin = (await store.list_entries())[0][0]
            assert admin.is_ai_tester is True
            assert admin.public(admin=True)['is_ai_tester'] is True
            assert 'sender_display' not in admin.public(admin=True)
            # #8035 ② (대표 결정): 관리자에게는 보낸 사람 신원을 공개한다.
            assert admin.public(admin=True)['sender_user_id'] == OWNER
            assert OWNER in repr(admin.public(admin=True))
            # 비관리자 화면에는 신원이 그대로 0이다.
            assert 'sender_user_id' not in admin.public()
            db.execute("UPDATE users SET display_name='정호' WHERE id=?", (OWNER,))
            admin = (await store.list_entries())[0][0]
            assert admin.public(admin=True)['sender_display'] == '정호'
            mine = (await store.list_entries(user_id=OWNER))[0][0]
            assert 'is_ai_tester' not in mine.public()
            assert 'sender_display' not in mine.public()
            await store.set_ai_tester(row.id, False)
            assert (await store.get_record(row.id)).is_ai_tester is False
        finally:
            db.close()
    asyncio.run(scenario())


def test_reply_validation_and_account_deletion_removes_thread():
    async def scenario():
        db, store = database(full=True)
        try:
            row = await store.submit(OWNER, BODY)
            await store.add_reply(row.id, 'ops', 'operator reply')
            for feedback_id, side, body in (
                    (row.id, 'side', 'x'), (row.id, 'ops', ''), (row.id, 'ops', 'x' * 4001),
                    ('bad', 'ops', 'x')):
                with pytest.raises(ValueError):
                    await store.add_reply(feedback_id, side, body)
            with pytest.raises(ValueError):
                await store.add_reply(row.id, 'user', 'x')
            d1 = SqliteD1(db)
            await d1.batch(_delete_batch(d1, OWNER))
            assert db.execute('SELECT id FROM product_feedback_reply').fetchone() is None
            assert db.execute('SELECT id FROM product_feedback').fetchone() is None
        finally:
            db.close()
    asyncio.run(scenario())