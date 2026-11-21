"""Staged offers, managed PC identity and authenticated outcome accounting."""
import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from app import pc_helper_version_routes as routes
from app.pc_helper_rollout import DEVICE_HEADER, cohort
from app.pc_helper_update_policy import load_update_view
from app.pc_device_pairing_routes import _install_helper_pair
from app.pc_device_pairing_store import D1PcPairingStore, derive_install_tag
from app.mesh_device_drive_store import D1MeshDeviceDriveStore
from app.d1_sqlite import SqliteD1
from padiem_ai_core.pc_helper_ready import HelperReadyError, validate_helper_ready
from _support.ops_audit_helpers import OWNER, OTHER, database, payload, request

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
STAMP = "2026-11-22T00:00:00Z"
STABLE_SHA = "a" * 64
NEW_SHA = "b" * 64
THIRD_SHA = "c" * 64
INTERNAL = "node//managed-fixture"
PC_IDS = ["node//rollout-" + str(i) for i in range(100)]
SELECTED = next(pc for pc in PC_IDS if cohort(pc, False, 25) == "percentage")
REMAINING = next(pc for pc in PC_IDS if cohort(pc, False, 25) == "remaining")
BASE_URL = "https://downloads.padiem.net/pc-helper/"
TAG = derive_install_tag("test-fixture")
READY = {"task_present": True, "install_dir_present": True, "pipe_open": True,
         "interactive_session": True, "helper_build": STABLE_SHA[:12],
         "helper_sha256": STABLE_SHA, "helper_version": "0.3.0-rc1"}


def deployment(state, version, sha):
    state.pc_pairing_user_helper_url = BASE_URL + version + "/padiem-user-helper.exe"
    state.pc_pairing_user_helper_sha256 = sha


@pytest.fixture
def fixture(monkeypatch):
    db, feedback = database(full=True)
    pairing = D1PcPairingStore(SqliteD1(db))
    drive = D1MeshDeviceDriveStore(SqliteD1(db))
    for idx, device in enumerate((INTERNAL, SELECTED, REMAINING)):
        db.execute(
            "INSERT INTO pc_device_links (link_id,user_id,mesh_node_id,state,created_at,updated_at,managed_at) "
            "VALUES (?,?,?,'active',?,?,?)",
            (str(idx), OWNER, device, STAMP, STAMP, STAMP if device == INTERNAL else None))
    db.execute(
        "INSERT INTO pc_pairing_codes (code_id,code_sha256,tag_sha256,user_id,state,mesh_node_id,issued_at,expires_at,claimed_at) "
        "VALUES (?,?,?,?,'claimed',?,?,?,?)",
        ("fixture-code", "d" * 64, hashlib.sha256(TAG.encode()).hexdigest(), OWNER,
         INTERNAL, STAMP, "2026-11-22T00:10:00Z", STAMP))
    monkeypatch.setattr(routes, "_now", lambda: NOW)
    req = request(feedback, user=OTHER)
    state = req.app.state
    state.pc_device_pairing_store = pairing
    state.mesh_device_drive_store = drive
    deployment(state, "0.3.0-rc1", STABLE_SHA)

    def make(*, user=OTHER, device=None, body=None):
        r = request(feedback, user=user, method="POST" if body else "GET", body=body)
        r.scope["app"].state = state
        if device is not None:
            r.scope["headers"].append((DEVICE_HEADER.lower().encode(), device.encode()))
        return r
    yield state, pairing, drive, make
    db.close()


