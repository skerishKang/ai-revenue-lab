"""#5172: one PC device identity crosses the whole PC boundary unchanged.

The live failure this issue closes is a Mesh PC that exists and is
authorized, yet never appears in the device list:

    scopeStatus=ready
    brokerScope=connector
    targetStatus=ready
    devices=[]

The Mesh execution target resolved (``targetStatus=ready``) and the Broker
scope was ready, but the identity the deployment ownership map names - the
composed MeshCentral form ``node/<domain>/<node-id>`` - was refused by the
simple device-id grammar, so the row was dropped before it could be listed.

These tests pin the whole chain with that real identity: the directory lists
it, the browser selects it, the store saves and reads it back, a new
conversation restores it, the model work context projects it, and the Engine
and P01 plan boundaries accept the same string. A path-like identity stays
refused at every one of them.
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_device_directory_routes import (
    CLAW_DEVICE_DIRECTORY_PATH,
    CLAW_PC_SELECT_PATH,
    BrokerDeviceDirectorySource,
)
from app.config import Settings
from app.main import create_app
from app.pc_work_context import (
    SAVED_SELECTION_SELECTED,
    load_saved_device_selection,
    read_saved_device_selection,
    resolve_pc_work_context,
)
from padiem_ai_core.pc_device_identity import is_pc_device_id

OWNER = "usr_5172_test"
WORKSPACE = "owner:" + OWNER
CONNECTOR_ACCOUNT = "acct-5172"
CONNECTOR_WORKSPACE = "ws-connector"
BASE = "https://chat.example.test"

#: The bare MeshCentral node reference the deployment ownership map carries.
BARE_NODE_REF = "Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4" + "@" + "meshdomain1"
#: The composed identity MeshCentral itself builds, with the default domain.
MESH_NODE_ID = "node//" + BARE_NODE_REF

STATIC = Path(__file__).resolve().parents[1] / "static"


class Binding:
    def __init__(self, rows=None, *, available=True):
        self.rows = list(rows or [])
        self.available = available

    async def device_directory(self, payload):
        del payload
        if not self.available:
            return {"ok": True, "available": False, "reason": "no_device_binding"}
        return {
            "ok": True, "available": True, "owner_scoped": True,
            "device_count": len(self.rows), "devices": self.rows,
        }


class SelectionStore:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.saves = []

    async def load(self, *, owner_id, workspace_id):
        return self.rows.get((owner_id, workspace_id))

    async def save(self, *, owner_id, workspace_id, device_id, now):
        del now
        self.saves.append((owner_id, workspace_id, device_id))
        self.rows[(owner_id, workspace_id)] = device_id
        return True


class _MeshTarget:
    """Mirror of the deployment ownership map's command-capable row."""

    configured = True
    execution_mode = "mesh"

    def __init__(self, row):
        self.row = row

    def command_target(self, *, account_ref, device_id=None):
        del account_ref
        if device_id is not None and self.row.get("device_id") != device_id:
            return None
        return dict(self.row)


class _ScopeIdentity:
    async def resolve_connector_owner_scope(self, *, session_id):
        del session_id
        return {
            "account_ref": CONNECTOR_ACCOUNT,
            "workspace_ref": CONNECTOR_WORKSPACE,
        }


MESH_ROW = {
    "account_ref": CONNECTOR_ACCOUNT,
    "device_id": MESH_NODE_ID,
    "node_ref": BARE_NODE_REF,
    "command_exec": True,
}


def make_app(*, selection_store=None, mesh_row=None):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="5172-device-list-test-not-real-session-secret",
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings, history_store=MagicMock(),
        claw_device_directory_source=BrokerDeviceDirectorySource(
            Binding(available=False),
        ),
        claw_pc_device_selection_store=selection_store,
    )
    app.state.oracle_mesh_return_source = _MeshTarget(mesh_row or MESH_ROW)
    app.state.control_plane_identity_authority = _ScopeIdentity()
    return app, settings


