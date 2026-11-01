"""Actual session-owner API envelopes render and refresh the existing selector."""
import json
import subprocess
from pathlib import Path

from test_4139_claw_device_directory_route import get, make_app
from test_pc_drive_inventory_directory import DISK, USB, Drives, snapshot


def test_owner_api_inventory_reaches_real_selector_dom_through_add_remove_empty_and_failure():
    class Pairings:
        async def links_for_owner(self, *, user_id):
            return [{"mesh_node_id": "node//office", "label": "내 PC"}]

    app, settings = make_app()
    app.state.pc_device_pairing_store = Pairings()
    store = Drives({})
    app.state.mesh_device_drive_store = store
    responses = []
    for value in [snapshot("node//office", [DISK]), snapshot("node//office", [DISK, USB]),
                  snapshot("node//office", [DISK]), snapshot("node//office", []),
                  None, RuntimeError("PRIVATE_DETAIL")]:
        store.snapshots["node//office"] = value
        response = get(app, settings)
        assert response.status_code == 200
        responses.append(response.json())
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("pc_drive_inventory_ui_harness.cjs"))],
        input=json.dumps({"responses": responses}), capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == {"ok": True, "reads": 13}
