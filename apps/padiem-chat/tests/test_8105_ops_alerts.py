"""#8105 — 새 의견·회차 점수 알림 계약.

다섯 가지:

  1. 문구 — 채널 3개를 가짜로 바꿔 끼워, 실제로 나가는 값에 의견 본문·이메일·
     회원 id·이름이 없음을 계산 값으로 확인한다(종류·분류·번호·링크만).
  2. 중복 — 실패 → 재시도 → 채널마다 정확히 1번만 성공한다.
  3. 저장 — 알림이 실패해도 의견·점수 저장은 성공하고 대기함에 남는다.
  4. 권한 — 상태·다시 보내기는 관리자만(회원 403·게스트 401), 감사 1줄씩.
  5. 시계 — now를 주입한다(실제 시계로 기다리지 않는다).

다른 시험 파일을 import하지 않는다 — 하니스를 이 파일 안에 둔다.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE
from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.local_cpython import apply_migrations
from app.ops_alert_delivery import (
    alert_message,
    deliver_alert,
    enqueue_and_deliver,
    retry_pending_alerts,
)
from app.ops_alert_routes import admin_ops_alerts, admin_ops_alerts_dispatch
from app.ops_alert_store import D1OpsAlertStore
from app.ops_audit_store import OpsAuditStore

CHAT_DIR = Path(__file__).resolve().parents[1]
BASE = 'https://chat.example.test'
MEMBER = 'usr_' + 'a' * 32
ADMIN = 'usr_' + 'b' * 32
BODY_TEXT = '의견 본문에 들어간 비밀스러운 고객 문장'
EMAIL_TEXT = 'customer@example.test'
PERSONA_NAME = 'AI 정호'
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret=secrets.token_urlsafe(32))


class _Clock:
    """주입 시계 — 부를 때마다 정해진 보폭만큼 나아간다."""

    def __init__(self, *, step_seconds=0):
        self.moment = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
        self.step = timedelta(seconds=step_seconds)

    def __call__(self):
        value = self.moment
        self.moment = value + self.step
        return value


class _Authority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == ADMIN


class _RecordingNotifier:
    """채널 3개를 가짜로 바꿔 끼운 대역 — 나가는 값을 그대로 모은다."""

    def __init__(self, *, fail=()):
        self.channels = {name: () for name in ('telegram', 'discord', 'email')}
        self.calls: list[dict] = []
        self.fail = set(fail)

    async def _send(self, channel, *, message=None, subject=None):
        self.calls.append({'channel': channel, 'message': message,
                           'subject': subject})
        return channel not in self.fail


def _database():
    db = sqlite3.connect(':memory:', isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=OFF')
    apply_migrations(db)
    db.execute('PRAGMA foreign_keys=OFF')
    for uid in (MEMBER, ADMIN):
        db.execute(
            "INSERT INTO users (id,auth_provider,provider_subject,email,"
            "display_name,picture_url,created_at,updated_at) "
            "VALUES (?,'google',?,?,'고객이름','','','')",
            (uid, uid, EMAIL_TEXT if uid == MEMBER else 'admin@example.test'))
    return db


def _stores(clock=None):
    db = _database()
    adapter = SqliteD1(db)
    return db, D1OpsAlertStore(adapter, now=clock), OpsAuditStore(adapter)


def _request(*, alert=None, audit=None, notifier=None, method='GET',
             user=ADMIN, path='/api/admin/ops-alerts', query='', body=None):
    from sid_session_helper import sid_session_token

    state = SimpleNamespace(settings=SETTINGS, history_store=object(),
                            ops_alert_store=alert, ops_audit_store=audit,
                            b66_signup_notifier=notifier,
                            central_model_admin_authorizer=_Authority())
    headers = [(b'content-type', b'application/json'), (b'origin', BASE.encode())]
    if user:
        token = sid_session_token(SETTINGS, user)
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    data = json.dumps(body if body is not None else {}, ensure_ascii=False).encode()

    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}

    return Request({'type': 'http', 'method': method, 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state),
                    'path_params': {}}, receive)


def payload(response):
    return json.loads(response.body)


def _entry(alert_id='opsalr_' + 'c' * 32, kind='site_feedback',
           target_id='sf_' + 'd' * 32, label='miraen-home'):
    return {'alert_id': alert_id, 'kind': kind, 'target_id': target_id,
            'label': label}


# ---- 1. 문구 ---------------------------------------------------------------

def test_the_message_carries_only_kind_label_number_and_link():
    text = alert_message(_entry(), base_url=BASE)
    assert '사이트 의견' in text
    assert 'miraen-home' in text
    assert 'sf_' + 'd' * 32 in text
    assert BASE + '/admin#ops-inbox' in text
    for forbidden in (BODY_TEXT, EMAIL_TEXT, MEMBER, '고객이름'):
        assert forbidden not in text


@pytest.mark.parametrize('kind,label', [
    ('product_feedback', 'chat'), ('site_feedback', 'miraen-home'),
    ('round_score', 'ai'),
])
def test_every_channel_receives_the_same_safe_values(kind, label):
    async def scenario():
        db, store, _audit = _stores(_Clock())
        try:
            entry = await store.enqueue(kind=kind, target_id='fb_' + 'e' * 32,
                                        label=label)
            notifier = _RecordingNotifier()
            result = await deliver_alert(store, notifier, entry, base_url=BASE)
            assert result == {'sent': 3, 'failed': 0}
            assert len(notifier.calls) == 3
            assert {call['channel'] for call in notifier.calls} == {
                'telegram', 'discord', 'email'}
            for call in notifier.calls:
                text = call['message']
                assert label in text and entry['target_id'] in text
                assert BASE + '/admin#ops-inbox' in text
                for forbidden in (BODY_TEXT, EMAIL_TEXT, MEMBER, PERSONA_NAME,
                                  '고객이름'):
                    assert forbidden not in text
                assert forbidden not in (call['subject'] or '')
        finally:
            db.close()
    asyncio.run(scenario())


def test_a_round_score_alert_never_carries_the_customer_name():
    async def scenario():
        db, store, _audit = _stores(_Clock())
        try:
            entry = await store.enqueue(kind='round_score',
                                        target_id='opsrs_' + 'f' * 32, label='ai')
            notifier = _RecordingNotifier()
            await deliver_alert(store, notifier, entry, base_url=BASE)
            for call in notifier.calls:
                assert PERSONA_NAME not in call['message']
                assert 'ai' in call['message']
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 2. 중복 없음 ----------------------------------------------------------

def test_a_failed_channel_is_retried_once_and_never_sent_twice():
    async def scenario():
        db, store, _audit = _stores(_Clock())
        try:
            entry = await store.enqueue(kind='product_feedback',
                                        target_id='fb_' + '1' * 32, label='chat')
            failing = _RecordingNotifier(fail=('discord',))
            first = await deliver_alert(store, failing, entry, base_url=BASE)
            assert first == {'sent': 2, 'failed': 1}
            assert await store.receipt_exists(entry['alert_id'], 'telegram')
            assert not await store.receipt_exists(entry['alert_id'], 'discord')
            assert (await store.pending()) != []

            healed = _RecordingNotifier()
            request = _request(alert=store, notifier=healed)
            second = await retry_pending_alerts(request)
            assert second == {'sent': 1, 'failed': 0, 'processed': 1}
            assert [call['channel'] for call in healed.calls] == ['discord']

            again = _RecordingNotifier()
            third = await retry_pending_alerts(_request(alert=store, notifier=again))
            assert third == {'sent': 0, 'failed': 0, 'processed': 0}
            assert again.calls == []
            assert await store.pending() == []
            status = await store.status()
            assert status['pending'] == 0
            by_channel = {row['channel']: row for row in status['channels']}
            assert by_channel['discord']['attempts'] == 2
            assert by_channel['telegram']['attempts'] == 1
            assert by_channel['discord']['last_failure'] is not None
            assert by_channel['discord']['last_success'] is not None
        finally:
            db.close()
    asyncio.run(scenario())


def test_the_same_target_is_queued_only_once():
    async def scenario():
        db, store, _audit = _stores(_Clock())
        try:
            first = await store.enqueue(kind='site_feedback',
                                        target_id='sf_' + '2' * 32,
                                        label='miraen-home')
            second = await store.enqueue(kind='site_feedback',
                                         target_id='sf_' + '2' * 32,
                                         label='miraen-home')
            assert first is not None and second is None
            assert len(await store.pending()) == 1
        finally:
            db.close()
    asyncio.run(scenario())


def test_without_channel_values_the_outbox_only_accumulates():
    async def scenario():
        db, store, _audit = _stores(_Clock())
        try:
            request = _request(alert=store, notifier=None)
            await enqueue_and_deliver(request, kind='product_feedback',
                                      target_id='fb_' + '3' * 32, label='chat')
            assert len(await store.pending()) == 1
            assert (await store.status())['pending'] == 1
            summary = await retry_pending_alerts(request)
            assert summary == {'sent': 0, 'failed': 0, 'processed': 0}
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 3. 저장과 무관 --------------------------------------------------------

def test_a_notifier_that_raises_never_breaks_the_submission():
    class _Exploding:
        channels = {'telegram': ()}

        async def _send(self, *args, **kwargs):
            raise RuntimeError('channel down')

    async def scenario():
        db, store, _audit = _stores(_Clock())
        try:
            request = _request(alert=store, notifier=_Exploding())
            await enqueue_and_deliver(request, kind='site_feedback',
                                      target_id='sf_' + '4' * 32,
                                      label='miraen-home')
            # 다리는 예외를 밖으로 내지 않고, 대기함에는 남는다.
            assert len(await store.pending()) == 1
        finally:
            db.close()
    asyncio.run(scenario())


def test_a_missing_store_is_a_silent_no_op():
    async def scenario():
        request = _request(alert=None, notifier=_RecordingNotifier())
        await enqueue_and_deliver(request, kind='round_score',
                                  target_id='opsrs_' + '5' * 32, label='ai')
        assert await retry_pending_alerts(request) == {
            'sent': 0, 'failed': 0, 'processed': 0}
    asyncio.run(scenario())


def test_the_feedback_submission_succeeds_while_the_alert_fails():
    """의견 접수 라우트가 알림 실패와 무관하게 201을 낸다."""
    from app.feedback_routes import feedback
    from app.feedback_store import D1FeedbackStore

    class _Exploding:
        channels = {'telegram': ()}

        async def _send(self, *args, **kwargs):
            raise RuntimeError('channel down')

    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            adapter = SqliteD1(db)
            request = _request(alert=store, audit=audit, notifier=_Exploding(),
                               method='POST', user=MEMBER,
                               path='/api/chat/feedback', body={'body': BODY_TEXT})
            request.app.state.feedback_store = D1FeedbackStore(adapter)
            response = await feedback(request)
            assert response.status_code == 201, payload(response)
            assert payload(response)['ok'] is True
            rows = await store.pending()
            assert len(rows) == 1
            assert rows[0]['kind'] == 'product_feedback'
            assert BODY_TEXT not in json.dumps(rows, ensure_ascii=False)
        finally:
            db.close()
    asyncio.run(scenario())


def test_the_round_score_submission_succeeds_while_the_alert_fails():
    from app.ops_round_score_routes import admin_round_score_create
    from app.ops_round_score_store import D1OpsRoundScoreStore

    class _Exploding:
        channels = {'email': ()}

        async def _send(self, *args, **kwargs):
            raise RuntimeError('channel down')

    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            adapter = SqliteD1(db)
            request = _request(alert=store, audit=audit, notifier=_Exploding(),
                               method='POST', path='/api/admin/round-scores',
                               body={'persona_name': PERSONA_NAME, 'round_no': 1,
                                     'round_on': '2026-11-20', 'source': 'ai',
                                     'return_score': 4, 'pretty_score': 5})
            request.app.state.ops_round_score_store = D1OpsRoundScoreStore(adapter)
            response = await admin_round_score_create(request)
            assert response.status_code == 200, payload(response)
            rows = await store.pending()
            assert len(rows) == 1 and rows[0]['kind'] == 'round_score'
            assert PERSONA_NAME not in json.dumps(rows, ensure_ascii=False)
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 4. 권한·감사 ----------------------------------------------------------

def test_the_alert_endpoints_answer_only_to_the_administrator():
    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            for handler, method, path in (
                (admin_ops_alerts, 'GET', '/api/admin/ops-alerts'),
                (admin_ops_alerts_dispatch, 'POST', '/api/admin/ops-alerts/dispatch'),
            ):
                member = await handler(_request(alert=store, audit=audit,
                                                method=method, user=MEMBER,
                                                path=path))
                assert member.status_code == 403
                assert payload(member)['error']['code'] == 'global_model_admin_forbidden'
                guest = await handler(_request(alert=store, audit=audit,
                                               method=method, user=None, path=path))
                assert guest.status_code == 401
                assert payload(guest)['error']['code'] == 'authentication_required'
            assert await audit.list_recent(limit=20) == []
        finally:
            db.close()
    asyncio.run(scenario())


def test_viewing_and_dispatching_each_leave_one_audit_row():
    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            await store.enqueue(kind='product_feedback',
                                target_id='fb_' + '6' * 32, label='chat')
            notifier = _RecordingNotifier()
            viewed = await admin_ops_alerts(_request(alert=store, audit=audit,
                                                     notifier=notifier))
            assert viewed.status_code == 200
            body = payload(viewed)
            assert body['configured'] == ['discord', 'email', 'telegram']
            assert body['pending'] == 1
            sent = await admin_ops_alerts_dispatch(
                _request(alert=store, audit=audit, notifier=notifier,
                         method='POST', path='/api/admin/ops-alerts/dispatch'))
            assert sent.status_code == 200
            assert payload(sent)['result'] == {'sent': 3, 'failed': 0, 'processed': 1}
            rows = await audit.list_recent(limit=20)
            actions = [row['action'] for row in rows]
            assert actions.count('ops_alert_view') == 1
            assert actions.count('ops_alert_dispatch') == 1
            assert all(row['actor_user_id'] == ADMIN for row in rows)
            blob = json.dumps(rows, ensure_ascii=False)
            assert EMAIL_TEXT not in blob and BODY_TEXT not in blob
        finally:
            db.close()
    asyncio.run(scenario())


def test_dispatch_without_channels_is_refused_and_the_view_still_answers():
    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            refused = await admin_ops_alerts_dispatch(
                _request(alert=store, audit=audit, notifier=None, method='POST',
                         path='/api/admin/ops-alerts/dispatch'))
            assert refused.status_code == 503
            assert payload(refused)['error']['code'] == 'ops_alert_not_configured'
            viewed = await admin_ops_alerts(_request(alert=store, audit=audit,
                                                     notifier=None))
            assert viewed.status_code == 200
            assert payload(viewed)['configured'] == []
            assert len(payload(viewed)['channels']) == 3
        finally:
            db.close()
    asyncio.run(scenario())


def test_an_unknown_query_parameter_is_refused():
    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            answer = await admin_ops_alerts(_request(alert=store, audit=audit,
                                                     query='limit=5'))
            assert answer.status_code == 400
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 5. 시계 주입 ----------------------------------------------------------

def test_the_receipt_timestamps_come_from_the_injected_clock():
    async def scenario():
        clock = _Clock(step_seconds=60)
        db, store, _audit = _stores(clock)
        try:
            entry = await store.enqueue(kind='site_feedback',
                                        target_id='sf_' + '7' * 32,
                                        label='miraen-home')
            start = clock.moment
            await deliver_alert(store, _RecordingNotifier(), entry, base_url=BASE)
            status = await store.status()
            stamps = [row['last_success'] for row in status['channels']]
            assert all(value is not None for value in stamps)
            assert all(value.startswith('2026-11-20T09:') for value in stamps)
            # 실제 시계가 아니라 주입 시계가 나아간 만큼만 시간이 흘렀다.
            assert clock.moment > start
            assert clock.moment.year == 2026
        finally:
            db.close()
    asyncio.run(scenario())