"""No live PC, no deployment settings, no production database."""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from app.d1_sqlite import SqliteD1
from app.pc_helper_registration import SOURCE_SHA256, registration_command
from app.pc_helper_maintenance import (
    MaintenanceAttemptStore, PrecontactProof, admit_maintenance,
)

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
STAMP = NOW.isoformat()
DEVICE = "node//managed-fixture"
MANIFEST = {"version": "0.3.0-rc2", "sha256": "a" * 64,
            "download_url": "https://downloads.padiem.net/pc-helper/0.3.0-rc2/padiem-user-helper.exe",
            "min_supported_version": "0.3.0-rc1"}
LINK = {"mesh_node_id": DEVICE, "state": "active", "paused_at": None,
        "managed_at": STAMP, "managed_by": "usr_admin", "user_id": "usr_owner",
        "link_id": "pcl_fixture"}
OBS = {"device_id": DEVICE, "received_at": STAMP, "state": {
    "helper_status_present": True, "helper_sha256": "b" * 64,
    "helper_version": "0.3.0-rc1", "updater_source_present": True,
    "updater_source_sha256": "c" * 64, "updater_task_present": True,
    "self_heal_task_present": True,
}}
ROLLOUT = {"initialized": True, "stage": "internal", "percent": 10,
           "stable": {**MANIFEST, "version": "0.3.0-rc1", "sha256": "b" * 64},
           "target": MANIFEST}
UPDATE = {"PADIEM_PC_HELPER_AUTO_UPDATE_ENABLED": "1"}
INSTALL = {**UPDATE, "PADIEM_PC_HELPER_AUTO_INSTALL_ENABLED": "1"}


def admit(**changes):
    args = dict(env=UPDATE, device_id=DEVICE, managed_links=[LINK], admin_now=True,
                online=True, owner_session=True, owner_auto_update=True,
                observation=OBS, manifest=MANIFEST, rollout=ROLLOUT, now=NOW,
                target_device_id=DEVICE, target_link_id=LINK["link_id"])
    return admit_maintenance(**{**args, **changes})


def test_exact_fixed_bytes_and_shared_refresh_lock():
    intent, reason = admit()
    assert reason is None
    assert intent.command == registration_command()
    assert intent.source_sha256 == hashlib.sha256(intent.command.encode()).hexdigest()
    assert intent.registration_sha256 == SOURCE_SHA256
    assert intent.release_sha256 == MANIFEST["sha256"]
    assert intent.action == "refresh"
    assert admit(command=intent.command, source_sha256=intent.source_sha256)[0] == intent


@pytest.mark.parametrize(("changes", "reason"), [
    ({"env": {}}, "switch_off"),
    ({"managed_links": []}, "not_managed"),
    ({"managed_links": [LINK, LINK]}, "owner_ambiguous"),
    ({"managed_links": [{**LINK, "managed_at": None}]}, "not_managed"),
    ({"managed_links": [{**LINK, "paused_at": STAMP}]}, "not_managed"),
    ({"admin_now": False}, "manager_not_admin"),
    ({"online": False}, "offline"),
    ({"owner_session": False}, "owner_unresolved"),
    ({"owner_auto_update": False}, "owner_auto_update_off"),
    ({"owner_auto_update": None}, "owner_auto_update_off"),
    ({"owner_auto_update": 1}, "owner_auto_update_off"),
    ({"device_id": "01234567-89ab-cdef-0123-456789abcdef"}, "device_unverified"),
    ({"target_device_id": "node//other"}, "target_mismatch"),
    ({"target_link_id": "pcl_other"}, "target_mismatch"),
    ({"manifest": {**MANIFEST, "sha256": "invalid"}}, "release_unpinned"),
    ({"rollout": {**ROLLOUT, "stage": "paused"}}, "stage_closed"),
    ({"rollout": {**ROLLOUT, "initialized": False}}, "stage_closed"),
    ({"rollout": {**ROLLOUT, "target": {**MANIFEST, "sha256": "d" * 64}}}, "stage_closed"),
    ({"observation": {**OBS, "device_id": "node//other"}}, "observation_unverified"),
    ({"observation": {**OBS, "received_at": (NOW - timedelta(seconds=181)).isoformat()}}, "observation_stale"),
    ({"command": "arbitrary"}, "command_mismatch"),
    ({"source_sha256": "d" * 64}, "source_mismatch"),
])
def test_admission_denies_before_any_dispatch(changes, reason):
    assert admit(**changes) == (None, reason)


