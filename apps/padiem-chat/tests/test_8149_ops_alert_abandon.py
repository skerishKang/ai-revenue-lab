"""#8149 — 운영센터 알림 대기함: 채널 격리·시도 상한·만료·예외 로그.

시계를 주입하고 실제 저장소·발송 코드를 쓴다. 외부 서비스는 닿지 않는다.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.d1_sqlite import SqliteD1
from _support.migrated_db_template import apply_copied_migrations as apply_migrations
from app.ops_alert_delivery import (
    deliver_alert,
    drain_alert_tasks,
    enqueue_and_deliver,
    retry_pending_alerts,
)
from app.ops_alert_store import D1OpsAlertStore, MAX_ATTEMPTS

CHAT_DIR = Path(__file__).resolve().parents[1]
SETTINGS = Settings(auth_mode='password', public_base_url='https://chat.example.test',
                    session_secret=secrets.token_urlsafe(32))


class Clock:
    def __init__(self, step=0):
        self.moment = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
        self.step = timedelta(seconds=step)

    def __call__(self):
        value = self.moment
        self.moment += self.step
        return value

    def advance(self, **kwargs):
        self.moment += timedelta(**kwargs)


class Notifier:
    def __init__(self, *, fail=(), raise_on=()):
        self.channels = {name: () for name in ('telegram', 'discord', 'email')}
        self.fail = set(fail)
        self.raise_on = set(raise_on)
        self.calls: list[str] = []

    async def _send(self, channel, *, message=None, subject=None):
        self.calls.append(channel)
        if channel in self.raise_on:
            raise RuntimeError('a secret ' + 'token=DO_NOT_LOG value=DO_NOT_LOG')
        return channel not in self.fail


def harness(clock=None, *, fail=(), raise_on=()):
    db = sqlite3.connect(':memory:', isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=OFF')
    apply_migrations(db)
    db.execute('PRAGMA foreign_keys=OFF')
    store = D1OpsAlertStore(SqliteD1(db), now=clock)
    notifier = Notifier(fail=fail, raise_on=raise_on)
    state = SimpleNamespace(settings=SETTINGS, ops_alert_store=store,
                            ops_alert_notifier=notifier, ops_alert_tasks=set())
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    return db, store, notifier, state, request


def _entry(store, alert_id):
    return {'alert_id': alert_id, 'kind': 'product_feedback',
            'target_id': 't', 'label': 'feedback'}


def test_a_failing_channel_never_blocks_the_other_channels():
    clock = Clock()
    db, store, notifier, state, request = harness(clock, fail=('telegram',))

    async def scenario():
        for index in range(7):
            await enqueue_and_deliver(request, kind='product_feedback',
                                      target_id=f'item_{index}', label='feedback')
            await drain_alert_tasks(state)

    try:
        asyncio.run(scenario())
        sent = [channel for channel in notifier.calls if channel in ('discord', 'email')]
        assert sent.count('discord') == 7
        assert sent.count('email') == 7
        status = asyncio.run(store.status())
        assert status['pending'] == 0
        telegram = next(row for row in status['channels'] if row['channel'] == 'telegram')
        assert telegram['abandoned'] >= 1
    finally:
        db.close()


def test_attempt_cap_abandons_a_channel_and_stops_retrying_it():
    clock = Clock(step=1)
    db, store, notifier, state, _request = harness(clock, fail=('email',))
    try:
        alert_id = asyncio.run(store.enqueue(
            kind='product_feedback', target_id='one', label='feedback'))['alert_id']
        for _ in range(MAX_ATTEMPTS):
            result = asyncio.run(deliver_alert(
                store, notifier, _entry(store, alert_id), base_url='https://chat.example.test'))
            assert result['failed'] >= 1
        assert asyncio.run(store.channel_abandoned(alert_id, 'email'))
        before = len(notifier.calls)
        asyncio.run(retry_pending_alerts(state))
        after_email = [c for c in notifier.calls[before:] if c == 'email']
        assert after_email == []
        status = asyncio.run(store.status())
        abandoned = {row['channel']: row['abandoned'] for row in status['channels']}
        assert abandoned['email'] == 1
        assert status['pending'] == 0
    finally:
        db.close()


def test_expiry_abandons_before_the_attempt_cap():
    clock = Clock()
    db, store, notifier, _state, _request = harness(clock, fail=('telegram',))
    try:
        alert_id = asyncio.run(store.enqueue(
            kind='product_feedback', target_id='old', label='feedback'))['alert_id']
        asyncio.run(deliver_alert(store, notifier, _entry(store, alert_id),
                                  base_url='https://chat.example.test'))
        clock.advance(hours=25)
        asyncio.run(deliver_alert(store, notifier, _entry(store, alert_id),
                                  base_url='https://chat.example.test'))
        assert asyncio.run(store.channel_abandoned(alert_id, 'telegram'))
        status = asyncio.run(store.status())
        telegram = next(row for row in status['channels'] if row['channel'] == 'telegram')
        assert telegram['attempts'] < MAX_ATTEMPTS
        assert telegram['abandoned'] == 1
    finally:
        db.close()


def test_send_exception_is_logged_without_body_or_secrets(caplog):
    clock = Clock()
    db, store, notifier, _state, _request = harness(clock, raise_on=('discord',))
    try:
        alert_id = asyncio.run(store.enqueue(
            kind='product_feedback', target_id='boom', label='feedback'))['alert_id']
        with caplog.at_level(logging.WARNING):
            asyncio.run(deliver_alert(store, notifier, _entry(store, alert_id),
                                      base_url='https://chat.example.test'))
        lines = [record.getMessage() for record in caplog.records
                 if record.name == 'app.ops_alert_delivery']
        assert len(lines) == 1
        assert 'channel=discord' in lines[0] and 'error=RuntimeError' in lines[0]
        assert 'DO_NOT_LOG' not in lines[0]
        assert 'token=' not in lines[0]
        assert asyncio.run(store.channel_abandoned(alert_id, 'discord')) is False
    finally:
        db.close()
