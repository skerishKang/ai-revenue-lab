"""#8105 후속 — 접수 두 건이 동시에 들어와도 채널당 발송은 한 번이다.

백그라운드 작업 두 개가 같은 대기분을 함께 집으면, 영수증 확인과 발송 사이
틈 때문에 같은 채널로 두 번 갈 수 있다. 발송 흐름 전체가 락 안에서 도는지
실제 동시 상황으로 확인한다.

채널은 이벤트로 멈춰 두고, 두 접수를 연속으로 넣은 뒤 이벤트를 푼다.
실제 시간으로 기다리지 않고(now 주입), 다른 시험 파일을 import하지 않는다.
"""
from __future__ import annotations

import asyncio
import secrets
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.auth import SESSION_COOKIE
from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.local_cpython import apply_migrations
from app.ops_alert_delivery import drain_alert_tasks, enqueue_and_deliver
from app.ops_alert_store import D1OpsAlertStore
from app.ops_audit_store import OpsAuditStore

CHAT_DIR = Path(__file__).resolve().parents[1]
BASE = 'https://chat.example.test'
ADMIN = 'usr_' + 'b' * 32
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


def _stores(clock):
    db = sqlite3.connect(':memory:', isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=OFF')
    apply_migrations(db)
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute(
        "INSERT INTO users (id,auth_provider,provider_subject,email,"
        "display_name,picture_url,created_at,updated_at) "
        "VALUES (?,'google',?,'admin@example.test','','','','')", (ADMIN, ADMIN))
    adapter = SqliteD1(db)
    return db, D1OpsAlertStore(adapter, now=clock), OpsAuditStore(adapter)


def _state(store, audit, notifier):
    """두 접수가 같은 앱 상태를 공유한다(같은 락·같은 작업 집합)."""
    return SimpleNamespace(settings=SETTINGS, history_store=object(),
                           ops_alert_store=store, ops_audit_store=audit,
                           ops_alert_notifier=notifier,
                           b66_signup_notifier=None, ops_alert_tasks=set())


def _request(state):
    return SimpleNamespace(app=SimpleNamespace(state=state))


class _GatedNotifier:
    """첫 발송에서 멈춰 서는 채널 대역 — 나가는 횟수를 그대로 센다."""

    def __init__(self, gate, entered):
        self.channels = {name: () for name in ('telegram', 'discord', 'email')}
        self.calls: list[str] = []
        self._gate = gate
        self._entered = entered

    async def _send(self, channel, *, message=None, subject=None):
        self.calls.append(channel)
        self._entered.set()
        await self._gate.wait()
        return True


def test_two_submissions_at_once_send_each_channel_exactly_once():
    async def scenario():
        db, store, audit = _stores(_Clock(step_seconds=1))
        gate = asyncio.Event()
        entered = asyncio.Event()
        notifier = _GatedNotifier(gate, entered)
        state = _state(store, audit, notifier)
        try:
            # 첫 접수: 백그라운드 작업이 첫 채널에서 멈춘다.
            await enqueue_and_deliver(_request(state), kind='product_feedback',
                                      target_id='fb_' + '1' * 32, label='chat')
            await asyncio.wait_for(entered.wait(), timeout=5)
            # 둘째 접수: 같은 대기분을 함께 집으려 하는 두 번째 작업이 뜬다.
            await enqueue_and_deliver(_request(state), kind='site_feedback',
                                      target_id='sf_' + '2' * 32,
                                      label='miraen-home')
            assert len(await store.pending()) == 2
            # 멈춘 동안에는 첫 채널 한 번만 나갔다.
            assert notifier.calls == ['telegram']
            gate.set()
            await drain_alert_tasks(state)
            # 락이 없으면 두 작업이 같은 건을 함께 집어 채널당 2번이 된다.
            counts = Counter(notifier.calls)
            assert counts == {'telegram': 2, 'discord': 2, 'email': 2}, counts
            # 건이 2개이므로 채널당 2번 = 건당 정확히 1번.
            assert len(notifier.calls) == 6
            assert await store.pending() == []
            status = await store.status()
            for row in status['channels']:
                assert row['attempts'] == 2, row
            assert state.ops_alert_tasks == set()
        finally:
            gate.set()
            db.close()
    asyncio.run(scenario())


def test_the_lock_is_created_once_and_shared_by_both_tasks():
    async def scenario():
        db, store, audit = _stores(_Clock())
        gate = asyncio.Event()
        entered = asyncio.Event()
        notifier = _GatedNotifier(gate, entered)
        state = _state(store, audit, notifier)
        try:
            assert getattr(state, 'ops_alert_lock', None) is None
            await enqueue_and_deliver(_request(state), kind='product_feedback',
                                      target_id='fb_' + '3' * 32, label='chat')
            await asyncio.wait_for(entered.wait(), timeout=5)
            first_lock = state.ops_alert_lock
            assert first_lock is not None
            assert first_lock.locked() is True
            await enqueue_and_deliver(_request(state), kind='round_score',
                                      target_id='opsrs_' + '4' * 32,
                                      label='round_score')
            assert state.ops_alert_lock is first_lock
            gate.set()
            await drain_alert_tasks(state)
            assert state.ops_alert_lock is first_lock
            assert first_lock.locked() is False
        finally:
            gate.set()
            db.close()
    asyncio.run(scenario())


def test_a_single_submission_still_sends_each_channel_once():
    async def scenario():
        db, store, audit = _stores(_Clock())
        notifier = _GatedNotifier(asyncio.Event(), asyncio.Event())
        notifier._gate.set()
        state = _state(store, audit, notifier)
        try:
            await enqueue_and_deliver(_request(state), kind='site_feedback',
                                      target_id='sf_' + '5' * 32,
                                      label='miraen-home')
            await drain_alert_tasks(state)
            assert Counter(notifier.calls) == {
                'telegram': 1, 'discord': 1, 'email': 1}
            assert await store.pending() == []
        finally:
            db.close()
    asyncio.run(scenario())