@contextmanager
def _session_pair():
    subject = "subject-owner-5172"
    b62 = SimpleNamespace(
        session_id="sess-b62", subject=SimpleNamespace(subject_id=subject),
    )
    b54 = SimpleNamespace(
        session_id="sess-b54", tenant_id=WORKSPACE,
        subject=SimpleNamespace(subject_id=subject),
    )
    with (
        patch("app.pc_work_context._resolve_owner_session",
              new=AsyncMock(return_value=(WORKSPACE, b62))),
        patch(
            "padiem_control_plane.b54_identity_bridge."
            "resolve_current_b54_canonical_session",
            new=AsyncMock(return_value=SimpleNamespace(auth_session=b54)),
        ),
        patch("app.claw_device_directory_routes._resolve_memory_workspace",
              new=AsyncMock(return_value=WORKSPACE)),
    ):
        yield


def _get(app, settings):
    async def perform():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            client.cookies.set(
                SESSION_COOKIE, create_session_token(settings, OWNER),
                domain="chat.example.test", path="/",
            )
            return await client.get(CLAW_DEVICE_DIRECTORY_PATH)
    return asyncio.run(perform())


def _post_select(app, settings, body):
    async def perform():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            client.cookies.set(
                SESSION_COOKIE, create_session_token(settings, OWNER),
                domain="chat.example.test", path="/",
            )
            return await client.post(
                CLAW_PC_SELECT_PATH,
                headers={"Origin": BASE, "Content-Type": "application/json"},
                content=json.dumps(body, ensure_ascii=False),
            )
    return asyncio.run(perform())


# ── the device list ───────────────────────────────────────────────────────


def test_the_mesh_node_identity_is_listed_instead_of_being_dropped():
    """The exact live symptom: the Mesh target resolved but the list was empty."""
    app, settings = make_app()
    with _session_pair():
        data = _get(app, settings).json()
    assert data["available"] is True
    assert data["scopeStatus"] == "ready"
    assert data["brokerScope"] == "connector"
    assert data["targetStatus"] == "ready"
    assert [row["deviceId"] for row in data["devices"]] == [MESH_NODE_ID]
    row = data["devices"][0]
    assert row["executable"] is True
    assert row["selectable"] is True
    assert row["state"] == "ACTION_REQUIRED"


def test_the_bare_node_reference_is_listed_too():
    """An unpinned ownership row names the bare node reference as the PC."""
    app, settings = make_app(
        mesh_row={**MESH_ROW, "device_id": None},
    )
    with _session_pair():
        data = _get(app, settings).json()
    assert [row["deviceId"] for row in data["devices"]] == [BARE_NODE_REF]


def test_a_node_reference_carrying_a_dollar_is_listed_selected_and_read_back():
    """MeshCentral's own node alphabet puts ``$`` in real ids.

    A freshly installed PC is named by an id like this one, and the whole
    pairing chain runs on it: the presence beat that carries its tag, the claim
    that makes the link, the directory row the browser selects. Refusing the
    character did not narrow anything - it dropped the device, which is how a
    second PC installed on a real machine never appeared in any list.
    """
    dollar_ref = "O$SnVp94Lb7ltPM78IZukErNte93bqygxqDvjI1eVDck$tGY" + "@" + "meshdomain1"
    assert is_pc_device_id(dollar_ref) is True
    assert is_pc_device_id("node//" + dollar_ref) is True

    app, settings = make_app(
        mesh_row={**MESH_ROW, "device_id": dollar_ref, "node_ref": dollar_ref},
    )
    with _session_pair():
        data = _get(app, settings).json()
    assert [row["deviceId"] for row in data["devices"]] == [dollar_ref]
    assert data["devices"][0]["selectable"] is True

    store = SelectionStore()
    app, settings = make_app(
        mesh_row={**MESH_ROW, "device_id": dollar_ref, "node_ref": dollar_ref},
        selection_store=store,
    )
    with _session_pair():
        response = _post_select(app, settings, {"device_id": dollar_ref})
    assert response.status_code == 200, response.text
    assert store.saves == [(OWNER, WORKSPACE, dollar_ref)]


# ── selection, save and readback ──────────────────────────────────────────


def test_the_mesh_node_identity_is_selectable_and_saved():
    store = SelectionStore()
    app, settings = make_app(selection_store=store)
    with _session_pair():
        response = _post_select(app, settings, {"device_id": MESH_NODE_ID})
    assert response.status_code == 200, response.text
    assert response.json()["selectedDeviceId"] == MESH_NODE_ID
    assert store.saves == [(OWNER, WORKSPACE, MESH_NODE_ID)]


