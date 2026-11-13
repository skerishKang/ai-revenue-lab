"""Private feedback persistence, independent of the Chat presentation and routes."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from .d1_rows import rows_from_result

BODY_CHARS = 4000
PAGE_SIZE = 100
STATUSES = frozenset({'new', 'reviewing', 'fixed', 'deferred'})
FEEDBACK_ID = re.compile(r'fb_[0-9a-f]{32}\Z')
_COLUMNS = 'id,user_id,body,screen_json,status,created_at,updated_at,fixed_version,read_version'


class FeedbackUnavailable(Exception):
    def __init__(self):
        super().__init__('feedback_unavailable')


class FeedbackDailyLimit(Exception):
    def __init__(self):
        super().__init__('feedback_daily_limit')


class FeedbackOwnerMissing(Exception):
    def __init__(self):
        super().__init__('authentication_required')


@dataclass(frozen=True)
class FeedbackRecord:
    id: str
    user_id: str = field(repr=False)
    body: str = field(repr=False)
    screen: dict | None = field(repr=False)
    status: str
    created_at: str
    updated_at: str
    fixed_version: int
    read_version: int

    @classmethod
    def from_row(cls, row):
        return cls(**{name: row[name] for name in cls.__dataclass_fields__ if name != 'screen'},
                   screen=json.loads(row['screen_json']) if row['screen_json'] else None)

    def public(self, *, admin=False):
        item = {name: getattr(self, name) for name in (
            'id', 'body', 'screen', 'status', 'created_at', 'updated_at', 'fixed_version')}
        item['unread_fixed'] = self.status == 'fixed' and self.fixed_version > self.read_version
        if admin:
            item['sender_label'] = '••••' + self.user_id[-4:]
        return item


class D1FeedbackStore:
    def __init__(self, db):
        if db is None or not callable(getattr(db, 'prepare', None)):
            raise FeedbackUnavailable()
        self._db = db

    async def _rows(self, sql, *values):
        try:
            rows = rows_from_result(await self._db.prepare(sql).bind(*values).run())
            return [dict(row.to_py() if callable(getattr(row, 'to_py', None)) else row) for row in rows]
        except Exception:
            raise FeedbackUnavailable() from None

    async def _record(self, sql, *values):
        rows = await self._rows(sql, *values)
        try:
            return FeedbackRecord.from_row(rows[0]) if rows else None
        except Exception:
            raise FeedbackUnavailable() from None

    async def submit(self, user_id, body, *, screen=None, daily_limit=10, max_chars=BODY_CHARS):
        if (type(max_chars) is not int or max_chars < 1
                or not isinstance(body, str) or not body.strip() or len(body) > max_chars
                or type(daily_limit) is not int or daily_limit < 1):
            raise ValueError('feedback_invalid_request')
        # The quota predicate and insertion are ONE writer statement. There is
        # no read-then-write window across processes; UTC is the database clock.
        record = await self._record(
            'INSERT INTO product_feedback '
            '(id,user_id,body,screen_json,created_day,created_at,updated_at) '
            "SELECT ?,?,?,?,date('now'),strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
            "strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            'WHERE EXISTS (SELECT 1 FROM users WHERE id=?) AND '
            '(SELECT count(*) FROM product_feedback '
            "WHERE user_id=? AND created_day=date('now')) < ? RETURNING " + _COLUMNS,
            'fb_' + uuid.uuid4().hex, user_id, body,
            json.dumps(screen, ensure_ascii=False, separators=(',', ':')) if screen else None,
            user_id, user_id, daily_limit)
        if record is None:
            if not await self._rows('SELECT id FROM users WHERE id=?', user_id):
                raise FeedbackOwnerMissing()
            raise FeedbackDailyLimit()
        return record

    async def list_entries(self, *, user_id=None, status='all', cursor=None):
        predicates, values = [], []
        if user_id is not None:
            predicates.append('user_id=?')
            values.append(user_id)
        if status != 'all':
            predicates.append('status=?')
            values.append(status)
        if cursor:
            scope = ' AND user_id=?' if user_id is not None else ''
            predicates.append('(created_at,id) < (SELECT created_at,id FROM product_feedback WHERE id=?' + scope + ')')
            values.append(cursor)
            if user_id is not None:
                values.append(user_id)
        where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
        rows = await self._rows('SELECT ' + _COLUMNS + ' FROM product_feedback' + where
                                + ' ORDER BY created_at DESC,id DESC LIMIT ?', *values, PAGE_SIZE + 1)
        try:
            records = [FeedbackRecord.from_row(row) for row in rows[:PAGE_SIZE]]
        except Exception:
            raise FeedbackUnavailable() from None
        return records, records[-1].id if len(rows) > PAGE_SIZE else None

    async def unread_count(self, user_id):
        rows = await self._rows("SELECT count(*) AS n FROM product_feedback WHERE user_id=? "
                                "AND status='fixed' AND fixed_version>read_version", user_id)
        return int(rows[0]['n'])

    async def set_status(self, feedback_id, status):
        if not FEEDBACK_ID.fullmatch(feedback_id) or status not in STATUSES:
            raise ValueError('feedback_invalid_request')
        return await self._record(
            'UPDATE product_feedback SET '
            "fixed_version=fixed_version+CASE WHEN status!='fixed' AND ?='fixed' THEN 1 ELSE 0 END,"
            "updated_at=CASE WHEN status!=? THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE updated_at END,"
            'status=? WHERE id=? RETURNING ' + _COLUMNS, status, status, status, feedback_id)

    async def mark_read(self, user_id, feedback_id, fixed_version):
        # A delayed acknowledgement cannot consume a newer fixed notification.
        await self._rows('UPDATE product_feedback SET read_version=fixed_version '
                         "WHERE id=? AND user_id=? AND status='fixed' AND fixed_version=?",
                         feedback_id, user_id, fixed_version)
        return await self._record('SELECT ' + _COLUMNS + ' FROM product_feedback WHERE id=? AND user_id=?',
                                  feedback_id, user_id)
