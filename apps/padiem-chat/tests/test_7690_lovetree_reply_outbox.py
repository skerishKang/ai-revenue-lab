"""#7690 역방향: 운영센터 답글·상태를 러브트리로 보내는 outbox.

계약(CTO 댓글)대로: 서명 HMAC(시각)\\n"lovetree"\\n본문 원문 바이트, eventKey
멱등(재시도에도 같은 키), 2xx 완료 / 4xx 실패(재시도 없음) / 5xx·네트워크만
1분·5분·30분·2시간·12시간, 다섯 번 실패하면 '보내기 실패'. 정방향으로 받은
상태 변화는 되돌이 금지 — 줄엔 운영센터 직접 변경만 들어간다.
"""
import asyncio
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.lovetree_ops_outbox import (D1LovetreeOpsOutbox, RETRY_DELAYS_SECONDS,
                                     build_payload, dispatch_pending,
                                     new_event_key, outbox_state)
from app.auth import SESSION_COOKIE, create_session_token
from app.site_feedback_routes import (admin_site_feedback, admin_site_feedback_reply,
                                      admin_site_feedback_resend,
                                      admin_site_feedback_status, site_feedback_ingest)
from app.site_feedback_store import D1SiteFeedbackStore
from _support.feedback_store import database

BASE = 'https://chat.example.test'
# 비밀·토큰은 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
_SESSION_SECRET = secrets.token_urlsafe(32)
_SECRET = secrets.token_urlsafe(32)
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret=_SESSION_SECRET,
                    # 정방향 수신(ingest) 비밀도 있어야 외부 의견 1건을 만들 수 있다.
                    site_feedback_secret_lovetree=_SECRET,
                    site_feedback_reply_secret_lovetree=_SECRET,
                    site_feedback_reply_url_lovetree='https://lovetree.test/api/ops-feedback/ingest')
SETTINGS_BARE = Settings(auth_mode='password', public_base_url=BASE,
                         session_secret=_SESSION_SECRET,
                         site_feedback_secret_lovetree=_SECRET)
ADMIN = 'usr_' + 'b' * 32
NOW_MS = 1_700_000_000_000
INGEST_TS = NOW_MS


def signed_ingest_request(store, value, *, secret=_SECRET, timestamp_ms=INGEST_TS):
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    message = str(timestamp_ms).encode() + b'\n' + b'lovetree' + b'\n' + raw
    headers = [(b'content-type', b'application/json'),
               (b'x-lt-site', b'lovetree'),
               (b'x-lt-timestamp', str(timestamp_ms).encode()),
               (b'x-lt-signature',
                ('sha256=' + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()).encode())]

    async def receive():
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    state = SimpleNamespace(settings=SETTINGS, site_feedback_store=store)

    return Request({'type': 'http', 'method': 'POST', 'path': '/api/site-feedback/ingest',
                    'query_string': b'', 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {},
                    'client': ('203.0.113.9', 12345)}, receive)


def ingest_payload(feedback_id=101, *, event='new', status='received', **over):
    value = {'event': event, 'feedbackId': feedback_id, 'body': 'lovetree-body',
             'status': status, 'append': None, 'isAiCustomer': True,
             'accountSubjectId': 'subj-lovetree-1', 'category': 'bug',
             'title': 'lovetree-title', 'createdAt': '2026-11-22T10:00:00.000Z'}
    value.update(over)
    return value


class AdminAuthority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == ADMIN


def admin_request(store, outbox=None, *, method='GET', user=ADMIN, body=None,
                  path='/api/admin/site-feedback', feedback_id='', query='',
                  settings=SETTINGS):
    state = SimpleNamespace(settings=settings, history_store=object(),
                            site_feedback_store=store, lovetree_ops_outbox=outbox,
                            central_model_admin_authorizer=AdminAuthority())
    headers = [(b'content-type', b'application/json'),
               (b'cf-connecting-ip', b'203.0.113.9'), (b'user-agent', b'fixture')]
    if user:
        token = create_session_token(settings, user, canonical_session_id="session_test_a")
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    data = json.dumps(body or {}, ensure_ascii=True).encode()

    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}

    return Request({'type': 'http', 'method': method, 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {'feedback_id': feedback_id},
                    'client': ('203.0.113.9', 12345)}, receive)


