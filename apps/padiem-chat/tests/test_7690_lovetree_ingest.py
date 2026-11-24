"""#7690: Lovetree 서버-서버 수신 — HMAC 서명, 멱등, append·status 갱신."""
import asyncio
import hashlib
import hmac
import json
import secrets
from types import SimpleNamespace

from starlette.requests import Request

from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.site_feedback_routes import site_feedback_ingest
from app.site_feedback_store import D1SiteFeedbackStore, SITE_KEYS
from _support.feedback_store import database

BASE = 'https://chat.example.test'
# 서명 키는 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
_SESSION_SECRET = secrets.token_urlsafe(32)
_CURRENT = secrets.token_urlsafe(32)
_PREVIOUS = secrets.token_urlsafe(32)
_OTHER = secrets.token_urlsafe(32)
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret=_SESSION_SECRET,
                    site_feedback_secret_lovetree=_CURRENT)
SETTINGS_ROTATING = Settings(auth_mode='password', public_base_url=BASE,
                             session_secret=_SESSION_SECRET,
                             site_feedback_secret_lovetree=_CURRENT,
                             site_feedback_secret_lovetree_previous=_PREVIOUS)
SETTINGS_NO_SECRET = Settings(auth_mode='password', public_base_url=BASE,
                              session_secret=_SESSION_SECRET)
NOW_MS = 1_700_000_000_000


def new_payload(feedback_id=101, **over):
    value = {'event': 'new', 'feedbackId': feedback_id, 'body': 'lovetree-body',
             'status': 'received', 'append': None, 'isAiCustomer': True,
             'accountSubjectId': 'subj-lovetree-1', 'category': 'bug',
             'title': 'lovetree-title', 'createdAt': '2026-11-22T10:00:00.000Z'}
    value.update(over)
    return value


def append_payload(feedback_id=101, **over):
    value = {'event': 'append', 'feedbackId': feedback_id, 'body': 'append-body',
             'status': 'reviewing', 'append': 'append-body', 'isAiCustomer': True,
             'accountSubjectId': 'subj-lovetree-1', 'category': '', 'title': '',
             'createdAt': '2026-11-22T11:00:00.000Z'}
    value.update(over)
    return value


def status_payload(feedback_id=101, **over):
    value = {'event': 'status', 'feedbackId': feedback_id, 'body': 'lovetree-body',
             'status': 'fixed', 'append': None, 'isAiCustomer': False,
             'accountSubjectId': 'subj-lovetree-1', 'category': '', 'title': '',
             'createdAt': '2026-11-22T12:00:00.000Z'}
    value.update(over)
    return value


def signed_request(store, payload_value, *, secret=_CURRENT, site='lovetree',
                   timestamp_ms=NOW_MS, settings=SETTINGS, signature=None):
    raw = json.dumps(payload_value, ensure_ascii=False, separators=(',', ':')).encode()
    if signature is None:
        message = str(timestamp_ms).encode() + b'\n' + site.encode() + b'\n' + raw
        signature = 'sha256=' + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    headers = [(b'content-type', b'application/json'),
               (b'x-lt-site', site.encode()),
               (b'x-lt-timestamp', str(timestamp_ms).encode()),
               (b'x-lt-signature', signature.encode())]

    async def receive():
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    state = SimpleNamespace(settings=settings, site_feedback_store=store)
    return Request({'type': 'http', 'method': 'POST', 'path': '/api/site-feedback/ingest',
                    'query_string': b'', 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {},
                    'client': ('203.0.113.9', 12345)}, receive)


def payload(response):
    return json.loads(response.body)


