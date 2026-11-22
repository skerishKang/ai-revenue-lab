"""Manifest, authenticated observations, and admin-only version status."""
import asyncio
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.d1_sqlite import SqliteD1
from app.mesh_device_drive_store import D1MeshDeviceDriveStore
from app.pc_helper_version_routes import (
    ADMIN_PC_VERSIONS_PATH, HELPER_VERSION_PATH, MIN_SUPPORTED_VERSION,
    admin_ops_pc_versions, pc_helper_version,
)
from padiem_ai_core.pc_helper_ready import HelperReadyError, validate_helper_ready
from _support.ops_audit_helpers import OTHER, OWNER, SETTINGS, database, payload, request

URL = "https://downloads.example.test/pc-helper/0.3.0-rc1/padiem-user-helper.exe"
SHA = "a" * 64
DEVICE = "node//version-fixture"
OTHER_PC = "node//unobserved-fixture"
MESH = "2026-02-16T00:43:44.000Z"
NOW = datetime(2026, 11, 21, 1, 2, 3, tzinfo=timezone.utc)
LATER = datetime(2026, 11, 21, 2, 3, 4, tzinfo=timezone.utc)
READY = {"task_present": True, "install_dir_present": True, "pipe_open": True,
         "interactive_session": True, "helper_build": SHA[:12],
         "helper_sha256": SHA, "mesh_agent_version": MESH}
STAMP = "2026-11-21T01:02:03Z"


def configure(state, *, url=URL, sha=SHA):
    state.pc_pairing_user_helper_url = url
    state.pc_pairing_user_helper_sha256 = sha


def test_public_manifest_uses_actual_helper_settings_not_installer():
    app = create_app(settings=SETTINGS, history_store=object())
    configure(app.state)
    with TestClient(app) as client:
        answer = client.get(HELPER_VERSION_PATH)
        assert answer.status_code == 200
        assert answer.json() == {"version": "0.3.0-rc1", "sha256": SHA,
                                 "download_url": URL, "min_supported_version": MIN_SUPPORTED_VERSION}
        assert answer.json()["sha256"] == app.state.pc_pairing_user_helper_sha256
        assert answer.headers["cache-control"] == "no-store"
        assert client.post(HELPER_VERSION_PATH).status_code == 405
        assert client.get(ADMIN_PC_VERSIONS_PATH).status_code == 401


@pytest.mark.parametrize("url,sha", [(None, SHA), (URL, None), (URL, "bad"),
                                     (URL + "?token=synthetic", SHA),
                                     (URL.replace("https:", "http:"), SHA),
                                     (URL.replace("/0.3.0-rc1/", "/"), SHA),
                                     (URL.replace("0.3.0-rc1", ".."), SHA)])
def test_manifest_fails_closed_without_public_versioned_release(url, sha):
    async def run():
        req = request(None, user=None)
        configure(req.app.state, url=url, sha=sha)
        answer = await pc_helper_version(req)
        assert answer.status_code == 503 and answer.headers["cache-control"] == "no-store"
        assert payload(answer) == {"error": "helper_release_unavailable"}
    asyncio.run(run())


def test_stored_versions_last_healthy_and_admin_overview():
    async def run():
        db, feedback = database(full=True)
        try:
            store = D1MeshDeviceDriveStore(SqliteD1(db))
            assert await store.upsert_helper_ready(device_id=DEVICE, state=READY, received_at=NOW)
            assert await store.upsert_helper_ready(
                device_id=DEVICE, state={**READY, "pipe_open": False, "update_result": "rollback"}, received_at=LATER)
            row = await store.load_helper_ready(device_id=DEVICE, include_versions=True)
            assert row["helper_sha256"] == SHA
            assert row["mesh_agent_version"] == MESH
            assert row["last_healthy_at"] == STAMP
            assert row["state"]["pipe_open"] is False
            assert row["received_at"] == "2026-11-21T02:03:04Z"

            class Pairing:
                async def list_active_device_ids(self):
                    return [DEVICE, OTHER_PC]

            for user, expected in ((None, 401), (OWNER, 403), (OTHER, 200)):
                req = request(feedback, user=user, path=ADMIN_PC_VERSIONS_PATH)
                configure(req.app.state)
                req.app.state.pc_device_pairing_store = Pairing()
                req.app.state.mesh_device_drive_store = store
                answer = await admin_ops_pc_versions(req)
                assert answer.status_code == expected
                if expected == 200:
                    rows = payload(answer)["devices"]
                    assert rows == [
                        {"device_id": DEVICE, "display_name": None, "helper_version": "0.3.0-rc1",
                         "helper_build": SHA[:12], "mesh_agent_version": MESH,
                         "update_result": "rollback",
                         "last_healthy_at": STAMP, "received_at": "2026-11-21T02:03:04Z"},
                        {"device_id": OTHER_PC, "display_name": None, "helper_version": None, "helper_build": None,
                         "mesh_agent_version": None, "update_result": None,
                         "last_healthy_at": None, "received_at": None},
                    ]
                    assert answer.headers["cache-control"] == "no-store"
            failed_registration = {**READY, "update_result": "registration_failed",
                                   "update_registration_error": "updater_running"}
            assert await store.upsert_helper_ready(device_id=DEVICE, state=failed_registration, received_at=LATER)
            req = request(feedback, user=OTHER, path=ADMIN_PC_VERSIONS_PATH)
            configure(req.app.state)
            req.app.state.pc_device_pairing_store = Pairing()
            req.app.state.mesh_device_drive_store = store
            reported = payload(await admin_ops_pc_versions(req))["devices"][0]
            assert reported["update_result"] == "registration_failed"
            assert reported["update_registration_error"] == "updater_running"
            old = {**READY, "helper_version": "0.2.0"}
            assert await store.upsert_helper_ready(device_id=DEVICE, state=old, received_at=LATER)
            assert (await store.load_helper_ready(device_id=DEVICE, include_versions=True))["helper_version"] == "0.2.0"
        finally:
            db.close()
    asyncio.run(run())


@pytest.mark.parametrize("extra", [
    {"helper_sha256": "b" * 64}, {"helper_sha256": "bad"},
    {"helper_version": "folder/private"}, {"mesh_agent_version": "private text"},
    {"account": "private"}, {"helper_version": "0.3.0", "helper_sha256": None},
    {"update_result": "private text"},
    {"update_result": "registration_failed", "update_registration_error": "private path"},
    {"update_result": "success", "update_registration_error": "updater_running"},
])
def test_version_fields_are_bounded_and_digest_consistent(extra):
    with pytest.raises(HelperReadyError):
        validate_helper_ready({**READY, **extra})
