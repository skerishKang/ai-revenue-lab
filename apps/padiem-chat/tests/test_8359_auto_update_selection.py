"""#8359 step 1: managed-PC selection and bounded attempt bookkeeping."""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.d1_sqlite import SqliteD1
from app.pc_helper_auto_update import (
    Attempt, D1PcHelperAutoAttemptStore, auto_update_enabled, failure_attempt,
    needs_update, select,
)
from _support.ops_audit_helpers import database

CHAT_DIR = Path(__file__).resolve().parents[1]
SOURCE = "c" * 64
OLD = "a" * 64
READY = {
    "state": {"updater_source_sha256": SOURCE, "updater_task_present": True},
    "helper_version": "0.3.0-rc2",
}
ROLLOUT = {"initialized": True, "revision": 1, "stage": "all", "percent": 25,
           "stable": {"version": "0.3.0-rc1", "sha256": OLD,
                      "min_supported_version": "0.3.0-rc1"},
           "target": {"version": "0.3.0-rc2", "sha256": SOURCE,
                      "min_supported_version": "0.3.0-rc1"}}


def test_switch_is_off_until_an_explicit_value():
    assert auto_update_enabled({}) is False
    assert auto_update_enabled({"PADIEM_PC_HELPER_AUTO_UPDATE_ENABLED": "false"}) is False
    assert auto_update_enabled({"PADIEM_PC_HELPER_AUTO_UPDATE_ENABLED": "1"}) is True


def test_needs_update_covers_missing_wrong_and_old_evidence():
    assert needs_update(None, source_sha256=SOURCE, min_version="0.3.0-rc1") is True
    assert needs_update(READY, source_sha256=SOURCE, min_version="0.3.0-rc1") is False
    assert needs_update(READY, source_sha256=OLD, min_version="0.3.0-rc1") is True
    assert needs_update(READY, source_sha256=SOURCE, min_version="0.4.0") is True
    outdated = {**READY, "helper_version": "0.2.0"}
    assert needs_update(outdated, source_sha256=SOURCE, min_version="0.3.0-rc1") is True


def test_selection_is_managed_only_once_per_source_and_stops_after_two_failures():
    devices = ["managed-old", "managed-new", "unmanaged", "already", "stopped"]
    managed = set(devices) - {"unmanaged"}
    observations = {device: READY for device in devices}
    observations["managed-old"] = None
    attempts = {
        ("already", SOURCE): Attempt(count=1),
        ("stopped", SOURCE): Attempt(count=2, stopped=True, reason="dispatch_refused"),
    }
    selected = select(
        devices=devices, managed=managed, observations=observations, rollout=ROLLOUT,
        source_sha256=SOURCE, min_version="0.3.0-rc1", attempts=attempts,
    )
    assert selected == ["managed-old"]
    # A source the staged rollout does not offer is not selected.
    assert select(
        devices=devices, managed=managed, observations=observations, rollout=ROLLOUT,
        source_sha256=OLD, min_version="0.3.0-rc1", attempts=attempts,
    ) == []


def test_failure_attempt_stops_after_two():
    first = failure_attempt(0, reason="dispatch_refused")
    assert first.count == 1 and first.stopped is False
    second = failure_attempt(first.count, reason="dispatch_refused")
    assert second.count == 2 and second.stopped is True


def test_attempt_store_keeps_one_row_per_pc_and_source():
    async def run():
        db, _feedback = database(full=True)
        try:
            db.executescript((CHAT_DIR / "migrations" / "137_pc_helper_auto_attempts.sql").read_text())
            store = D1PcHelperAutoAttemptStore(SqliteD1(db))
            assert await store.load_all(source_sha256=SOURCE) == {}
            assert await store.record(device_id="pc-one", source_sha256=SOURCE,
                                      attempt=Attempt(count=1), now="2026-11-22T00:00:00Z")
            loaded = await store.load_all(source_sha256=SOURCE)
            assert loaded[("pc-one", SOURCE)].count == 1
            await store.record(device_id="pc-one", source_sha256=SOURCE,
                               attempt=Attempt(count=2, stopped=True, reason="dispatch_refused"),
                               now="2026-11-22T00:01:00Z")
            loaded = await store.load_all(source_sha256=SOURCE)
            assert loaded[("pc-one", SOURCE)].stopped is True
            assert len(loaded) == 1
        finally:
            db.close()
    asyncio.run(run())


def test_selection_and_failure_bookkeeping_alert_and_audit_once():
    from app.pc_helper_auto_update import record_failure, record_selection

    async def run():
        db, _feedback = database(full=True)
        try:
            db.executescript((CHAT_DIR / "migrations" / "137_pc_helper_auto_attempts.sql").read_text())
            state = type("State", (), {
                "pc_helper_auto_attempt_store": D1PcHelperAutoAttemptStore(SqliteD1(db)),
            })()
            alerts, audits = [], []

            async def alert(device, action):
                alerts.append((device, action))

            async def audit(action, device):
                audits.append((action, device))

            kwargs = dict(device_id="pc-one", source_sha256=SOURCE, now="2026-11-22T00:00:00Z",
                          alert=alert, audit=audit)
            assert await record_selection(state, **kwargs) is True
            assert await record_selection(state, **kwargs) is False
            assert alerts == [("pc-one", "helper_auto_update_selected")]
            first = await record_failure(state, reason="dispatch_refused", **kwargs)
            assert first is not None and first.stopped is False
            second = await record_failure(state, reason="dispatch_refused", **kwargs)
            assert second is not None and second.stopped is True
            third = await record_failure(state, reason="dispatch_refused", **kwargs)
            assert third is not None and third.stopped is True
            assert len(alerts) == 3 and len(audits) == 3
            assert alerts[-1] == ("pc-one", "helper_auto_update_stopped")
        finally:
            db.close()
    asyncio.run(run())
