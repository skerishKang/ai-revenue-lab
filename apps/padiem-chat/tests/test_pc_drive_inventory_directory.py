"""Read-only Mesh drive snapshots join only the session owner's PC list."""
from copy import deepcopy

import pytest

from test_4139_claw_device_directory_route import Binding, OWNER, fact, get, make_app
from test_4139_claw_device_directory_projection import online, project


STAMP = "2026-11-01T01:02:03+00:00"
DISK = {"path": "C:/", "name": "Windows", "kind": "fixed",
        "free_bytes": 128 * 1024**3, "total_bytes": 256 * 1024**3}
USB = {"path": "E:/", "name": "USB", "kind": "removable",
       "free_bytes": None, "total_bytes": None}


class Drives:
    def __init__(self, snapshots):
        self.snapshots, self.calls = snapshots, []

    async def load_drives(self, *, device_id):
        self.calls.append(device_id)
        result = self.snapshots.get(device_id)
        if isinstance(result, Exception):
            raise result
        return result


def snapshot(device="office", drives=None, **extra):
    return {"device_id": device, "drives": deepcopy([DISK] if drives is None else drives),
            "received_at": STAMP, **extra}


def test_mesh_owner_list_reads_latest_inventory_add_remove_and_empty_without_broker():
    class Pairings:
        async def links_for_owner(self, *, user_id):
            return [{"mesh_node_id": "node//office", "label": "내 PC"}] if user_id == OWNER else []

    app, settings = make_app()
    app.state.pc_device_pairing_store = Pairings()
    store = Drives({"node//office": snapshot("node//office")})
    app.state.mesh_device_drive_store = store
    responses = []
    for drives in ([DISK], [DISK, USB], [DISK], []):
        store.snapshots["node//office"] = snapshot("node//office", drives)
        response = get(app, settings)
        assert response.status_code == 200
        assert response.headers["cache-control"].startswith("no-store")
        row = response.json()["devices"][0]
        assert row["deviceId"] == "node//office"
        assert row["drives"] == drives
        assert row["drivesStatus"] == "ready"
        assert row["drivesUpdatedAt"] == STAMP
        responses.append(response.json())
    assert store.calls == ["node//office"] * 4
    # Exercise the production browser projection on the API's actual envelope.
    assert project(responses[1])["devices"][0]["drives"] == [DISK, USB]
    assert project(responses[-1])["devices"][0]["drives"] == []


def test_inventory_never_enumerates_or_loads_another_owners_device():
    class Pairings:
        async def links_for_owner(self, *, user_id):
            own = "node//alice" if user_id == OWNER else "node//bob"
            return [{"mesh_node_id": own}]

    app, settings = make_app()
    app.state.pc_device_pairing_store = Pairings()
    store = Drives({"node//alice": snapshot("node//alice"),
                    "node//bob": snapshot("node//bob", [{**USB, "name": "BOB_PRIVATE"}])})
    app.state.mesh_device_drive_store = store
    alice = get(app, settings)
    assert "BOB_PRIVATE" not in alice.text
    assert store.calls == ["node//alice"]
    assert get(app, settings, query={"device_id": "node//bob"}).status_code == 400
    assert get(app, settings, signed=False).status_code == 401
    assert store.calls == ["node//alice"]
    bob = get(app, settings, user="usr_other")
    assert [row["deviceId"] for row in bob.json()["devices"]] == ["node//bob"]
    assert "Windows" not in bob.text
    assert store.calls == ["node//alice", "node//bob"]


def test_revoked_and_expired_devices_do_not_read_inventory():
    app, settings = make_app(Binding([fact("revoked", state="revoked"),
                                     fact("expired", state="credential_expired")]))
    store = Drives({device: snapshot(device) for device in ("revoked", "expired")})
    app.state.mesh_device_drive_store = store
    rows = get(app, settings).json()["devices"]
    assert len(rows) == 2
    assert store.calls == []
    assert all("drives" not in row for row in rows)


@pytest.mark.parametrize("value,status", [
    (None, "pending"),
    (RuntimeError("PRIVATE_STORE_DETAIL"), "unavailable"),
    (snapshot("different-owner-pc"), "unavailable"),
    (snapshot(received_at="invalid"), "unavailable"),
    (snapshot(received_at="2026-11-01T00:00:00"), "unavailable"),
    (snapshot(drives=[{**DISK, "free_bytes": -1}]), "unavailable"),
    (snapshot(drives=[DISK, DISK]), "unavailable"),
])
def test_missing_or_bad_inventory_does_not_hide_device_or_invent_empty_list(value, status):
    app, settings = make_app(Binding([fact("office")]))
    app.state.mesh_device_drive_store = Drives({"office": value})
    response = get(app, settings)
    payload = response.json()
    row = payload["devices"][0]
    assert row["deviceId"] == "office"
    assert row["drivesStatus"] == status
    assert "drives" not in row
    assert "PRIVATE_STORE_DETAIL" not in response.text


def test_api_and_browser_keep_closed_inventory_projection_without_new_execution_rights():
    app, settings = make_app(Binding([fact("office")]))
    app.state.mesh_device_drive_store = Drives({"office": snapshot(
        drives=[{**DISK, "credential": "PRIVATE_CREDENTIAL", "command": "PRIVATE_COMMAND"}],
        token="PRIVATE_TOKEN")})
    response = get(app, settings)
    payload = response.json()
    row = payload["devices"][0]
    assert row["drives"] == [DISK]
    assert "PRIVATE_" not in response.text
    row["drives"][0]["secret"] = "PRIVATE_BROWSER"
    projected = project(payload, "office")
    assert projected["devices"][0]["drives"] == [DISK]
    assert projected["canTarget"] is False  # inventory never makes an offline PC executable


@pytest.mark.parametrize("drives", [[{**DISK, "kind": "execute"}],
                                   [{**DISK, "free_bytes": True}],
                                   [{**DISK, "free_bytes": DISK["total_bytes"] + 1}],
                                   [DISK, DISK]])
def test_browser_rejects_malformed_inventory_without_hiding_verified_device(drives):
    result = project({"available": True, "ownerScoped": True, "devices": [online(
        drivesStatus="ready", drivesUpdatedAt=STAMP, drives=drives)]}, "office")
    assert result["canTarget"] is True
    assert result["devices"][0]["drivesStatus"] == "unavailable"
    assert "drives" not in result["devices"][0]