def test_install_requires_both_switches_and_explicit_absence():
    absent = {**OBS, "state": {"helper_status_present": False}}
    assert admit(observation=absent) == (None, "install_switch_off")
    assert admit(env={"PADIEM_PC_HELPER_AUTO_INSTALL_ENABLED": "1"},
                 observation=absent) == (None, "switch_off")
    intent, reason = admit(env=INSTALL, observation=absent)
    assert reason is None and intent.action == "install"
    assert intent.registration_sha256 == intent.source_sha256
    unknown = {**OBS, "state": {"helper_status_present": True}}
    assert admit(env=INSTALL, observation=unknown) == (None, "digest_unverified")


@pytest.mark.parametrize("missing", [
    ("updater_source_sha256",), ("updater_task_present",),
    ("updater_source_present", "updater_source_sha256", "updater_task_present"),
])
def test_fresh_installed_file_only_observation_selects_fixed_refresh(missing):
    state = {k: v for k, v in OBS["state"].items() if k not in missing}
    observation = {**OBS, "state": state}
    intent, reason = admit(observation=observation)
    assert reason is None and intent.action == "refresh"
    assert intent.command == registration_command()
    assert intent.registration_sha256 == SOURCE_SHA256
    assert admit(observation=observation, owner_session=False) == (None, "owner_unresolved")
    assert admit(observation=observation, admin_now=False) == (None, "manager_not_admin")
    assert admit(observation=observation, command="arbitrary") == (None, "command_mismatch")
    assert admit(observation=observation, source_sha256="d" * 64) == (None, "source_mismatch")


@pytest.mark.parametrize("change", [
    {"helper_sha256": None}, {"helper_sha256": "invalid"}, {"helper_version": None},
])
def test_missing_install_evidence_never_opens_unknown_probe_refresh(change):
    state = {**OBS["state"], "updater_source_sha256": None, **change}
    assert admit(observation={**OBS, "state": state}) == (None, "digest_unverified")


@pytest.mark.parametrize("watcher", [None, False, True])
def test_current_updater_with_unobserved_watcher_selects_only_fixed_refresh(watcher):
    state = {**OBS["state"], "helper_version": MANIFEST["version"],
             "updater_source_sha256": SOURCE_SHA256}
    if watcher is None:
        state.pop("self_heal_task_present")
    else:
        state["self_heal_task_present"] = watcher
    observation = {**OBS, "state": state}
    intent, reason = admit(observation=observation)
    if watcher is True:
        assert intent is None and reason == "already_current"
    else:
        assert reason is None and intent.action == "refresh"
        assert intent.command == registration_command()
        assert admit(observation=observation, owner_session=False) == (None, "owner_unresolved")
        assert admit(observation=observation, managed_links=[]) == (None, "not_managed")
        assert admit(observation=observation, rollout={**ROLLOUT, "stage": "paused"}) == (None, "stage_closed")


def _db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript((Path(__file__).resolve().parents[1] / "migrations" /
                      "137_pc_helper_auto_attempts.sql").read_text())
    return db