def test_the_saved_mesh_node_identity_is_read_back_unchanged():
    """A new conversation reads the same preference back, byte for byte."""
    store = SelectionStore({(OWNER, WORKSPACE): MESH_NODE_ID})
    app, settings = make_app(selection_store=store)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        claw_pc_device_selection_store=store,
    )))
    selection = asyncio.run(read_saved_device_selection(
        request, owner_id=OWNER, workspace_id=WORKSPACE,
    ))
    assert selection.status == SAVED_SELECTION_SELECTED
    assert selection.device_id == MESH_NODE_ID
    assert asyncio.run(load_saved_device_selection(
        request, owner_id=OWNER, workspace_id=WORKSPACE,
    )) == MESH_NODE_ID


def test_the_work_context_projects_the_same_mesh_node_identity():
    """The model sees exactly the identity the server proved."""
    app, _settings = make_app()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        claw_device_directory_source=None,
        oracle_mesh_return_source=_MeshTarget(MESH_ROW),
        control_plane_identity_authority=_ScopeIdentity(),
    )))
    with _session_pair():
        context = asyncio.run(resolve_pc_work_context(
            request, owner_id=OWNER, workspace_id=WORKSPACE,
            session_id="sess-b54", selected_device_id=MESH_NODE_ID,
        ))
    assert context.execution.status == "ready"
    assert context.execution.device_id == MESH_NODE_ID


# ── the other boundaries keep the same value ──────────────────────────────


def test_the_engine_client_accepts_the_same_identity():
    from padiem_ai_engine_client.client import _trusted_pc_tool_arguments

    plan = {
        "agent_id": "agent:padiem:claw-pc-query@1",
        "steps": [{"step_id": "query_drives", "tool_id": "claw.pc.query_drives"}],
    }
    assert _trusted_pc_tool_arguments(
        plan, {"query_drives": {"device_id": MESH_NODE_ID}},
    ) is True
    assert _trusted_pc_tool_arguments(
        plan, {"query_drives": {"device_id": BARE_NODE_REF}},
    ) is True
    assert _trusted_pc_tool_arguments(
        plan, {"query_drives": {"device_id": "../../etc/passwd"}},
    ) is False


def test_the_p01_plan_boundary_accepts_the_same_identity():
    from kagent.p01_orchestration_client import P01EngineOrchestrationClient

    client = P01EngineOrchestrationClient.__new__(P01EngineOrchestrationClient)
    client._allow_subject_identity = True
    request = SimpleNamespace(
        app_id="b54-padiem-claw",
        subject_id="usr_5172_test",
        execution_request=SimpleNamespace(session_id="sess-b54"),
        agent_plan=SimpleNamespace(
            agent_id="agent:padiem:claw-pc-query@1",
            steps=[SimpleNamespace(
                step_id="query_drives", tool_id="claw.pc.query_drives",
            )],
        ),
        tool_arguments={"query_drives": {"device_id": MESH_NODE_ID}},
    )
    assert client._is_trusted_pc_query_request(request) is True
    request.tool_arguments = {"query_drives": {"device_id": "../../etc/passwd"}}
    assert client._is_trusted_pc_query_request(request) is False


def test_the_browser_projection_pattern_matches_the_server_grammar():
    """The browser may project exactly what the server proved, nothing more."""
    source = (STATIC / "claw-local-handoff.js").read_text(encoding="utf-8")
    match = re.search(
        r"const DEVICE_ID_PATTERN = /(.*?)/;", source, re.S,
    )
    assert match is not None, "the browser device-id pattern must stay declared"
    browser = re.compile(match.group(1).replace("\\/", "/"))
    samples = [
        "device-1", BARE_NODE_REF, MESH_NODE_ID, "node/meshdomain1/abc",
        "", " ", "node/", "node//", "node/a/b/c", "https://example.test",
        "../../etc/passwd", "C:\\Windows\\System32", "node//a b",
    ]
    for value in samples:
        assert bool(browser.fullmatch(value)) is is_pc_device_id(value), value


@pytest.mark.parametrize(
    "value",
    ["../etc/passwd", "node/a/b/c", "https://example.test", "node//a b", ""],
)
def test_a_path_like_identity_is_refused_by_the_grammar(value: str):
    assert is_pc_device_id(value) is False
