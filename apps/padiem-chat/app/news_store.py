"""Public '새 소식' version notes for signed-in Chat users (#7718 step 2).

Items carry no user identity: the kind, an easy-word title and detail, and how
the change came about ('ai_tester' / 'user' / 'none') are all that is stored.
A feedback row points at the note that fixed it through product_feedback.news_number.

#7847 adds one more public value: the deployment a note belongs to (`version`,
`YYYY.MM.DD`). It is a date only, so the screen can group notes under their
deployment without storing an operator name, a build id or an issue number.
Empty means 'no deployment' and the screen groups those notes last.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .d1_rows import rows_from_result
from .feedback_store import FEEDBACK_ID

KINDS = frozenset({'improved', 'fixed'})
SOURCES = frozenset({'ai_tester', 'user', 'none'})
NEWS_PAGE = 50
TITLE_CHARS = 120
DETAIL_CHARS = 1000
#: The only accepted deployment shape. Nothing else is stored, so a build id or
#: an internal tag can never leak into the public list through this column.
VERSION = re.compile(r'\A\d{4}\.\d{2}\.\d{2}\Z')


def version_or_empty(value):
    """Return the accepted deployment string, or '' when it is not one.

    A row written before this column existed reads back as '', and a value the
    screen does not recognise folds into the same group instead of dropping the
    whole list.
    """
    return value if isinstance(value, str) and VERSION.match(value) else ''


def _row_value(row, name):
    """Read one optional column from either row shape; a missing one is ''.

    Both row shapes are in use (an sqlite3.Row here, a plain dict on the COM2
    host), and `in` does not answer the same question on both — one asks about
    values. A read that cannot find the column means the row predates the
    column, not that the list is broken.
    """
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return ''


class NewsUnavailable(Exception):
    def __init__(self):
        super().__init__('news_unavailable')


@dataclass(frozen=True)
class NewsRecord:
    number: int
    kind: str
    title: str = field(repr=False)
    detail: str = field(repr=False)
    source: str = 'none'
    published_at: str = ''
    version: str = ''

    @classmethod
    def from_row(cls, row):
        return cls(number=int(row['number']), kind=row['kind'], title=row['title'],
                   detail=row['detail'], source=row['source'], published_at=row['published_at'],
                   version=version_or_empty(_row_value(row, 'version')))

    def public(self):
        # The source value itself never carries a name; the screen renders the
        # fixed two-word labels from it.
        return {'number': self.number, 'kind': self.kind, 'title': self.title,
                'detail': self.detail, 'source': self.source,
                'published_at': self.published_at, 'version': self.version}


def _validate_content(kind, title, detail, source, version):
    if (not isinstance(kind, str) or kind not in KINDS
            or not isinstance(source, str) or source not in SOURCES
            or not isinstance(title, str) or not title.strip() or len(title) > TITLE_CHARS
            or not isinstance(detail, str) or not detail.strip() or len(detail) > DETAIL_CHARS
            or not isinstance(version, str) or (version and not VERSION.match(version))
            or any(ord(c) < 32 and c not in '\n\r\t' for c in title + detail)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in title + detail)):
        raise ValueError('news_invalid_request')


class D1NewsStore:
    def __init__(self, db, *, now=None):
        if db is None or not callable(getattr(db, 'prepare', None)):
            raise NewsUnavailable()
        self._db = db
        self._now = now

    async def _rows(self, sql, *values):
        try:
            rows = rows_from_result(await self._db.prepare(sql).bind(*values).run())
            return [dict(row.to_py() if callable(getattr(row, 'to_py', None)) else row) for row in rows]
        except Exception:
            raise NewsUnavailable() from None

    async def create(self, kind, title, detail, source, version=''):
        _validate_content(kind, title, detail, source, version)
        rows = await self._rows(
            'INSERT INTO product_news (kind,title,detail,source,published_at,version) '
            "VALUES (?,?,?,?,COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now')),?) "
            'RETURNING number,kind,title,detail,source,published_at,version',
            kind, title, detail, source, self._now() if self._now else None, version)
        try:
            return NewsRecord.from_row(rows[0])
        except Exception:
            raise NewsUnavailable() from None

    async def update(self, number, kind, title, detail, source, version=''):
        """Edit the public copy without changing its number or first publication time."""
        if type(number) is not int or number < 1:
            raise ValueError('news_invalid_request')
        _validate_content(kind, title, detail, source, version)
        rows = await self._rows(
            'UPDATE product_news SET kind=?,title=?,detail=?,source=?,version=? WHERE number=? '
            'RETURNING number,kind,title,detail,source,published_at,version',
            kind, title, detail, source, version, number)
        try:
            return NewsRecord.from_row(rows[0]) if rows else None
        except Exception:
            raise NewsUnavailable() from None

    async def linked_feedback(self, numbers):
        """Admin-only lookup of feedback IDs; never included in public news."""
        if not numbers:
            return {}
        if len(numbers) > NEWS_PAGE or any(type(n) is not int or n < 1 for n in numbers):
            raise ValueError('news_invalid_request')
        placeholders = ','.join('?' for _ in numbers)
        rows = await self._rows(
            'SELECT id,news_number FROM product_feedback WHERE news_number IN ('
            + placeholders + ') ORDER BY id', *numbers)
        links = {number: [] for number in numbers}
        for row in rows:
            links[row['news_number']].append(row['id'])
        return links

    async def get(self, number):
        if type(number) is not int or number < 1:
            raise ValueError('news_invalid_request')
        rows = await self._rows('SELECT number,kind,title,detail,source,published_at,version '
                                'FROM product_news WHERE number=?', number)
        try:
            return NewsRecord.from_row(rows[0]) if rows else None
        except Exception:
            raise NewsUnavailable() from None

    async def list_recent(self, limit=NEWS_PAGE):
        if type(limit) is not int or not 1 <= limit <= NEWS_PAGE:
            raise ValueError('news_invalid_request')
        rows = await self._rows('SELECT number,kind,title,detail,source,published_at,version '
                                'FROM product_news ORDER BY published_at DESC, number DESC LIMIT ?',
                                limit)
        try:
            return [NewsRecord.from_row(row) for row in rows]
        except Exception:
            raise NewsUnavailable() from None

    async def unread_count(self, user_id):
        if not isinstance(user_id, str) or not user_id:
            raise ValueError('news_invalid_request')
        rows = await self._rows(
            'SELECT count(*) AS n FROM product_news WHERE published_at > '
            'COALESCE((SELECT news_read_at FROM users WHERE id=?), \'\')', user_id)
        return int(rows[0]['n'])

    async def mark_seen(self, user_id, *, now=None):
        if not isinstance(user_id, str) or not user_id:
            raise ValueError('news_invalid_request')
        await self._rows(
            'UPDATE users SET news_read_at=COALESCE(?,strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\')) '
            'WHERE id=?', now, user_id)

    async def update_source(self, number, source):
        """Change only the source of one already published item (#7847 follow-up)."""
        if type(number) is not int or number < 1 or source not in SOURCES:
            raise ValueError('news_invalid_request')
        rows = await self._rows(
            'UPDATE product_news SET source=? WHERE number=? '
            'RETURNING number,kind,title,detail,source,published_at,version',
            source, number)
        try:
            return NewsRecord.from_row(rows[0]) if rows else None
        except Exception:
            raise NewsUnavailable() from None

    async def link_feedback(self, feedback_id, number):
        """Point one feedback row at a news item. No user names involved."""
        if not FEEDBACK_ID.fullmatch(feedback_id) or type(number) is not int or number < 1:
            raise ValueError('news_invalid_request')
        rows = await self._rows(
            'UPDATE product_feedback SET news_number=? WHERE id=? AND EXISTS '
            '(SELECT 1 FROM product_news WHERE number=?) '
            'AND (news_number IS NULL OR news_number=?) '
            'RETURNING id,news_number', number, feedback_id, number, number)
        return bool(rows)