def test_atomic_claim_defer_retry_limit_and_stale_callback():
    async def run():
        db = _db()
        try:
            store = MaintenanceAttemptStore(SqliteD1(db))
            digest = "c" * 64
            key = dict(device_id=DEVICE, source_sha256=digest, now=STAMP)
            # One deferred record and therefore one alert; no claim/run.
            assert await store.defer_no_owner(**key)
            assert not await store.defer_no_owner(**key)
            claims = await asyncio.gather(*(store.reserve(**key) for _ in range(12)))
            assert len([x for x in claims if x]) == 1
            claim = next(x for x in claims if x)
            for proof in (PrecontactProof.NO_DISPATCH_ROW, PrecontactProof.CANCELLED_UNCLAIMED):
                assert await store.settle(claim, now=STAMP, proof=proof)
                assert not await store.settle(claim, now=STAMP, proof=proof)
                previous = claim
                claim = await store.reserve(**key)
                assert claim and claim != previous
                assert not await store.settle(previous, now=STAMP, verified=True)
            assert await store.settle(claim, now=STAMP, proof=PrecontactProof.NO_DISPATCH_ROW)
            assert await store.reserve(**key) is None
            row = db.execute("SELECT attempts,stopped,last_reason FROM pc_helper_auto_attempts").fetchone()
            assert tuple(row) == (3, 1, "stopped_precontact_limit")
        finally:
            db.close()
    asyncio.run(run())


def test_unknown_contact_stops_and_global_concurrency_limit():
    async def run():
        db = _db()
        try:
            store = MaintenanceAttemptStore(SqliteD1(db))
            keys = [dict(device_id=f"node//pc-{n}", source_sha256="c" * 64, now=STAMP)
                    for n in range(10)]
            claims = await asyncio.gather(*(store.reserve(**key) for key in keys))
            assert len([x for x in claims if x]) == 3
            claim = claims[0]
            # A string that sounds like proof is not queue proof.
            assert await store.settle(claim, now=STAMP, proof="no_dispatch_row")
            assert not await store.settle(claim, now=STAMP)
            assert await store.reserve(**keys[0]) is None
            assert await store.reserve(**keys[3])
            assert await store.settle(claims[1], now=STAMP, verified=True)
            assert await store.reserve(**keys[1]) is None
            assert await store.reserve(**{**keys[1], "source_sha256": "d" * 64})
        finally:
            db.close()
    asyncio.run(run())



@pytest.mark.parametrize("state", [
    "empty", "owner_unresolved", "retryable", "retry_limit", "stopped", "verified",
    "null_reason", "stopped_reopenable_reason", "same_device_in_flight", "global_limit"])
def test_reservable_mirrors_reserve_8772(state):
    """The read-only precheck answers exactly what the atomic claim would."""
    async def run():
        db = _db()
        try:
            store = MaintenanceAttemptStore(SqliteD1(db))
            digest = "c" * 64
            insert = ("INSERT INTO pc_helper_auto_attempts (device_id,source_sha256,attempts,"
                      "stopped,last_reason,updated_at) VALUES (?,?,?,?,?,?)")
            rows = {
                "owner_unresolved": [(DEVICE, digest, 0, 0, "owner_unresolved")],
                "retryable": [(DEVICE, digest, 2, 0, "retryable_precontact")],
                "retry_limit": [(DEVICE, digest, 3, 0, "retryable_precontact")],
                "stopped": [(DEVICE, digest, 1, 1, "stopped_contact_or_unknown")],
                "verified": [(DEVICE, digest, 0, 1, "verified")],
                "null_reason": [(DEVICE, digest, 0, 0, None)],
                "stopped_reopenable_reason": [(DEVICE, digest, 1, 1, "retryable_precontact")],
                "same_device_in_flight": [(DEVICE, "d" * 64, 0, 0, "reserved:" + "e" * 32)],
                "global_limit": [(f"node//pc-{n}", digest, 0, 0, "reserved:" + str(n) * 32)
                                 for n in range(3)],
            }.get(state, [])
            for row in rows:
                db.execute(insert, (*row, STAMP))
            db.commit()
            key = dict(device_id=DEVICE, source_sha256=digest)
            predicted = await store.reservable(**key)
            claimed = await store.reserve(**key, now=STAMP)
            assert predicted is (claimed is not None)
            # Read-only: the precheck alone never changes a row.
            if claimed is None:
                before = db.execute("SELECT * FROM pc_helper_auto_attempts ORDER BY device_id").fetchall()
                assert await store.reservable(**key) is False
                after = db.execute("SELECT * FROM pc_helper_auto_attempts ORDER BY device_id").fetchall()
                assert [tuple(r) for r in before] == [tuple(r) for r in after]
        finally:
            db.close()
    asyncio.run(run())
