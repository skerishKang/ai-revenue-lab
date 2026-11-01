"""PC inventory -> authenticated queue -> SQLite -> Chat proxy, without network."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import pathlib
import sqlite3
import sys

import httpx
import pytest

QUEUE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QUEUE.parent / "padiem-chat"))
sys.path.insert(0, str(QUEUE))

from app.mesh_device_drive_routes import MESH_DEVICE_DRIVES_PATH, MESH_DEVICE_DRIVE_TARGETS_PATH
from app.mesh_device_drive_store import MeshDeviceDriveStoreError
from app.queue_store_proxy import QueueBackedDriveStore, QueueStoreClient
from padiem_ai_core.pc_drive_inventory import DriveInventoryError, validate_drive_inventory
from schema import apply
from service import create_app

CHANNEL = "synthetic-drive-channel-secret"
SERVICE = "synthetic-drive-service-secret"
WATCH = "synthetic-drive-watch-secret"
DEVICE = "node//synthetic-pc-one"
OTHER = "node//synthetic-pc-two"
USER = "usr_" + "a" * 32
DRIVE = {"path": "C:/", "name": "System", "kind": "fixed",
         "free_bytes": 200, "total_bytes": 500}
USB = {"path": "E:/", "name": "USB", "kind": "removable",
       "free_bytes": None, "total_bytes": None}


def app_and_db():
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    apply(db)
    app = create_app(connection=db, channel_secret=CHANNEL, service_secret=SERVICE,
                     watch_secret=WATCH, legacy_map_lane=False)
    return app, db


def link(db, device=DEVICE, *, user=USER, state="active", paused=None):
    db.execute(
        "INSERT INTO pc_device_links (link_id,user_id,mesh_node_id,state,roots_json,"
        "created_at,updated_at,paused_at) VALUES (?,?,?,?,?,?,?,?)",
        (device + user[-1], user, device, state, "[]", "2026-11-01T00:00:00Z",
         "2026-11-01T00:00:00Z", paused),
    )


async def post(app, payload, *, channel=CHANNEL, path=MESH_DEVICE_DRIVES_PATH):
    headers = {} if channel is None else {"X-Oracle-Mesh-Secret": channel}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://queue.invalid") as client:
        return await client.post(path, json=payload, headers=headers)


def test_shared_inventory_normalizes_order_and_handles_empty_and_unknown_capacity():
    assert validate_drive_inventory([USB, {**DRIVE, "path": "c:\\"}]) == [DRIVE, USB]
    assert validate_drive_inventory([]) == []


@pytest.mark.parametrize("drives", [
    None, {}, [{**DRIVE, "path": "relative"}], [{**DRIVE, "path": "C:/private/file"}],
    [{**DRIVE, "path": "/mnt/../private"}], [{**DRIVE, "name": "bad\nname"}],
    [{**DRIVE, "kind": "invented"}], [{**DRIVE, "free_bytes": True}],
    [{**DRIVE, "free_bytes": -1}], [{**DRIVE, "free_bytes": 501}],
    [{**DRIVE, "owner": USER}], [DRIVE, {**DRIVE, "path": "c:\\"}],
])
def test_shared_inventory_rejects_unusable_metadata_without_echoing_paths(drives):
    with pytest.raises(DriveInventoryError) as caught:
        validate_drive_inventory(drives)
    assert "private" not in str(caught.value)


def test_report_persists_complete_snapshot_and_chat_reads_it_through_queue_proxy():
    async def run():
        app, db = app_and_db()
        link(db)
        before = datetime.now(timezone.utc)
        report = await post(app, {"device_id": DEVICE, "drives": [DRIVE, USB]})
        assert report.status_code == 200
        # Exercise the real authenticated internal/store HTTP handler and proxy.
        def factory(**kwargs):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)
        proxy = QueueBackedDriveStore(QueueStoreClient(
            origin="https://queue.invalid", service_secret=SERVICE, client_factory=factory))
        row = await proxy.load_drives(device_id=DEVICE)
        assert row["device_id"] == DEVICE and row["drives"] == [DRIVE, USB]
        assert before <= datetime.fromisoformat(row["received_at"].replace("Z", "+00:00"))
        assert report.json()["received_at"] == row["received_at"]
        # Removal replaces, rather than appends to, the previous full snapshot.
        assert (await post(app, {"device_id": DEVICE, "drives": [DRIVE]})).status_code == 200
        assert (await proxy.load_drives(device_id=DEVICE))["drives"] == [DRIVE]
        assert (await post(app, {"device_id": DEVICE, "drives": []})).status_code == 200
        assert (await proxy.load_drives(device_id=DEVICE))["drives"] == []
        assert await proxy.load_drives(device_id=OTHER) is None
        # A drive observation does not grant or rewrite any filesystem roots.
        assert db.execute("SELECT roots_json FROM pc_device_links").fetchone()[0] == "[]"
    asyncio.run(run())


@pytest.mark.parametrize("secret", [None, "incorrect", WATCH])
def test_report_requires_executor_channel_not_the_read_only_watch_secret(secret):
    async def run():
        app, db = app_and_db()
        link(db)
        response = await post(app, {"device_id": DEVICE, "drives": [DRIVE]}, channel=secret)
        assert response.status_code == 403
        assert db.execute("SELECT count(*) FROM mesh_device_drives").fetchone()[0] == 0
    asyncio.run(run())


@pytest.mark.parametrize("state,paused", [(None, None), ("revoked", None),
                                           ("pending_verification", None),
                                           ("active", "2026-11-01T00:00:00Z")])
def test_report_requires_an_active_unpaused_pairing(state, paused):
    async def run():
        app, db = app_and_db()
        if state:
            link(db, state=state, paused=paused)
        response = await post(app, {"device_id": DEVICE, "drives": [DRIVE]})
        assert response.status_code == 403
        assert db.execute("SELECT count(*) FROM mesh_device_drives").fetchone()[0] == 0
    asyncio.run(run())


@pytest.mark.parametrize("extra", [{"user_id": USER}, {"received_at": "2099-01-01T00:00:00Z"},
                                  {"credential_generation": 1}])
def test_report_refuses_payload_identity_or_receipt_time(extra):
    async def run():
        app, db = app_and_db()
        link(db)
        result = await post(app, {"device_id": DEVICE, "drives": [DRIVE], **extra})
        assert result.status_code == 400
        assert db.execute("SELECT count(*) FROM mesh_device_drives").fetchone()[0] == 0
    asyncio.run(run())


def test_target_list_contains_only_active_pcs_and_no_account_or_roots():
    async def run():
        app, db = app_and_db()
        link(db)
        link(db, user="usr_" + "b" * 32)  # Shared PC appears once.
        link(db, OTHER, paused="2026-11-01T00:00:00Z")
        link(db, "node//revoked-device", state="revoked")
        result = await post(app, {}, path=MESH_DEVICE_DRIVE_TARGETS_PATH)
        assert result.json() == {"ok": True, "device_ids": [DEVICE]}
        assert "no-store" in result.headers["cache-control"]
        assert (await post(app, {}, channel=WATCH,
                           path=MESH_DEVICE_DRIVE_TARGETS_PATH)).status_code == 403
        assert (await post(app, {"user_id": USER},
                           path=MESH_DEVICE_DRIVE_TARGETS_PATH)).status_code == 400
    asyncio.run(run())


def test_broken_inventory_store_is_unavailable_and_does_not_publish_metadata(capsys):
    async def run():
        app, db = app_and_db()
        link(db)
        db.execute("DROP TABLE mesh_device_drives")
        result = await post(app, {"device_id": DEVICE, "drives": [DRIVE]})
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "mesh_drives_unavailable"
        assert DRIVE["name"] not in result.text
    asyncio.run(run())
    captured = capsys.readouterr()
    assert CHANNEL not in captured.out + captured.err


def test_corrupt_stored_snapshot_is_unavailable_not_an_empty_inventory():
    async def run():
        app, db = app_and_db()
        db.execute("INSERT INTO mesh_device_drives VALUES (?,?,?)",
                   (DEVICE, json.dumps([{"path": "C:/"}]), "2026-11-01T00:00:00Z"))
        with pytest.raises(MeshDeviceDriveStoreError):
            await app.state.mesh_device_drive_store.load_drives(device_id=DEVICE)
    asyncio.run(run())
