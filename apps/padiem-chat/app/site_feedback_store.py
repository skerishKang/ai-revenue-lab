"""Anonymous, site-scoped feedback for public sites; one D1 database, one ops view."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .d1_rows import rows_from_result
from .feedback_store import FeedbackDailyLimit, FeedbackUnavailable

BODY_CHARS = 2000
MEMO_CHARS = 2000
PAGE_SIZE = 100
STATUSES = frozenset({'new', 'reviewing', 'fixed', 'deferred'})
SITE_KEYS = frozenset({'miraen-home', 'lovetree', 'bookai'})
SITE_FEEDBACK_ID = re.compile(r'sf_[0-9a-f]{32}\Z')
MIRAEN_IMPORT_KEY = re.compile(r'miraen-home:[^:\s]{1,40}:[0-9]{6}(?:_2)?:[0-9]{1,3}\Z')
RATE_HASH = re.compile(r'[0-9a-f]{64}\Z')
_COLUMNS = ('id,site,body,screen_json,status,created_at,updated_at,ops_memo,'
            'external_feedback_id,external_title,external_category,'
            'external_account_subject_id,external_is_ai_customer,external_append,'
            'external_append_created_at,external_created_at,external_status,'
            'external_status_created_at,external_account_name')
# 러브트리 보낸 사람 표시 이름 길이 상한(닉네임). 이메일·소개는 받지 않는다.
ACCOUNT_NAME_CHARS = 60
# #7690: Lovetree 쪽 상태 어휘. 받은함 표시(STATUSES)에 맞게만 옮기고,
# 원래 값은 external_status에 그대로 둔다.
EXTERNAL_STATUSES = frozenset({'received', 'reviewing', 'fixed', 'later', 'closed'})
EXTERNAL_STATUS_TO_CHAT = {'received': 'new', 'reviewing': 'reviewing', 'fixed': 'fixed',
                           'later': 'deferred', 'closed': 'fixed'}
EXTERNAL_CATEGORIES = frozenset({'bug', 'inconvenient', 'feature', 'other'})
INGEST_EVENTS = frozenset({'new', 'append', 'status'})


def _valid_text(value, limit):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not any(ord(c) < 32 and c not in '\n\r\t' for c in value)
            and not any(0xD800 <= ord(c) <= 0xDFFF for c in value))


def _valid_memo(value):
    return value is None or (isinstance(value, str) and len(value) <= MEMO_CHARS
                             and not any(ord(c) < 32 and c not in '\n\r\t' for c in value)
                             and not any(0xD800 <= ord(c) <= 0xDFFF for c in value))


@dataclass(frozen=True)
class SiteFeedbackRecord:
    id: str
    site: str
    body: str = field(repr=False)
    screen: dict | None = field(repr=False)
    status: str
    created_at: str
    updated_at: str
    ops_memo: str | None = None
    external_feedback_id: str | None = None
    external_title: str | None = None
    external_category: str | None = None
    external_account_subject_id: str | None = None
    external_is_ai_customer: bool | None = None
    external_append: str | None = None
    external_append_created_at: str | None = None
    external_created_at: str | None = None
    external_status: str | None = None
    external_status_created_at: str | None = None
    external_account_name: str | None = None

    @classmethod
    def from_row(cls, row):
        values = {name: row[name] for name in ('id', 'site', 'body', 'status', 'created_at', 'updated_at')}
        values['screen'] = json.loads(row['screen_json']) if row.get('screen_json') else None
        values['ops_memo'] = row.get('ops_memo')
        values['external_feedback_id'] = row.get('external_feedback_id')
        values['external_title'] = row.get('external_title')
        values['external_category'] = row.get('external_category')
        values['external_account_subject_id'] = row.get('external_account_subject_id')
        _ai = row.get('external_is_ai_customer')
        values['external_is_ai_customer'] = None if _ai is None else bool(_ai)
        values['external_append'] = row.get('external_append')
        values['external_append_created_at'] = row.get('external_append_created_at')
        values['external_created_at'] = row.get('external_created_at')
        values['external_status'] = row.get('external_status')
        values['external_status_created_at'] = row.get('external_status_created_at')
        values['external_account_name'] = row.get('external_account_name')
        return cls(**values)

    def public(self, *, admin=False):
        item = {name: getattr(self, name) for name in (
            'id', 'site', 'body', 'screen', 'status', 'created_at', 'updated_at', 'ops_memo',
            'external_feedback_id', 'external_title', 'external_category',
            'external_account_subject_id', 'external_is_ai_customer', 'external_append',
            'external_append_created_at', 'external_created_at', 'external_status',
            'external_status_created_at', 'external_account_name')}
        if admin:
            item['sender_label'] = self.sender_label()
        return item

    def sender_label(self):
        """운영센터 보낸 사람 표시. 러브트리 의견은 닉네임과 AI·사람 고객을 붙이고,
        이름도 구분도 없는 공개 접수(로그아웃)만 '익명'으로 둔다."""
        if self.external_is_ai_customer is None:
            return self.external_account_name or '익명'
        kind = 'AI 고객' if self.external_is_ai_customer else '사람 고객'
        if self.external_account_name:
            return f'{self.external_account_name} · {kind}'
        if self.site == 'lovetree' and not self.external_account_subject_id:
            return '익명'
        return kind


class D1SiteFeedbackStore:
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
            return SiteFeedbackRecord.from_row(rows[0]) if rows else None
        except Exception:
            raise FeedbackUnavailable() from None

    async def _cleanup_rate(self, now):
        try:
            current = datetime.fromisoformat(now.replace('Z', '+00:00')).date()
            cutoff = (current - timedelta(days=1)).isoformat()
        except Exception:
            return
        await self._rows('DELETE FROM site_feedback_rate WHERE day < ?', cutoff)

    async def submit(self, site, body, *, screen=None, rate_hash, daily_limit=5,
                     site_daily_limit=200, max_chars=BODY_CHARS, now=None):
        if (site not in SITE_KEYS or not _valid_text(body, max_chars)
                or not isinstance(rate_hash, str) or RATE_HASH.fullmatch(rate_hash) is None
                or type(daily_limit) is not int or daily_limit < 1
                or type(site_daily_limit) is not int or site_daily_limit < 1
                or type(max_chars) is not int or max_chars < 1):
            raise ValueError('feedback_invalid_request')
        now = now or datetime.now().astimezone().replace(microsecond=0).isoformat()
        day = now[:10]
        counted = await self._rows(
            'SELECT COALESCE((SELECT count FROM site_feedback_rate WHERE rate_hash=? AND day=?), 0) AS n', rate_hash, day)
        if int(counted[0]['n']) >= daily_limit:
            raise FeedbackDailyLimit()
        site_counted = await self._rows(
            'SELECT count(*) AS n FROM site_feedback WHERE site=? AND created_day=?', site, day)
        if int(site_counted[0]['n']) >= site_daily_limit:
            raise FeedbackDailyLimit()
        record = await self._record(
            'INSERT INTO site_feedback '
            '(id,site,body,screen_json,created_day,created_at,updated_at) '
            'SELECT ?,?,?,?,substr(?,1,10),?,? RETURNING ' + _COLUMNS,
            'sf_' + uuid.uuid4().hex, site, body,
            json.dumps(screen, ensure_ascii=False, separators=(',', ':')) if screen else None,
            now, now, now)
        if record is None:
            raise FeedbackUnavailable()
        await self._rows(
            'INSERT INTO site_feedback_rate (rate_hash,day,count) VALUES (?,?,1) '
            'ON CONFLICT(rate_hash,day) DO UPDATE SET count=count+1', rate_hash, day)
        await self._cleanup_rate(now)
        return record

    async def list_entries(self, *, site=None, sites=None, status='all', cursor=None):
        predicates, values = [], []
        if site is not None:
            predicates.append('site=?')
            values.append(site)
        elif sites is not None:
            chosen = sorted({value for value in sites if isinstance(value, str) and value})
            if chosen:
                predicates.append('site IN (' + ','.join('?' * len(chosen)) + ')')
                values.extend(chosen)
            else:
                # No assigned sites: answer nothing instead of the whole table.
                predicates.append('0=1')
        if status != 'all':
            predicates.append('status=?')
            values.append(status)
        if cursor:
            predicates.append('(created_at,id) < (SELECT created_at,id FROM site_feedback WHERE id=?)')
            values.append(cursor)
        where = ' WHERE ' + ' AND '.join(predicates) if predicates else ''
        rows = await self._rows('SELECT ' + _COLUMNS + ' FROM site_feedback' + where
                                + ' ORDER BY created_at DESC,id DESC LIMIT ?',
                                *values, PAGE_SIZE + 1)
        try:
            records = [SiteFeedbackRecord.from_row(row) for row in rows[:PAGE_SIZE]]
        except Exception:
            raise FeedbackUnavailable() from None
        return records, records[-1].id if len(rows) > PAGE_SIZE else None

    async def get_record(self, feedback_id):
        if not SITE_FEEDBACK_ID.fullmatch(feedback_id):
            return None
        return await self._record('SELECT ' + _COLUMNS + ' FROM site_feedback WHERE id=?', feedback_id)

    async def set_status(self, feedback_id, status):
        if not SITE_FEEDBACK_ID.fullmatch(feedback_id) or status not in STATUSES:
            raise ValueError('feedback_invalid_request')
        return await self._record(
            'UPDATE site_feedback SET status=?,updated_at=strftime('
            "'%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? RETURNING " + _COLUMNS,
            status, feedback_id)

    async def set_ops_memo(self, feedback_id, memo):
        if not SITE_FEEDBACK_ID.fullmatch(feedback_id) or not _valid_memo(memo):
            raise ValueError('feedback_invalid_request')
        return await self._record(
            'UPDATE site_feedback SET ops_memo=?,updated_at=strftime('
            "'%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? RETURNING " + _COLUMNS,
            memo, feedback_id)

    async def ingest_lovetree(self, *, external_feedback_id, event, body, status, append,
                              is_ai_customer, account_subject_id, category, title,
                              created_at, now=None, account_name=None):
        """#7690: Lovetree 서버-서버 수신. 같은 의견은 한 행으로 갱신한다.

        멱등 키: new는 (site, feedbackId), append는 거기에 createdAt,
        status는 상태값과 createdAt을 함께 본다. 중복은 행을 늘리지 않고
        기존 행을 돌려준다. append·status가 아직 없는 의견이면 None을
        돌려 호출 쪽이 404로 답하게 한다(보낼 쪽 재시도로 'new'가 먼저 온다).
        """
        if (event not in INGEST_EVENTS or status not in EXTERNAL_STATUSES
                or type(external_feedback_id) is not int or external_feedback_id < 1):
            raise ValueError('feedback_invalid_request')
        external_id = str(external_feedback_id)
        chat_status = EXTERNAL_STATUS_TO_CHAT[status]
        now = now or datetime.now().astimezone().replace(microsecond=0).isoformat()
        existing = await self._record(
            'SELECT ' + _COLUMNS + ' FROM site_feedback WHERE site=? AND external_feedback_id=?',
            'lovetree', external_id)
        if event == 'new':
            if existing is not None:
                return existing, False, True
            created_day = created_at[:10] if (isinstance(created_at, str) and len(created_at) >= 10
                                             and created_at[4:5] == '-') else now[:10]
            record = await self._record(
                'INSERT INTO site_feedback '
                '(id,site,body,screen_json,created_day,created_at,updated_at,'
                'external_feedback_id,external_title,external_category,'
                'external_account_subject_id,external_is_ai_customer,external_append,'
                'external_created_at,external_status,external_status_created_at,'
                'external_account_name) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING ' + _COLUMNS,
                'sf_' + uuid.uuid4().hex, 'lovetree', body, None, created_day,
                created_at, now, external_id, title or None, category or None,
                account_subject_id, 1 if is_ai_customer else 0, append,
                created_at, status, created_at, account_name or None)
            if record is None:
                raise FeedbackUnavailable()
            return record, True, False
        if existing is None:
            return None
        if account_name and existing.external_account_name != account_name:
            # 이름은 뒤 사건(덧붙임·상태)으로도 채운다 — 이름을 보내기 전에 들어온 의견, 닉네임 변경.
            renamed = await self._record(
                'UPDATE site_feedback SET external_account_name=? WHERE id=? RETURNING ' + _COLUMNS,
                account_name, existing.id)
            existing = renamed or existing
        if event == 'append':
            if existing.external_append_created_at == created_at:
                return existing, False, True
            combined = append if not existing.external_append else existing.external_append + '\n' + append
            record = await self._record(
                'UPDATE site_feedback SET external_append=?,external_append_created_at=?,'
                'external_status=?,status=?,external_status_created_at=?,updated_at=? '
                'WHERE id=? RETURNING ' + _COLUMNS,
                combined, created_at, status, chat_status, created_at, now, existing.id)
            if record is None:
                raise FeedbackUnavailable()
            return record, False, False
        # status
        if existing.external_status == status and existing.external_status_created_at == created_at:
            return existing, False, True
        record = await self._record(
            'UPDATE site_feedback SET external_status=?,status=?,'
            'external_status_created_at=?,updated_at=? WHERE id=? RETURNING ' + _COLUMNS,
            status, chat_status, created_at, now, existing.id)
        if record is None:
            raise FeedbackUnavailable()
        return record, False, False

    async def import_miraen(self, *, external_key, body, screen, status, created_at, memo,
                            existing_id=None):
        """#8677: operator-only import of AI honorary member feedback for the
        councillor homepage. No public route, no daily quota. The external key
        makes a rerun a no-op, and a rerun never overwrites a status that the
        operations inbox has changed since."""
        if (not isinstance(external_key, str)
                or not MIRAEN_IMPORT_KEY.fullmatch(external_key)
                or not _valid_text(body, BODY_CHARS) or not body.startswith('[AI ')
                or status not in STATUSES or not _valid_memo(memo)
                or not isinstance(screen, dict) or set(screen) != {'width', 'height'}
                or any(type(v) is not int or not 1 <= v <= 10000 for v in screen.values())
                or not isinstance(created_at, str)):
            raise ValueError('feedback_invalid_request')
        try:
            stamp = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('feedback_invalid_request') from None
        if stamp.tzinfo is None or stamp.strftime('%y%m%d') != external_key.split(':')[2][:6]:
            raise ValueError('feedback_invalid_request')
        stored_at = stamp.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        if existing_id is not None:
            if not isinstance(existing_id, str) or not SITE_FEEDBACK_ID.fullmatch(existing_id):
                raise ValueError('feedback_invalid_request')
            record = await self.get_record(existing_id)
            if (record is None or record.site != 'miraen-home'
                    or record.external_feedback_id not in (None, external_key)):
                raise ValueError('feedback_invalid_request')
            if record.external_feedback_id == external_key:
                return record, False
            record = await self._record(
                'UPDATE site_feedback SET external_feedback_id=?,external_is_ai_customer=1 '
                'WHERE id=? AND site=? AND external_feedback_id IS NULL RETURNING ' + _COLUMNS,
                external_key, existing_id, 'miraen-home')
            if record is None:
                raise FeedbackUnavailable()
            return record, False
        record = await self._record(
            'INSERT INTO site_feedback (id,site,body,screen_json,status,created_day,created_at,'
            'updated_at,ops_memo,external_feedback_id,external_is_ai_customer,external_created_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,1,?) ON CONFLICT(site,external_feedback_id) '
            'WHERE external_feedback_id IS NOT NULL DO NOTHING RETURNING ' + _COLUMNS,
            'sf_' + uuid.uuid4().hex, 'miraen-home', body,
            json.dumps(screen, separators=(',', ':')), status, stored_at[:10], stored_at,
            stored_at, memo, external_key, created_at)
        if record is not None:
            return record, True
        record = await self._record(
            'SELECT ' + _COLUMNS + ' FROM site_feedback WHERE site=? AND external_feedback_id=?',
            'miraen-home', external_key)
        if record is None:
            raise FeedbackUnavailable()
        return record, False
