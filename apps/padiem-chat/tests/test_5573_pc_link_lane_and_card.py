"""#5573 PR-5: a linked PC runs on the Mesh lane, and the old desktop card stays down.

The Owner adopted their PC as an administrator, so the pairing directory holds an
active link for that account. Two things had to be true afterwards and one of them
was not, which is what the production read turned on:

* the file call runs on the Mesh PC lane, and the reference the Mesh client is run
  against stays the deployment's own answer for that device. An adopted link names
  a PC by the identity the ownership map pins it by, which is not a node reference
  and must never silently become one;
* the #3084 "connect this computer / install the desktop app" card is a projection
  about the machine the user is browsing on, so it is not raised for an account that
  already has a linked PC.

Each behaviour is tested in both directions: linked and not linked. The not-linked
half is the pre-existing map lane and the pre-existing card, unchanged.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from starlette.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).parent))

import test_5015_pc_read_dispatch as lane                     # noqa: E402
import test_5573_pc_device_pairing as pairing                 # noqa: E402

from app import claw_device_directory_routes as directory     # noqa: E402
from app import claw_local_access_routes as panel             # noqa: E402
from app import claw_memory_routes as memory                  # noqa: E402

# The panel's own evidence: a directory that shows one connected, executable PC.
CONNECTION = {
    "available": True, "ownerScoped": True,
    "devices": [{
        "deviceId": lane.DEVICE, "executable": True, "state": "CONNECTED",
        "usable": True, "revoked": False, "expired": False,
    }],
}


def _adopted_state(monkeypatch):
    """The production shape: an administrator-adopted link over the map's device."""
    store = pairing.store()
    adopted = pairing.run(store.adopt_link(
        user_id=lane.OWNER, mesh_node_id=lane.DEVICE, root_paths=[lane.ROOT],
        now=pairing._now(),
    ))
    assert adopted["state"] == "active" and len(adopted["roots"]) == 1
    state = lane._state(monkeypatch)
    state.pc_device_pairing_store = store
    return state, adopted


def _card(monkeypatch, state):
    """One real panel read, through the Mesh directory projection the lane uses."""
    async def read(request, **scope):
        assert scope == {"uid": lane.OWNER, "workspace_id": "ws"}
        return JSONResponse(CONNECTION)

    async def workspace(request, owner):
        assert owner == lane.OWNER
        return "ws"

    monkeypatch.setattr(directory, "_read_device_directory", read)
    monkeypatch.setattr(memory, "_resolve_memory_workspace", workspace)
    monkeypatch.setattr(panel, "auth_ready", lambda request: True)
    monkeypatch.setattr(panel, "current_user_id", lambda request: lane.OWNER)
    request = SimpleNamespace(
        query_params={"conversationId": "conv_5573_link"},
        app=SimpleNamespace(state=state),
    )
    return json.loads(asyncio.run(panel.claw_local_access(request)).body)


def test_a_linked_pc_runs_on_the_mesh_lane_and_raises_no_desktop_card(monkeypatch):
    state, adopted = _adopted_state(monkeypatch)

    status, body = lane._dispatch(state, lane._base_payload())
    assert status == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["kind"] == "command"
    # The link chose the PC and the folder; the deployment's own Mesh reference is
    # still what the command is run against.
    assert row["node_ref"] == lane.NODE
    assert row["device_id"] == adopted["mesh_node_id"] == lane.DEVICE
    assert lane.ROOT in row["command_text"]
    assert adopted["mesh_node_id"] not in row["command_text"]

    card = _card(monkeypatch, state)
    assert card["available"] is False
    assert card["projection"]["requiresLocalAccess"] is False


def test_an_unlinked_account_keeps_the_map_lane_and_its_existing_card(monkeypatch):
    state = lane._state(monkeypatch)
    state.pc_device_pairing_store = pairing.store()   # the directory answers "no PC"

    status, body = lane._dispatch(state, lane._base_payload())
    assert status == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["node_ref"] == lane.NODE and row["device_id"] == lane.DEVICE
    assert lane.ROOT in row["command_text"]

    card = _card(monkeypatch, state)
    assert card["available"] is True
    assert card["projection"]["requiresLocalAccess"] is True
