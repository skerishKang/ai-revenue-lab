"""#8359 step 1: managed-PC selection and bounded attempt bookkeeping."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.d1_sqlite import SqliteD1
from app.pc_helper_auto_update import (
    Attempt, D1PcHelperAutoAttemptStore, auto_update_enabled, failure_attempt,
    needs_update, select, stage_allows,
)
from app.pc_helper_registration import SOURCE_SHA256
from app.pc_helper_rollout import effective_plan
from app.pc_helper_version_routes import helper_manifest
from padiem_ai_core.pc_helper_ready import validate_helper_ready
from _support.ops_audit_helpers import database

CHAT_DIR = Path(__file__).resolve().parents[1]
# The updater script source (attempt key) and the helper EXE release are two
# different digests; the fixtures keep them apart the way production does.
SOURCE = "c" * 64
OLD = "a" * 64
HELPER = "b" * 64
HELPER_OLD = "d" * 64
READY = {
    "state": {"updater_source_sha256": SOURCE, "updater_task_present": True},
    "helper_version": "0.3.0-rc2",
}
ROLLOUT = {"initialized": True, "revision": 1, "stage": "all", "percent": 25,
           "stable": {"version": "0.3.0-rc1", "sha256": HELPER_OLD,
                      "min_supported_version": "0.3.0-rc1"},
           "target": {"version": "0.3.0-rc2", "sha256": HELPER,
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
    # #8359 F7: an observed missing watcher needs work; an unreported key does not.
    watcher_missing = {**READY, "state": {**READY["state"], "self_heal_task_present": False}}
    assert needs_update(watcher_missing, source_sha256=SOURCE, min_version="0.3.0-rc1") is True
    watcher_present = {**READY, "state": {**READY["state"], "self_heal_task_present": True}}
    assert needs_update(watcher_present, source_sha256=SOURCE, min_version="0.3.0-rc1") is False


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
        source_sha256=SOURCE, helper_sha256=HELPER, min_version="0.3.0-rc1",
        attempts=attempts,
    )
    assert selected == ["managed-old"]
    # A helper release the staged rollout does not offer is not selected.
    assert select(
        devices=devices, managed=managed, observations=observations, rollout=ROLLOUT,
        source_sha256=SOURCE, helper_sha256=HELPER_OLD, min_version="0.3.0-rc1",
        attempts=attempts,
    ) == []


def _deployment(version, helper_sha256):
    return SimpleNamespace(
        pc_pairing_user_helper_url=(
            "https://downloads.padiem.net/pc-helper/" + version + "/padiem-user-helper.exe"),
        pc_pairing_user_helper_sha256=helper_sha256,
    )


def _observation(helper_sha256, *, updater_source_sha256):
    """One helper-ready row exactly as the executor reports and the store keeps it."""
    state = validate_helper_ready({
        "task_present": True, "install_dir_present": True, "pipe_open": True,
        "interactive_session": True, "helper_build": helper_sha256[:12],
        "helper_sha256": helper_sha256, "helper_version": "0.3.0-rc2",
        "helper_status_present": True, "updater_source_present": True,
        "updater_source_sha256": updater_source_sha256, "updater_task_present": True,
    })
    return {"device_id": "node//managed-fixture", "state": state,
            "received_at": "2026-11-22T00:00:00Z", "helper_sha256": helper_sha256,
            "helper_version": "0.3.0-rc2"}


def test_production_shaped_release_and_script_digests_select_a_managed_pc():
    """The rollout stages the helper EXE digest; the attempt key is the script digest.

    With the deployment manifest, an uninitialized rollout row and a helper-ready
    row shaped like the executor's report, a managed PC whose installed updater
    script is behind the fixed source is selected. The two digests never match
    each other, so a comparison across them would select nothing.
    """
    helper_sha256 = "e" * 64
    manifest = helper_manifest(_deployment("0.3.0-rc2", helper_sha256))
    assert manifest is not None and manifest["sha256"] != SOURCE_SHA256
    plan = effective_plan(None, manifest)
    device = "node//managed-fixture"
    observations = {device: _observation(helper_sha256, updater_source_sha256=OLD)}
    kwargs = dict(devices=[device], managed={device}, observations=observations,
                  rollout=plan, source_sha256=SOURCE_SHA256,
                  min_version=manifest["min_supported_version"], attempts={})
    assert select(helper_sha256=manifest["sha256"], **kwargs) == [device]
    # The script digest is not a release the rollout can offer.
    assert stage_allows(plan, device_id=device, helper_sha256=SOURCE_SHA256) is False
    assert select(helper_sha256=SOURCE_SHA256, **kwargs) == []
    # A paused rollout holds the stable release back from every cohort.
    paused = {**plan, "initialized": True, "stage": "paused",
              "stable": {**manifest, "sha256": "f" * 64, "version": "0.3.0-rc1"}}
    assert select(helper_sha256=manifest["sha256"], **{**kwargs, "rollout": paused}) == []
    # A PC whose installed script already matches the fixed source is current.
    current = {device: _observation(helper_sha256, updater_source_sha256=SOURCE_SHA256)}
    assert select(helper_sha256=manifest["sha256"], **{**kwargs, "observations": current}) == []


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