def test_stages_pause_minimum_and_release_rollover(fixture, monkeypatch):
    state, pairing, drive, make = fixture

    async def run():
        async def offer(device=None):
            reply = await routes.pc_helper_version(make(user=None, device=device))
            assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store"
            return payload(reply)

        async def admin():
            reply = await routes.admin_ops_pc_versions(make())
            assert reply.status_code == 200
            return payload(reply)["rollout"]

        async def action(name, percent=25, user=OTHER, **override):
            plan = await admin()
            body = {"action": name, "percent": percent, "revision": plan["revision"],
                    "target_sha256": plan["target"]["sha256"], **override}
            return await routes.admin_change_rollout(make(user=user, body=body))

        assert (await offer())["sha256"] == STABLE_SHA
        assert not (await admin())["initialized"]
        assert (await action("initialize", user=None)).status_code == 401
        assert (await action("initialize", user=OWNER)).status_code == 403
        assert await pairing.load_helper_rollout() is None
        assert (await action("initialize")).status_code == 200
        assert (await pairing.load_helper_rollout())["updated_at"].startswith("2026-11-22T00:00:00")
        deployment(state, "0.3.0-rc2", NEW_SHA)
        assert (await admin())["stage"] == "internal"
        for pc in (INTERNAL, TAG):
            assert (await offer(pc))["sha256"] == NEW_SHA
        for pc in (SELECTED, REMAINING, "unknown", None):
            assert (await offer(pc))["sha256"] == STABLE_SHA
        assert (await _install_helper_pair(state))[1] == STABLE_SHA
        assert (await action("next", revision=0)).status_code == 409
        assert (await action("next")).status_code == 200
        assert (await admin())["stage"] == "percentage"
        assert (await offer(SELECTED))["sha256"] == NEW_SHA
        assert (await offer(REMAINING))["sha256"] == STABLE_SHA
        assert (await offer(SELECTED))["sha256"] == NEW_SHA
        assert (await drive.upsert_helper_ready(device_id=REMAINING, state=READY, received_at=NOW))
        assert not (await load_update_view(state, device_id=REMAINING, now=NOW))["update_available"]
        assert (await action("pause")).status_code == 200
        for pc in (INTERNAL, TAG, SELECTED, REMAINING, None):
            assert (await offer(pc))["sha256"] == STABLE_SHA
        deployment(state, "0.3.0-rc3", THIRD_SHA)
        assert (await admin())["stage"] == "paused"
        assert (await offer(INTERNAL))["sha256"] == STABLE_SHA
        deployment(state, "0.3.0-rc2", NEW_SHA)
        monkeypatch.setattr(routes, "MIN_SUPPORTED_VERSION", "0.3.0-rc2")
        for pc in (INTERNAL, REMAINING, None):
            assert (await offer(pc))["sha256"] == NEW_SHA
        view = await load_update_view(state, device_id=REMAINING, now=NOW)
        assert view["update_required"] and view["update_available"]
        monkeypatch.setattr(routes, "MIN_SUPPORTED_VERSION", "0.3.0-rc1")
        assert (await action("next")).status_code == 200
        assert (await action("next")).status_code == 200
        assert (await action("next")).status_code == 200
        assert (await offer())["sha256"] == NEW_SHA
        deployment(state, "0.3.0-rc3", THIRD_SHA)
        assert (await admin())["stage"] == "internal"
        assert (await offer(INTERNAL))["sha256"] == THIRD_SHA
        assert (await offer(REMAINING))["sha256"] == NEW_SHA
    asyncio.run(run())


def test_outcomes_are_per_release_and_survive_later_receipts(fixture):
    state, _, drive, make = fixture

    async def run():
        deployment(state, "0.3.0-rc2", NEW_SHA)
        updated = {**READY, "helper_sha256": NEW_SHA, "helper_build": NEW_SHA[:12],
                   "helper_version": "0.3.0-rc2", "update_result": "success", "update_target_sha256": NEW_SHA}
        for device, row in ((INTERNAL, updated),
                            (SELECTED, {**READY, "update_result": "hash_mismatch", "update_target_sha256": NEW_SHA}),
                            (REMAINING, {**READY, "update_result": "rollback", "update_target_sha256": NEW_SHA})):
            assert await drive.upsert_helper_ready(device_id=device, state=row, received_at=NOW)
        assert await drive.upsert_helper_ready(device_id=SELECTED, state=READY, received_at=NOW)
        assert await drive.load_rollout_outcomes(sha256=NEW_SHA) == {
            INTERNAL: "updated", SELECTED: "failed", REMAINING: "rollback"}
        assert await drive.load_rollout_outcomes(sha256=THIRD_SHA) == {}
        data = payload(await routes.admin_ops_pc_versions(make()))["rollout"]["groups"]
        assert sum(g["updated"] for g in data.values()) == 1
        assert sum(g["failed"] for g in data.values()) == 1
        assert sum(g["rollback"] for g in data.values()) == 1
        assert sum(g["total"] for g in data.values()) == 3
        with pytest.raises(HelperReadyError):
            validate_helper_ready({**READY, "update_target_sha256": "private path"})
    asyncio.run(run())


def test_cohort_is_stable_and_nested():
    # Pin SHA-256's first-eight-byte bucket with an independent calculation.
    buckets = {pc: int(hashlib.sha256(pc.encode()).hexdigest()[:16], 16) % 100 for pc in PC_IDS}
    for percent in (1, 10, 25, 99):
        expected = {pc for pc, bucket in buckets.items() if bucket < percent}
        assert {pc for pc in PC_IDS if cohort(pc, False, percent) == "percentage"} == expected
        assert all(cohort(pc, True, percent) == "internal" for pc in PC_IDS)
