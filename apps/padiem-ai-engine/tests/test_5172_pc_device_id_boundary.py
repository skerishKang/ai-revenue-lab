"""#5172: the Engine plan and tool boundaries keep the same PC identity.

The device identity is decided by the server and the Broker directory. The
Engine must not re-interpret it: the plan arguments, the tool arguments and
the signed dispatch all have to carry the exact value the directory proved,
including the composed MeshCentral form ``node/<domain>/<node-id>``.

A path-like identity stays refused at every one of those boundaries.
"""
from __future__ import annotations

import pytest

from app.claw_pc_query_step_driver import _selected_device_id
from app.orchestration_service import _pc_query_selected_device
from padiem_ai_core.tool_runtime import ToolHandlerError

#: The real MeshCentral node reference and its composed identity.
BARE_NODE_REF = "Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4" + "@" + "meshdomain1"
MESH_NODE_ID = "node//" + BARE_NODE_REF


@pytest.mark.parametrize("device_id", [MESH_NODE_ID, BARE_NODE_REF, "office-pc"])
def test_the_tool_argument_boundary_keeps_the_device_identity(device_id: str):
    assert _selected_device_id({"device_id": device_id}) == device_id


@pytest.mark.parametrize("device_id", [MESH_NODE_ID, BARE_NODE_REF, "office-pc"])
def test_the_plan_argument_boundary_keeps_the_device_identity(device_id: str):
    assert _pc_query_selected_device(
        {"query_drives": {"device_id": device_id}},
    ) == device_id
    assert _pc_query_selected_device(
        {"files": {"device_id": device_id}},
    ) == device_id


@pytest.mark.parametrize(
    "device_id",
    [
        "../../etc/passwd",
        "node/a/b/c",
        "https://example.test",
        "node//a b",
        "",
    ],
)
def test_a_path_like_device_identity_is_refused(device_id: str):
    with pytest.raises(ToolHandlerError):
        _selected_device_id({"device_id": device_id})
    assert _pc_query_selected_device({"query_drives": {"device_id": device_id}}) is None
    assert _pc_query_selected_device({"files": {"device_id": device_id}}) is None


def test_the_plan_boundary_accepts_no_other_argument():
    """The PC target stays the only argument the plan may carry."""
    with pytest.raises(ToolHandlerError):
        _selected_device_id({"device_id": MESH_NODE_ID, "path": "C:/"})
    with pytest.raises(ToolHandlerError):
        _selected_device_id({"device": MESH_NODE_ID})


def test_drives_schema_uses_canonical_bare_device_pattern():
    from kagent.pc_query_adapter import pc_drives_tool_spec
    from padiem_ai_core.pc_device_identity import PC_DEVICE_ID_PATTERN
    assert pc_drives_tool_spec().input_schema["properties"]["device_id"]["pattern"] == PC_DEVICE_ID_PATTERN
