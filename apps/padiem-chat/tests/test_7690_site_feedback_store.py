"""#7690 site feedback store: anonymous rows, site filter, status/memo, daily hash limit."""
import asyncio

import pytest

from app.d1_sqlite import SqliteD1
from app.feedback_store import FeedbackDailyLimit
from app.site_feedback_store import D1SiteFeedbackStore
from test_7680_feedback_store import database

HASH = 'a' * 64
BODY = 'site-feedback-body'
NOW = '2026-11-15T00:00:00.000Z'


def test_submit_list_status_memo_and_daily_limit():
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            row = await store.submit(
                'miraen-home', BODY,
                screen={'url': 'https://councillor-prototype-v2.pages.dev/', 'width': 390, 'height': 844},
                rate_hash=HASH, now=NOW)
            assert row.id.startswith('sf_') and row.site == 'miraen-home' and row.status == 'new'
            assert row.ops_memo is None and row.screen['width'] == 390
            with pytest.raises(FeedbackDailyLimit):
                await store.submit('miraen-home', BODY, rate_hash=HASH, daily_limit=1, now=NOW)
            rows, cursor = await store.list_entries()
            assert len(rows) == 1 and cursor is None and rows[0].id == row.id
            assert (await store.set_status(row.id, 'fixed')).status == 'fixed'
            assert (await store.set_ops_memo(row.id, 'ops memo')).ops_memo == 'ops memo'
            record = await store.get_record(row.id)
            assert record.status == 'fixed' and record.ops_memo == 'ops memo'
            await store._cleanup_rate('2026-11-17T00:00:00.000Z')
            assert db.execute('SELECT count(*) FROM site_feedback_rate').fetchone()[0] == 0
            with pytest.raises(ValueError):
                await store.submit('other-site', BODY, rate_hash=HASH, now=NOW)
            with pytest.raises(ValueError):
                await store.submit('miraen-home', 'x' * 2001, rate_hash=HASH, now=NOW)
        finally:
            db.close()
    asyncio.run(scenario())