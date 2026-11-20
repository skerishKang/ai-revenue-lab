"""#8130: public service boundary and durable outbox/digest behavior."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE
from app.d1_sqlite import SqliteD1
from app.local_cpython import apply_migrations
from app.ops_alert_delivery import (
    daily_summary_loop,
    dispatch_pending_alerts,
    drain_alert_tasks,
)
from app.ops_alert_routes import ops_notify_event
from app.ops_alert_store import D1OpsAlertStore
from app.ops_notify_event import KEY_HEADER, SITE_LINKS

KEY_NAME = "PADIEM_OPS_NOTIFY_KEY_LOVETREE"
FIXTURE_KEY = "unit-test-placeholder"
BASE_EVENT = dict(site="lovetree", kind="feedback_new", audience="real",
                  title="새 의견", source_id="feedback-1")


class Clock:
    def __init__(self):
        self.moment = datetime(2026, 11, 20, 14, 59, tzinfo=timezone.utc)

    def __call__(self):
        return self.moment


class Notifier:
    channels = {"telegram": (), "discord": ()}

    def __init__(self, fail=()):
        self.fail = set(fail)
        self.calls = []

    async def _send(self, channel, *, message, subject):
        self.calls.append((channel, message))
        return channel not in self.fail


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv(KEY_NAME, FIXTURE_KEY)
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    apply_migrations(db)
    clock = Clock()
    state = SimpleNamespace(ops_alert_store=D1OpsAlertStore(SqliteD1(db), now=clock),
                            ops_alert_notifier=Notifier())
    yield db, state, clock
    db.close()


async def submit(state, event=None, *, key=FIXTURE_KEY, headers=(), raw=None):
    data = raw if raw is not None else json.dumps(
        BASE_EVENT if event is None else event).encode()
    request_headers = [(b"content-type", b"application/json")]
    if key is not None:
        request_headers.append((KEY_HEADER.lower().encode(), key.encode()))
    request_headers.extend(headers)

    async def receive():
        return {"type": "http.request", "body": data, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/api/ops/notify-event",
                       "query_string": b"", "headers": request_headers,
                       "app": SimpleNamespace(state=state)}, receive)
    return await ops_notify_event(request)


def test_service_key_is_the_only_authority(service, monkeypatch):
    db, state, _ = service

    async def scenario():
        for key, headers in (
            (None, ()), ("wrong", ()),
            (None, [(b"cookie", (SESSION_COOKIE + "=session").encode())]),
            (FIXTURE_KEY, [(b"cookie", (SESSION_COOKIE + "=session").encode())]),
            (FIXTURE_KEY, [(b"authorization", b"Bearer session")]),
            (FIXTURE_KEY, [(b"origin", b"https://example.test")]),
        ):
            assert (await submit(state, key=key, headers=headers)).status_code == 401
        assert (await submit(state, {**BASE_EVENT, "site": "unknown"})).status_code == 401
        monkeypatch.delenv(KEY_NAME)
        assert (await submit(state)).status_code == 401
        assert await state.ops_alert_store.pending() == []
        assert state.ops_alert_notifier.calls == []
        assert db.execute("SELECT COUNT(*) FROM ops_alert_outbox").fetchone()[0] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("change", [
    {"kind": "unknown"}, {"audience": "tester"}, {"title": "x" * 81},
    {"title": ""}, {"title": "a\nb"}, {"source_id": ""}, {"source_id": 5},
    {"source_id": "person@example.test"}, {"body": "forbidden"},
    {"email": "person@example.test"}, {"account_id": "user"},
    {"link": "https://wrong.example.test"}, {"title": None},
])
def test_unknown_fields_and_invalid_values_are_refused(service, change):
    _, state, _ = service

    async def scenario():
        assert (await submit(state, {**BASE_EVENT, **change})).status_code == 400
        assert (await state.ops_alert_store.status())["pending"] == 0

    asyncio.run(scenario())


def test_missing_duplicate_and_oversized_fields_are_refused(service):
    _, state, _ = service

    async def scenario():
        event = dict(BASE_EVENT)
        del event["title"]
        assert (await submit(state, event)).status_code == 400
        raw = json.dumps(BASE_EVENT).encode()[:-1] + b',"title":"twice"}'
        assert (await submit(state, raw=raw)).status_code == 400
        assert (await submit(state, raw=b"x" * 4097)).status_code == 400
        assert (await state.ops_alert_store.status())["pending"] == 0

    asyncio.run(scenario())


def test_real_event_is_queued_once_and_dispatched_with_server_link(service):
    db, state, _ = service

    async def scenario():
        # Two concurrent deliveries of the same event still create one row.
        responses = await asyncio.gather(submit(state), submit(state))
        assert [response.status_code for response in responses] == [202, 202]
        await drain_alert_tasks(state)
        assert len(state.ops_alert_notifier.calls) == 2
        for _, message in state.ops_alert_notifier.calls:
            assert BASE_EVENT["title"] in message
            assert SITE_LINKS["lovetree"] in message
            assert BASE_EVENT["source_id"] in message
        assert db.execute("SELECT COUNT(*) FROM ops_alert_outbox").fetchone()[0] == 1
        assert (await submit(state)).status_code == 202
        await drain_alert_tasks(state)
        assert len(state.ops_alert_notifier.calls) == 2
        assert (await state.ops_alert_store.status())["pending_by_site"] == {
            "chat": 0, "lovetree": 0, "pc": 0}
        # Different kind may reuse the same source id.
        assert (await submit(state, {**BASE_EVENT, "kind": "feedback_append"})).status_code == 202
        await drain_alert_tasks(state)
        assert len(state.ops_alert_notifier.calls) == 4

    asyncio.run(scenario())


def test_delivery_failure_keeps_receipts_and_pending_even_with_duplicate(service):
    _, state, _ = service
    state.ops_alert_notifier = Notifier(fail=("discord",))

    async def scenario():
        assert (await submit(state)).status_code == 202
        await drain_alert_tasks(state)
        assert (await state.ops_alert_store.status())["pending_by_site"]["lovetree"] == 1
        assert (await submit(state)).status_code == 202
        await drain_alert_tasks(state)
        assert len(state.ops_alert_notifier.calls) == 2
        state.ops_alert_notifier.fail.clear()
        assert await dispatch_pending_alerts(state) == {"sent": 1, "failed": 0, "processed": 1}
        assert [channel for channel, _ in state.ops_alert_notifier.calls] == [
            "telegram", "discord", "discord"]
        assert (await state.ops_alert_store.status())["pending"] == 0

    asyncio.run(scenario())


def test_daily_summary_uses_closed_kst_day_and_counts_only_unique_events(service):
    db, state, clock = service

    async def scenario():
        event = {**BASE_EVENT, "audience": "ai"}
        for item in (event, event, {**event, "kind": "ai_round_score", "source_id": "score-1"}):
            assert (await submit(state, item)).status_code == 202
        assert state.ops_alert_notifier.calls == []
        assert (await state.ops_alert_store.status())["pending_by_site"]["lovetree"] == 2
        assert (await dispatch_pending_alerts(state))["processed"] == 0
        clock.moment += timedelta(minutes=1)  # KST midnight
        # The timer checks even when no new events arrive. No wall-clock wait.
        async def one_tick(seconds):
            assert seconds == 3600
            raise asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await daily_summary_loop(state, sleep=one_tick)
        assert len(state.ops_alert_notifier.calls) == 2
        for _, message in state.ops_alert_notifier.calls:
            assert "2건" in message and "2026-11-20" in message
            assert BASE_EVENT["title"] not in message
            assert SITE_LINKS["lovetree"] in message
        assert (await state.ops_alert_store.status())["pending"] == 0
        assert (await dispatch_pending_alerts(state))["processed"] == 0
        assert (await submit(state, event)).status_code == 202
        assert (await state.ops_alert_store.status())["pending"] == 0
        assert db.execute("SELECT COUNT(*) FROM ops_alert_outbox").fetchone()[0] == 3
        assert len(state.ops_alert_notifier.calls) == 2

    asyncio.run(scenario())


def test_failed_summary_retries_only_missing_channel_and_retains_counts(service):
    _, state, clock = service
    state.ops_alert_notifier = Notifier(fail=("discord",))

    async def scenario():
        assert (await submit(state, {**BASE_EVENT, "audience": "ai"})).status_code == 202
        clock.moment += timedelta(minutes=1)
        assert (await dispatch_pending_alerts(state))["failed"] == 1
        assert (await state.ops_alert_store.status())["pending_by_site"]["lovetree"] == 1
        state.ops_alert_notifier.fail.clear()
        assert (await dispatch_pending_alerts(state))["sent"] == 1
        assert (await state.ops_alert_store.status())["pending_by_site"]["lovetree"] == 0
        assert len(state.ops_alert_notifier.calls) == 3
        assert (await dispatch_pending_alerts(state))["processed"] == 0

    asyncio.run(scenario())


def test_dispatch_contends_for_the_same_process_file_lock(service, tmp_path):
    from app.local_bootstrap import ProcessFileLock

    _, state, _ = service
    path = tmp_path / "outbox.lock"
    first = ProcessFileLock(path)
    second = ProcessFileLock(path)
    state.ops_alert_process_lock = second

    async def scenario():
        assert first.acquire(wait=False)
        await state.ops_alert_store.enqueue_event(BASE_EVENT)
        calls = []

        async def release_on_wait(seconds):
            calls.append(seconds)
            assert state.ops_alert_notifier.calls == []
            first.release()

        try:
            result = await dispatch_pending_alerts(state, sleep=release_on_wait)
            assert calls == [0.1]
            assert result == {"processed": 1, "sent": 2, "failed": 0}
            assert not second.held
            assert first.acquire(wait=False)
        finally:
            first.release()
            second.release()

    asyncio.run(scenario())


def test_pc_agent_stall_is_accepted_and_dispatched_with_ops_link(service, monkeypatch):
    """#8140: site=pc / kind=agent_stall is a valid real-time event."""
    db, state, _ = service
    monkeypatch.setenv("PADIEM_OPS_NOTIFY_KEY_PC", FIXTURE_KEY)
    event = dict(site="pc", kind="agent_stall", audience="real",
                 title="PC 에이전트 응답 없음: COMP1", source_id="stall_abc123")

    async def scenario():
        assert (await submit(state, event)).status_code == 202
        await drain_alert_tasks(state)
        assert len(state.ops_alert_notifier.calls) == 2
        for _, message in state.ops_alert_notifier.calls:
            assert event["title"] in message
            assert SITE_LINKS["pc"] in message
        # The pc key is the only authority for the new site.
        monkeypatch.delenv("PADIEM_OPS_NOTIFY_KEY_PC")
        assert (await submit(state, event)).status_code == 401
        # Unknown kinds stay refused even with the correct pc key.
        monkeypatch.setenv("PADIEM_OPS_NOTIFY_KEY_PC", FIXTURE_KEY)
        assert (await submit(state, {**event, "kind": "unknown"})).status_code == 400

    asyncio.run(scenario())


def test_new_real_event_is_sent_before_an_older_backlog(service):
    _, state, _ = service

    async def scenario():
        for index in range(7):
            await state.ops_alert_store.enqueue(
                kind="product_feedback", target_id=f"old_{index}", label="chat")
        assert (await submit(state)).status_code == 202
        await drain_alert_tasks(state)
        messages = [message for _, message in state.ops_alert_notifier.calls]
        assert all(BASE_EVENT["title"] in message and SITE_LINKS["lovetree"] in message
                   for message in messages[:2])
        assert (await state.ops_alert_store.status())["pending_by_site"]["lovetree"] == 0
        assert (await state.ops_alert_store.status())["pending_by_site"]["chat"] == 3

    asyncio.run(scenario())
