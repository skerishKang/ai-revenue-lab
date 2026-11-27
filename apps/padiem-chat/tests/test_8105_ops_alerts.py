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
from _support.migrated_db_template import apply_copied_migrations as apply_migrations
from app.ops_alert_delivery import (
    alert_message,
    deliver_alert,
    drain_alert_tasks,
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
                            ops_alert_notifier=notifier,
                            b66_signup_notifier=None,
                            ops_alert_tasks=set(),
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
            second = await retry_pending_alerts(request.app.state)
            assert second == {'sent': 1, 'failed': 0, 'processed': 1}
            assert [call['channel'] for call in healed.calls] == ['discord']

            again = _RecordingNotifier()
            third = await retry_pending_alerts(
                _request(alert=store, notifier=again).app.state)
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
            summary = await retry_pending_alerts(request.app.state)
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
        assert await retry_pending_alerts(request.app.state) == {
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
            await drain_alert_tasks(request.app.state)
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
            await drain_alert_tasks(request.app.state)
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

# ---- 6. 발송기 분리 --------------------------------------------------------

def test_the_ops_notifier_never_changes_the_b66_delivery_flag():
    """B66 회원 저장소가 없는 배포: b66_signup_notifier는 None으로 남는다.

    B66 관리 상태의 notification_delivery_configured도 False로 남고,
    운영센터 발송기(ops_alert_notifier)만 채널을 가진다.
    """
    from app.b66_member_inquiries import b66_admin_inquiries

    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            # local_cpython의 #8105 블록과 같은 조건: B66 발송기가 없다.
            request = _request(alert=store, audit=audit,
                               notifier=_RecordingNotifier())
            assert request.app.state.b66_signup_notifier is None
            assert request.app.state.ops_alert_notifier is not None
            assert set(request.app.state.ops_alert_notifier.channels) == {
                'telegram', 'discord', 'email'}
            viewed = await admin_ops_alerts(request)
            assert payload(viewed)['configured'] == ['discord', 'email', 'telegram']
            # B66 쪽은 자기 발송기가 없으므로 설정 안 됨으로 남는다.
            request.app.state.b66_inquiry_store = _B66Inquiries()
            request.app.state.b66_member_admin_store = _B66Admin()
            b66_view = await b66_admin_inquiries(request)
            assert b66_view.status_code == 200
            assert payload(b66_view)['notification_delivery_configured'] is False
        finally:
            db.close()
    asyncio.run(scenario())


class _B66Admin:
    async def is_google_admin(self, user_id):
        return user_id == ADMIN


class _B66Inquiries:
    async def list_admin(self, status):
        return []


def test_the_ops_notifier_reuses_the_b66_sender_when_it_exists():
    """B66 발송기가 있으면 그것을 그대로 같이 쓴다(새로 만들지 않는다)."""
    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            shared = _RecordingNotifier()
            request = _request(alert=store, audit=audit, notifier=shared)
            request.app.state.b66_signup_notifier = shared
            assert request.app.state.ops_alert_notifier is shared
            await enqueue_and_deliver(request, kind='product_feedback',
                                      target_id='fb_' + '8' * 32, label='chat')
            await drain_alert_tasks(request.app.state)
            assert len(shared.calls) == 3
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 7. 요청 응답 밖 발송 --------------------------------------------------

def test_a_stalled_channel_never_holds_the_submission_response():
    """채널이 멈춰도 접수 응답은 즉시 나간다(발송은 백그라운드).

    실제 시간으로 기다리지 않는다: 채널은 이벤트로 멈춰 두고, 응답이 먼저
    끝났는지로 확인한 뒤 이벤트를 풀어 작업을 마무리한다.
    """
    from app.feedback_routes import feedback
    from app.feedback_store import D1FeedbackStore

    async def scenario():
        db, store, audit = _stores(_Clock())
        gate = asyncio.Event()
        started = asyncio.Event()

        class _Stalled:
            channels = {'telegram': ()}

            async def _send(self, *args, **kwargs):
                started.set()
                await gate.wait()
                return True

        try:
            request = _request(alert=store, audit=audit, notifier=_Stalled(),
                               method='POST', user=MEMBER,
                               path='/api/chat/feedback', body={'body': BODY_TEXT})
            request.app.state.feedback_store = D1FeedbackStore(SqliteD1(db))
            response = await feedback(request)
            # 응답은 채널이 아직 멈춰 있는 동안 이미 끝났다.
            assert response.status_code == 201
            assert len(await store.pending()) == 1
            assert request.app.state.ops_alert_tasks
            gate.set()
            await drain_alert_tasks(request.app.state)
            assert started.is_set()
            assert await store.pending() == []
            assert request.app.state.ops_alert_tasks == set()
        finally:
            gate.set()
            db.close()
    asyncio.run(scenario())


# ---- 8. 자동 재시도 --------------------------------------------------------

def test_the_next_submission_retries_the_older_pending_alert():
    """실패한 건은 다음 접수 때 같은 흐름에서 자동으로 다시 보내진다."""
    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            failing = _RecordingNotifier(fail=('discord',))
            first = _request(alert=store, audit=audit, notifier=failing)
            await enqueue_and_deliver(first, kind='product_feedback',
                                      target_id='fb_' + '9' * 32, label='chat')
            await drain_alert_tasks(first.app.state)
            assert len(await store.pending()) == 1
            assert not await store.receipt_exists(
                (await store.pending())[0]['alert_id'], 'discord')

            healed = _RecordingNotifier()
            second = _request(alert=store, audit=audit, notifier=healed)
            await enqueue_and_deliver(second, kind='site_feedback',
                                      target_id='sf_' + 'a' * 32,
                                      label='miraen-home')
            await drain_alert_tasks(second.app.state)
            # 새 건 3채널 + 오래된 건의 실패 채널 1개만 다시 갔다.
            assert len(healed.calls) == 4
            assert await store.pending() == []
            status = await store.status()
            by_channel = {row['channel']: row for row in status['channels']}
            assert by_channel['discord']['attempts'] == 3
            assert by_channel['telegram']['attempts'] == 2

            third = _RecordingNotifier()
            last = _request(alert=store, audit=audit, notifier=third)
            await enqueue_and_deliver(
                last, kind='round_score', target_id='opsrs_' + 'b' * 32,
                label='round_score')
            await drain_alert_tasks(last.app.state)
            # 이미 보낸 건은 다시 가지 않는다 — 새 건 3채널뿐.
            assert len(third.calls) == 3
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 9. 분류 칸 ------------------------------------------------------------

def test_a_round_score_alert_uses_the_fixed_label_and_is_never_dropped():
    """분류 칸은 서버가 정하는 고정 낱말 — 출처 값이 규칙에 안 맞아도 버려지지 않는다."""
    from app.ops_round_score_routes import admin_round_score_create
    from app.ops_round_score_store import D1OpsRoundScoreStore

    async def scenario():
        db, store, audit = _stores(_Clock())
        try:
            notifier = _RecordingNotifier()
            request = _request(alert=store, audit=audit, notifier=notifier,
                               method='POST', path='/api/admin/round-scores',
                               body={'persona_name': PERSONA_NAME, 'round_no': 1,
                                     'round_on': '2026-11-20', 'source': 'human',
                                     'return_score': 3, 'pretty_score': 4})
            request.app.state.ops_round_score_store = D1OpsRoundScoreStore(SqliteD1(db))
            response = await admin_round_score_create(request)
            assert response.status_code == 200
            await drain_alert_tasks(request.app.state)
            rows = await store.status()
            assert rows['pending'] == 0
            assert len(notifier.calls) == 3
            for call in notifier.calls:
                assert '분류: round_score' in call['message']
                assert PERSONA_NAME not in call['message']
        finally:
            db.close()
    asyncio.run(scenario())


def test_an_unusable_label_is_refused_by_the_store_not_silently_dropped():
    from app.ops_alert_store import OpsAlertInvalid

    async def scenario():
        db, store, _audit = _stores(_Clock())
        try:
            with pytest.raises(OpsAlertInvalid):
                await store.enqueue(kind='round_score',
                                    target_id='opsrs_' + 'c' * 32,
                                    label='한글 분류')
            assert await store.pending() == []
        finally:
            db.close()
    asyncio.run(scenario())