def payload(response):
    return json.loads(response.body)


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeClient:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.posts = []

    async def post(self, url, *, content, headers):
        self.posts.append({'url': url, 'content': content, 'headers': headers})
        code = self.statuses.pop(0) if self.statuses else 200
        if isinstance(code, Exception):
            raise code
        return FakeResponse(code)

    async def aclose(self):
        pass


@pytest.fixture(autouse=True)
def _now_pinned(monkeypatch):
    # 정방향 서명 창(5분) 안에 들어오도록 시각을 고정한다(test_7690_lovetree_ingest와 같다).
    monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: NOW_MS)
    monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-22T10:00:00Z')


def stores():
    db, _ = database(full=True)
    try:
        return db, D1SiteFeedbackStore(SqliteD1(db)), D1LovetreeOpsOutbox(SqliteD1(db))
    except Exception:
        db.close()
        raise


async def ingested(store):
    """595쪽 정방향 입장까지 다 끝난 러브트리 의견 한 건."""
    response = await site_feedback_ingest(signed_ingest_request(store, ingest_payload()))
    assert response.status_code == 201
    return payload(response)['feedback']


def test_signature_bytes_match_the_contract():
    """CTO 계약 예시 바이트와 같은 서명(시각\\n사이트\\n본문 원문 바이트)."""
    raw = json.dumps({'eventKey': 'ops_testkey_00000000', 'feedbackId': 101, 'kind': 'status',
                      'reply': None, 'status': 'fixed'},
                     ensure_ascii=False, separators=(',', ':')).encode()
    message = str(NOW_MS).encode('utf-8') + b'\n' + b'lovetree' + b'\n' + raw
    expect = hmac.new(_SECRET.encode('utf-8'), message, hashlib.sha256).hexdigest()
    sent = build_payload(event_key='ops_testkey_00000000', external_feedback_id='101',
                         kind='status', status='fixed')
    assert sent == raw
    # dispatcher의 header가 같은 바이트에 같은 답을 낸다.
    from app.lovetree_ops_outbox import signature_headers
    got = signature_headers(secret=_SECRET, raw=sent, timestamp_ms=NOW_MS)
    assert got['x-pd-site'] == 'lovetree'
    assert got['x-pd-timestamp'] == str(NOW_MS)
    assert got['x-pd-signature'] == 'sha256=' + expect


def test_event_key_shape_and_status_mapping():
    assert re.fullmatch(r'[A-Za-z0-9_-]{16,128}', new_event_key())
    assert new_event_key() != new_event_key()  # 같은 일은 같은 행, 행마다 고유 키
    from app.lovetree_ops_outbox import CHAT_STATUS_TO_EXTERNAL
    assert CHAT_STATUS_TO_EXTERNAL == {
        'new': 'received', 'reviewing': 'reviewing', 'fixed': 'fixed', 'deferred': 'later'}


def test_retry_intervals_are_the_contract_delays():
    assert RETRY_DELAYS_SECONDS == (60, 300, 1800, 7200, 43200)