def test_ingest_signature_idempotency_append_status(monkeypatch):
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: NOW_MS)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-22T13:00:00Z')
            assert 'lovetree' in SITE_KEYS

            # 서명 맞음: new가 201로 저장되고 받은함(site) 모양으로 보인다.
            created = await site_feedback_ingest(signed_request(store, new_payload()))
            assert created.status_code == 201
            item = payload(created)['feedback']
            assert item['site'] == 'lovetree' and item['body'] == 'lovetree-body'
            assert item['status'] == 'new' and item['external_status'] == 'received'
            assert item['external_feedback_id'] == '101'
            assert item['external_title'] == 'lovetree-title'
            assert item['external_category'] == 'bug'
            assert item['external_is_ai_customer'] is True

            # 중복: 같은 new를 다시 보내도 행이 늘지 않는다.
            duplicate = await site_feedback_ingest(
                signed_request(store, new_payload(), timestamp_ms=NOW_MS + 1000))
            assert duplicate.status_code == 200 and payload(duplicate)['duplicate'] is True
            rows, _ = await store.list_entries(site='lovetree')
            assert len(rows) == 1

            # 서명 틀림: 다른 키로 서명하면 401, 행이 늘지 않는다.
            wrong = await site_feedback_ingest(
                signed_request(store, new_payload(102), secret=_OTHER))
            assert wrong.status_code == 401
            assert payload(wrong)['error']['code'] == 'feedback_invalid_signature'
            rows, _ = await store.list_entries(site='lovetree')
            assert len(rows) == 1

            # 시각 밖: 6분 지난 시각은 서명이 맞아도 401이다.
            old = await site_feedback_ingest(
                signed_request(store, new_payload(103), timestamp_ms=NOW_MS - 6 * 60 * 1000))
            assert old.status_code == 401
            assert payload(old)['error']['code'] == 'feedback_invalid_signature'

            # 사이트 다름: lovetree가 아닌 사이트는 400이다.
            other_site = await site_feedback_ingest(
                signed_request(store, new_payload(104), site='other-site'))
            assert other_site.status_code == 400
            assert payload(other_site)['error']['code'] == 'feedback_invalid_request'

            # append 갱신: 같은 의견에 덧붙임이 쌓이고 상태도 따라온다.
            appended = await site_feedback_ingest(
                signed_request(store, append_payload(), timestamp_ms=NOW_MS + 2000))
            assert appended.status_code == 200
            item = payload(appended)['feedback']
            assert item['external_append'] == 'append-body'
            assert item['body'] == 'lovetree-body'
            assert item['status'] == 'reviewing' and item['external_status'] == 'reviewing'

            # append 중복: 같은 createdAt은 다시 쌓지 않는다.
            append_dup = await site_feedback_ingest(
                signed_request(store, append_payload(), timestamp_ms=NOW_MS + 3000))
            assert append_dup.status_code == 200 and payload(append_dup)['duplicate'] is True
            assert payload(append_dup)['feedback']['external_append'] == 'append-body'

            # status 갱신: 외부 상태와 받은함 상태가 함께 바뀐다.
            changed = await site_feedback_ingest(
                signed_request(store, status_payload(), timestamp_ms=NOW_MS + 4000))
            assert changed.status_code == 200
            item = payload(changed)['feedback']
            assert item['status'] == 'fixed' and item['external_status'] == 'fixed'

            # status 중복: 같은 상태·시각은 중복으로 답한다.
            status_dup = await site_feedback_ingest(
                signed_request(store, status_payload(), timestamp_ms=NOW_MS + 5000))
            assert status_dup.status_code == 200 and payload(status_dup)['duplicate'] is True

            # 다른 상태는 중복이 아니다: later는 deferred로 보인다.
            later = await site_feedback_ingest(
                signed_request(store, status_payload(status='later', createdAt='2026-11-22T14:00:00.000Z'),
                               timestamp_ms=NOW_MS + 6000))
            assert later.status_code == 200 and 'duplicate' not in payload(later)
            item = payload(later)['feedback']
            assert item['status'] == 'deferred' and item['external_status'] == 'later'

            # 없는 의견의 append는 404다(보낼 쪽 재시도로 new가 먼저 온다).
            missing = await site_feedback_ingest(
                signed_request(store, append_payload(999), timestamp_ms=NOW_MS + 7000))
            assert missing.status_code == 404
            assert payload(missing)['error']['code'] == 'feedback_not_found'

            rows, _ = await store.list_entries(site='lovetree')
            assert len(rows) == 1 and rows[0].external_status == 'later'
        finally:
            db.close()
    asyncio.run(scenario())


def test_ingest_no_secret_503_and_previous_key(monkeypatch):
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: NOW_MS)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-22T13:00:00Z')

            # 비밀 없음: 서명 검증을 할 수 없어 503이다.
            unavailable = await site_feedback_ingest(
                signed_request(store, new_payload(201), settings=SETTINGS_NO_SECRET))
            assert unavailable.status_code == 503
            assert payload(unavailable)['error']['code'] == 'feedback_unavailable'

            # 교체 기간: 이전 키로 서명해도 받아들인다.
            old_key = await site_feedback_ingest(
                signed_request(store, new_payload(202), secret=_PREVIOUS,
                               settings=SETTINGS_ROTATING, timestamp_ms=NOW_MS + 1000))
            assert old_key.status_code == 201
            # 현행 키도 함께 받아들인다.
            new_key = await site_feedback_ingest(
                signed_request(store, new_payload(203), secret=_CURRENT,
                               settings=SETTINGS_ROTATING, timestamp_ms=NOW_MS + 2000))
            assert new_key.status_code == 201
            rows, _ = await store.list_entries(site='lovetree')
            assert len(rows) == 2
        finally:
            db.close()
    asyncio.run(scenario())
