"""A changed PC inventory reaches the existing owner-only selector end to end.

Only the Mesh socket/device-event boundary is simulated. The reporter, channel
authentication, 086 SQLite table, queue RPC, Chat session API and browser modules
are production implementations. No live PC, Broker or service is contacted.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import httpx

QUEUE = Path(__file__).resolve().parents[1]
CHAT_TESTS = QUEUE.parent / "padiem-chat" / "tests"
sys.path.insert(0, str(CHAT_TESTS))

from test_mesh_device_drives import CHANNEL, SERVICE, USER, app_and_db, link, post
from test_4139_claw_device_directory_route import get, make_app
from test_pc_drive_inventory_directory import DISK, USB
from app.queue_store_proxy import QueueBackedDriveStore, QueueBackedPairingStore, QueueStoreClient
from kagent.local_agent_mesh_drive_reporter import DRIVES_PATH, MeshDriveReporter


ALICE_PC = "node//office"
BOB_PC = "node//bob"
BOB_USER = "usr_" + "b" * 32


def test_changed_drives_travel_from_mesh_reporter_to_queue_owner_api_and_real_selector():
    queue, db = app_and_db()
    link(db, ALICE_PC)
    link(db, BOB_PC, user=BOB_USER)
    assert "086_mesh_device_drives.sql" in {
        row[0] for row in db.execute("SELECT name FROM queue_schema_applied")
    }

    # A fake authenticated Mesh response has the same node-bound shape as the
    # source. Events and the 30-second fallback change these full snapshots.
    observed = {
        ALICE_PC: [deepcopy(DISK)],
        BOB_PC: [{**USB, "name": "BOB_PRIVATE_VOLUME"}],
    }
    source_targets, channel_calls = [], []

    def source(device_ids):
        source_targets.append(device_ids)
        return [{"device_id": device, "drives": deepcopy(observed[device])}
                for device in device_ids if device in observed]

    def channel(path, body):
        channel_calls.append((path, deepcopy(body)))
        response = asyncio.run(post(queue, body, channel=CHANNEL, path=path))
        return response.status_code, response.json()

    reporter = MeshDriveReporter(post=channel, source=source)

    def queue_client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=queue), **kwargs)

    client = QueueStoreClient(origin="https://queue.invalid", service_secret=SERVICE,
                              client_factory=queue_client_factory)
    chat, settings = make_app()  # No Broker binding: the production Mesh lane.
    chat.state.pc_device_pairing_store = QueueBackedPairingStore(client)
    chat.state.mesh_device_drive_store = QueueBackedDriveStore(client)

    def alice_directory():
        response = get(chat, settings, user=USER)
        assert response.status_code == 200
        assert "BOB_PRIVATE_VOLUME" not in response.text
        assert BOB_PC not in response.text
        result = response.json()
        assert [row["deviceId"] for row in result["devices"]] == [ALICE_PC]
        return result

    assert reporter.tick() == 2
    responses = [alice_directory()]
    assert responses[0]["devices"][0]["drives"] == [DISK]
    assert source_targets == [[BOB_PC, ALICE_PC]]
    assert reporter.tick() == 0  # An unchanged poll sends no duplicate report.
    assert len([call for call in channel_calls if call[0] == DRIVES_PATH]) == 2

    # The browser is not allowed to select another account's inventory by
    # query, and the other account sees only its own genuinely stored drives.
    assert get(chat, settings, signed=False).status_code == 401
    assert get(chat, settings, user=USER,
               query={"device_id": BOB_PC}).status_code == 400
    bob = get(chat, settings, user=BOB_USER)
    assert bob.status_code == 200
    assert [row["deviceId"] for row in bob.json()["devices"]] == [BOB_PC]
    assert "BOB_PRIVATE_VOLUME" in bob.text and "Windows" not in bob.text

    for drives in ([DISK, USB], [DISK], []):
        observed[ALICE_PC] = drives
        assert reporter.tick() == 1
        envelope = alice_directory()
        assert envelope["devices"][0]["drives"] == drives
        assert db.execute("SELECT drives_json FROM mesh_device_drives WHERE device_id=?",
                          (ALICE_PC,)).fetchone()[0] == json.dumps(
                              drives, ensure_ascii=False, separators=(",", ":"))
        responses.append(envelope)

    # A temporarily unreachable PC is not a report that all drives vanished.
    del observed[ALICE_PC]
    assert reporter.tick() == 0
    assert alice_directory()["devices"][0]["drivesStatus"] == "ready"
    # The inventory has never widened the account's existing filesystem roots.
    assert {row[0] for row in db.execute("SELECT roots_json FROM pc_device_links")} == {"[]"}

    # Also feed real pending/unavailable API responses to the shared DOM test.
    db.execute("DELETE FROM mesh_device_drives WHERE device_id=?", (ALICE_PC,))
    responses.append(alice_directory())
    assert responses[-1]["devices"][0]["drivesStatus"] == "pending"
    db.execute("DROP TABLE mesh_device_drives")
    responses.append(alice_directory())
    assert responses[-1]["devices"][0]["drivesStatus"] == "unavailable"

    rendered = subprocess.run(
        ["node", str(CHAT_TESTS / "pc_drive_inventory_ui_harness.cjs")],
        input=json.dumps({"responses": responses}), text=True,
        capture_output=True, check=True,
    )
    assert json.loads(rendered.stdout) == {"ok": True, "reads": 13}
    db.close()