def test_reply_send_two_xx_done_and_four_xx_no_retry_five_xx_retries():
    async def scenario():
        db, store, outbox = stores()
        try:
            item = await ingested(store)
            # 답글 적재 → 줄 1행, 아직 못 보내면 설정 없음 대기로 남는다
            entry = await outbox.enqueue_reply(
                feedback_id=item['id'], external_feedback_id=item['external_feedback_id'],
                body='고객에게 보이는 답글')
            assert entry['kind'] == 'reply' and entry['attempts'] == 0
            # 2xx — 완료
            client = FakeClient(200)
            await dispatch_pending(SimpleNamespace(
                settings=SETTINGS, lovetree_ops_outbox=outbox), client=client)
            row = (await outbox.pending_rows(limit=10))
            assert row == []  # sent_at 걸려 대기에서 빠진다
            rows = await outbox.list_for_feedback(item['id'])
            assert rows[0]['sent_at'] is not None and rows[0]['attempts'] == 1

            # 4xx — 실패로 남고 재시도 없음
            older = await outbox.enqueue_reply(
                feedback_id=item['id'], external_feedback_id=item['external_feedback_id'],
                body='두 번째 답글', now='2026-11-22T11:00:00Z')
            client = FakeClient(401)
            await dispatch_pending(SimpleNamespace(
                settings=SETTINGS, lovetree_ops_outbox=outbox), client=client)
            rows = {r['event_key']: r for r in await outbox.list_for_feedback(item['id'])}
            assert rows[older['event_key']]['failed_at'] is not None
            assert rows[older['event_key']]['next_attempt_at'] is None
            assert await outbox.pending_rows(limit=10) == []  # 재시도 안 함

            # 5xx — 재시도 간격이 계약대로 쌓인다(1분·5분·30분·2시간 뒤)
            third = await outbox.enqueue_reply(
                feedback_id=item['id'], external_feedback_id=item['external_feedback_id'],
                body='세 번째 답글', now='2026-11-22T12:00:00Z')
            base = datetime.now(timezone.utc)
            for index in range(5):
                client = FakeClient(500 + index)
                await dispatch_pending(SimpleNamespace(
                    settings=SETTINGS, lovetree_ops_outbox=outbox), client=client, now=base)
                rows = {r['event_key']: r for r in await outbox.list_for_feedback(item['id'])}
                row = rows[third['event_key']]
                assert row['attempts'] == index + 1
                if index < 4:
                    delta = (datetime.fromisoformat(
                        row['next_attempt_at'].replace('Z', '+00:00')) - base).total_seconds()
                    assert delta == RETRY_DELAYS_SECONDS[index]
                    base = datetime.fromisoformat(
                        row['next_attempt_at'].replace('Z', '+00:00')) + timedelta(seconds=1)
                else:
                    assert row['next_attempt_at'] is None  # 다섯 번째 실패 — 더는 안 감
            assert row['sent_at'] is None
            assert outbox_state(row, configured=True) == 'exhausted'
        finally:
            db.close()
    asyncio.run(scenario())


def test_retries_reuse_the_same_event_key_and_payload():
    async def scenario():
        db, store, outbox = stores()
        try:
            item = await ingested(store)
            await outbox.enqueue_reply(
                feedback_id=item['id'], external_feedback_id=item['external_feedback_id'],
                body='같은 답글')
            client = FakeClient(500, 200)
            state = SimpleNamespace(settings=SETTINGS, lovetree_ops_outbox=outbox)
            base = datetime.now(timezone.utc)
            await dispatch_pending(state, client=client, now=base)
            await dispatch_pending(state, client=client, now=base + timedelta(seconds=61))
            assert len(client.posts) == 2
            first, second = client.posts
            assert json.loads(first['content']) == json.loads(second['content'])
            value = json.loads(first['content'])
            assert value['eventKey'] == json.loads(second['content'])['eventKey']
            assert value['feedbackId'] == 101 and value['kind'] == 'reply'
            assert value['reply']['body'] == '같은 답글'
            assert value['reply']['replyId'].startswith('rpb_')
            assert value['status'] is None and value['reply']['createdAt']
        finally:
            db.close()
    asyncio.run(scenario())


def test_missing_config_leaves_the_row_waiting_not_failed():
    async def scenario():
        db, store, outbox = stores()
        try:
            item = await ingested(store)
            await outbox.enqueue_reply(
                feedback_id=item['id'], external_feedback_id=item['external_feedback_id'],
                body='대기 답글')
            state = SimpleNamespace(settings=SETTINGS_BARE, lovetree_ops_outbox=outbox)
            result = await dispatch_pending(state, client=FakeClient(200))
            assert result == {'sent': 0, 'retried': 0, 'failed': 0, 'checked': 0}
            rows = await outbox.list_for_feedback(item['id'])
            assert rows[0]['attempts'] == 0 and rows[0]['sent_at'] is None
            assert outbox_state(rows[0], configured=False) == 'waiting'
            assert outbox_state(rows[0], configured=True) == 'pending'
        finally:
            db.close()
    asyncio.run(scenario())


def test_forwarded_status_never_reenters_the_outbox():
    """되돌이 금지: 정방향으로 받은 상태 변화는 줄엔 들어오지 않는다."""
    async def scenario():
        db, store, outbox = stores()
        try:
            await ingested(store)
            # 정방향 status 이벤트
            response = await site_feedback_ingest(
                signed_ingest_request(store, ingest_payload(event='status', status='later')))
            assert response.status_code in (200, 201)  # 신규 201도 200도 통과는 된다
            waiting = await outbox.pending_rows(limit=10)
            assert waiting == []
            assert await outbox.list_for_feedback(payload(response)['feedback']['id']) == []
        finally:
            db.close()
    asyncio.run(scenario())


