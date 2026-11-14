"""Private feedback persistence, independent of the Chat presentation and routes."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field, replace

from .d1_rows import rows_from_result

BODY_CHARS = 4000
PAGE_SIZE = 100
STATUSES = frozenset({'new', 'reviewing', 'fixed', 'deferred'})
SIDES = frozenset({'ops', 'user'})
FEEDBACK_ID = re.compile(r'fb_[0-9a-f]{32}\Z')
_COLUMNS = ('id,user_id,body,screen_json,status,created_at,updated_at,'
            'fixed_version,read_version,ops_reply_read_at')
_LIST_COLUMNS = ('f.id,f.user_id,f.body,f.screen_json,f.status,f.created_at,'
                 'f.updated_at,f.fixed_version,f.read_version,f.ops_reply_read_at,'
                 'u.display_name AS sender_display,u.ai_tester AS is_ai_tester')


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
class FeedbackReplyRecord:
    id: str
    feedback_id: str
    side: str
    body: str = field(repr=False)
    created_at: str

    @classmethod
    def from_row(cls, row):
        return cls(id=row['id'], feedback_id=row['feedback_id'], side=row['side'],
                   body=row['body'], created_at=row['created_at'])

    def public(self):
        return {'id': self.id, 'side': self.side, 'body': self.body, 'created_at': self.created_at}


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
    ops_reply_read_at: str | None = None
    replies: tuple[FeedbackReplyRecord, ...] = ()
    sender_display: str = field(default='', repr=False)
    is_ai_tester: bool = False

    @classmethod
    def from_row(cls, row):
        values = {name: row[name] for name in (
            'id', 'user_id', 'body', 'status', 'created_at', 'updated_at',
            'fixed_version', 'read_version')}
        values['screen'] = json.loads(row['screen_json']) if row.get('screen_json') else None
        values['ops_reply_read_at'] = row.get('ops_reply_read_at')
        values['sender_display'] = row.get('sender_display') or ''
        values['is_ai_tester'] = bool(row.get('is_ai_tester'))
        return cls(**values)

    def unread_ops_replies(self):
        ops = [reply for reply in self.replies if reply.side == 'ops']
        if not self.ops_reply_read_at:
            return len(ops)
        return sum(1 for reply in ops if reply.created_at > self.ops_reply_read_at)

    def public(self, *, admin=False):
        item = {name: getattr(self, name) for name in (
            'id', 'body', 'screen', 'status', 'created_at', 'updated_at', 'fixed_version')}
        item['unread_fixed'] = self.status == 'fixed' and self.fixed_version > self.read_version
        item['unread_ops_replies'] = self.unread_ops_replies()
        item['replies'] = [reply.public() for reply in self.replies]
        if admin:
            item['sender_label'] = '••••' + self.user_id[-4:]
            item['is_ai_tester'] = self.is_ai_tester
            if self.is_ai_tester and self.sender_display:
                item['sender_display'] = self.sender_display
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

    async def _replies_for(self, feedback_ids):
        if not feedback_ids:
            return {}
        placeholders = ','.join('?' for _ in feedback_ids)
        rows = await self._rows(
            'SELECT id,feedback_id,side,body,created_at FROM product_feedback_reply '
            'WHERE feedback_id IN (' + placeholders + ') ORDER BY created_at,id',
            *feedback_ids)
        grouped = {}
        for row in rows:
            grouped.setdefault(row['feedback_id'], []).append(FeedbackReplyRecord.from_row(row))
        return grouped

    async def submit(self, user_id, body, *, screen=None, daily_limit=10, max_chars=BODY_CHARS):
        if (type(max_chars) is not int or max_chars < 1
                or not isinstance(body, str) or not body.strip() or len(body) > max_chars
                or type(daily_limit) is not int or daily_limit < 1):
            raise ValueError('feedback_invalid_request')
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
            predicates.append('f.user_id=?')
            values.append(user_id)
        if status != 'all':
            predicates.append('f.status=?')
            values.append(status)
        if cursor:
            scope = ' AND user_id=?' if user_id is not None else ''
            predicates.append('(f.created_at,f.id) < (SELECT created_at,id FROM product_feedback WHERE id=?' + scope + ')')
            values.append(cursor)
            if user_id is not None:
                values.append(user_id)
        where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
        rows = await self._rows('SELECT ' + _LIST_COLUMNS + ' FROM product_feedback f '
                                'LEFT JOIN users u ON u.id=f.user_id' + where
                                + ' ORDER BY f.created_at DESC,f.id DESC LIMIT ?',
                                *values, PAGE_SIZE + 1)
        try:
            records = [FeedbackRecord.from_row(row) for row in rows[:PAGE_SIZE]]
        except Exception:
            raise FeedbackUnavailable() from None
        replies = await self._replies_for([record.id for record in records])
        records = [replace(record, replies=tuple(replies.get(record.id, ()))) for record in records]
        return records, records[-1].id if len(rows) > PAGE_SIZE else None

    async def unread_count(self, user_id):
        rows = await self._rows("SELECT count(*) AS n FROM product_feedback WHERE user_id=? "
                                "AND status='fixed' AND fixed_version>read_version", user_id)
        return int(rows[0]['n'])

    async def unread_replies_count(self, user_id):
        rows = await self._rows(
            "SELECT count(*) AS n FROM product_feedback_reply r "
            "JOIN product_feedback f ON f.id=r.feedback_id "
            "WHERE f.user_id=? AND r.side='ops' "
            "AND (f.ops_reply_read_at IS NULL OR r.created_at > f.ops_reply_read_at)", user_id)
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
        await self._rows('UPDATE product_feedback SET read_version=fixed_version '
                         "WHERE id=? AND user_id=? AND status='fixed' AND fixed_version=?",
                         feedback_id, user_id, fixed_version)
        return await self._record('SELECT ' + _COLUMNS + ' FROM product_feedback WHERE id=? AND user_id=?',
                                  feedback_id, user_id)

    async def mark_replies_read(self, user_id, feedback_ids, *, now=None):
        ids = [feedback_id for feedback_id in feedback_ids if FEEDBACK_ID.fullmatch(feedback_id)]
        if not user_id or not ids:
            return
        placeholders = ','.join('?' for _ in ids)
        await self._rows(
            'UPDATE product_feedback SET ops_reply_read_at='
            "COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
            'WHERE user_id=? AND id IN (' + placeholders + ') AND EXISTS '
            "(SELECT 1 FROM product_feedback_reply WHERE feedback_id=product_feedback.id AND side='ops')",
            now, user_id, *ids)

    async def add_reply(self, feedback_id, side, body, *, user_id=None, now=None):
        if (not FEEDBACK_ID.fullmatch(feedback_id) or side not in SIDES
                or not isinstance(body, str) or not body.strip() or len(body) > BODY_CHARS
                or any(ord(c) < 32 and c not in '\n\r\t' for c in body)
                or any(0xD800 <= ord(c) <= 0xDFFF for c in body)):
            raise ValueError('feedback_invalid_request')
        if side == 'user' and not user_id:
            raise ValueError('feedback_invalid_request')
        scope = ' AND user_id=?' if side == 'user' else ''
        values = ['fbr_' + uuid.uuid4().hex, feedback_id, side, body, now, feedback_id]
        if side == 'user':
            values.append(user_id)
        rows = await self._rows(
            'INSERT INTO product_feedback_reply (id,feedback_id,side,body,created_at) '
            "SELECT ?,?,?,?,COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
            'WHERE EXISTS (SELECT 1 FROM product_feedback WHERE id=?' + scope + ') '
            'RETURNING id,feedback_id,side,body,created_at', *values)
        try:
            return FeedbackReplyRecord.from_row(rows[0]) if rows else None
        except Exception:
            raise FeedbackUnavailable() from None

    async def get_record(self, feedback_id, *, user_id=None):
        if not FEEDBACK_ID.fullmatch(feedback_id):
            return None
        if user_id is not None:
            rows = await self._rows('SELECT ' + _LIST_COLUMNS + ' FROM product_feedback f '
                                    'LEFT JOIN users u ON u.id=f.user_id '
                                    'WHERE f.id=? AND f.user_id=?', feedback_id, user_id)
        else:
            rows = await self._rows('SELECT ' + _LIST_COLUMNS + ' FROM product_feedback f '
                                    'LEFT JOIN users u ON u.id=f.user_id WHERE f.id=?', feedback_id)
        if not rows:
            return None
        record = FeedbackRecord.from_row(rows[0])
        replies = await self._replies_for([record.id])
        return replace(record, replies=tuple(replies.get(record.id, ())))

    async def set_ai_tester(self, feedback_id, enabled):
        if not FEEDBACK_ID.fullmatch(feedback_id) or type(enabled) is not bool:
            raise ValueError('feedback_invalid_request')
        await self._rows('UPDATE users SET ai_tester=? '
                         'WHERE id=(SELECT user_id FROM product_feedback WHERE id=?)',
                         int(enabled), feedback_id)
        return await self.get_record(feedback_id)