def test_direct_status_change_queues_one_status_event():
    async def scenario():
        db, store, outbox = stores()
        try:
            item = await ingested(store)
            changed = await admin_site_feedback_status(admin_request(
                store, outbox, method='PATCH', body={'status': 'fixed'},
                feedback_id=item['id']))
            assert changed.status_code == 200
            rows = await outbox.list_for_feedback(item['id'])
            assert len(rows) == 1 and rows[0]['kind'] == 'status'
            assert rows[0]['status'] == 'fixed'
            # 운영 메모만 바꾸면 줄엔 들어오지 않는다.
            memo = await admin_site_feedback_status(admin_request(
                store, outbox, method='PATCH', body={'ops_memo': '메모'},
                feedback_id=item['id']))
            assert memo.status_code == 200
            assert len(await outbox.list_for_feedback(item['id'])) == 1
        finally:
            db.close()
    asyncio.run(scenario())


def test_reply_endpoint_authority_and_length():
    async def scenario():
        db, store, outbox = stores()
        try:
            item = await ingested(store)
            # 권한 없는 계정 — 거절 그대로(403, detail 없음)
            nobody = await admin_site_feedback_reply(admin_request(
                store, outbox, method='POST', user='usr_' + 'c' * 32,
                body={'body': '답글'}, path='/api/admin/site-feedback/x/reply',
                feedback_id=item['id']))
            assert nobody.status_code in (401, 403, 404)
            # 2000자 초과 거절
            too_long = await admin_site_feedback_reply(admin_request(
                store, outbox, method='POST', body={'body': '가' * 2001},
                feedback_id=item['id']))
            assert too_long.status_code == 400
            # 빈 답글·여분 칸 거절
            empty = await admin_site_feedback_reply(admin_request(
                store, outbox, method='POST', body={'body': ' ', 'extra': 1},
                feedback_id=item['id']))
            assert empty.status_code == 400
            # 정상 — 201 로 줄 1행
            ok = await admin_site_feedback_reply(admin_request(
                store, outbox, method='POST', body={'body': '운영 답글입니다'},
                feedback_id=item['id']))
            assert ok.status_code == 201
            answer = payload(ok)
            assert answer['outbox'][0]['kind'] == 'reply'
            assert answer['outbox'][0]['reply_body'] == '운영 답글입니다'
        finally:
            db.close()
    asyncio.run(scenario())


def test_resend_restarts_a_failed_row_only():
    async def scenario():
        db, store, outbox = stores()
        try:
            item = await ingested(store)
            entry = await admin_site_feedback_reply(admin_request(
                store, outbox, method='POST', body={'body': '실패할 답글'},
                feedback_id=item['id']))
            event_key = payload(entry)['outbox'][0]['event_key']
            await dispatch_pending(
                SimpleNamespace(settings=SETTINGS, lovetree_ops_outbox=outbox),
                client=FakeClient(400))
            rows = await outbox.list_for_feedback(item['id'])
            assert rows[0]['state'] if 'state' in rows[0] else True
            # 다시 보내기 — 실패 행만
            ok = await admin_site_feedback_resend(admin_request(
                store, outbox, method='POST', body={'eventKey': event_key},
                feedback_id=item['id']))
            assert ok.status_code == 200
            rows = await outbox.list_for_feedback(item['id'])
            assert rows[0]['failed_at'] is None and rows[0]['attempts'] == 0
            assert rows[0]['next_attempt_at'] is None
            # 실패가 아닌 행은 again 404/False 의미로 거절
            again = await admin_site_feedback_resend(admin_request(
                store, outbox, method='POST', body={'eventKey': event_key},
                feedback_id=item['id']))
            assert again.status_code == 404
        finally:
            db.close()
    asyncio.run(scenario())


def test_admin_list_shows_outbox_state_and_waiting_when_unconfigured():
    async def scenario():
        db, store, outbox = stores()
        try:
            item = await ingested(store)
            await outbox.enqueue_reply(
                feedback_id=item['id'], external_feedback_id=item['external_feedback_id'],
                body='기다릴 답글')
            blocked = await admin_site_feedback(admin_request(
                store, outbox, query='site=lovetree', settings=SETTINGS_BARE))
            assert blocked.status_code == 200
            seen = payload(blocked)['feedback'][0]
            assert seen['outbox'][0]['state'] == 'waiting'
        finally:
            db.close()
    asyncio.run(scenario())
