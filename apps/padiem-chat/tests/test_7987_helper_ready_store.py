"""#7987 — helper readiness is really stored and read in BOTH deployment shapes.

#7990 taught the lesson this file encodes: a read that only worked on the local
database object went silent on the queue-backed one, because it reached for a
private method the queue proxy does not forward. Here the same public calls are
exercised on the object ``build_app`` actually wires in each shape:

* local store: the host's own SQLite file (``D1MeshDeviceDriveStore``);
* queue store: the queue service through its authenticated internal door
  (``QueueBackedDriveStore``), with the real queue app answering in-process.

No operating secret, address, account or PC is used.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[3]
QUEUE = ROOT / "apps" / "padiem-mesh-queue"
sys.path.insert(0, str(QUEUE))

import app.local_cpython as local_cpython  # noqa: E402
from app.mesh_device_drive_store import D1MeshDeviceDriveStore  # noqa: E402
from app.mesh_device_helper_ready_routes import (  # noqa: E402
    MESH_DEVICE_HELPER_READY_PATH, mesh_device_helper_ready_report,
)
from app.oracle_mesh_read_return_routes import (  # noqa: E402
    RETIRED_OWNERSHIP_MAP, build_oracle_mesh_return_source,
)
from app.queue_store_proxy import QUEUE_DRIVE_METHODS, QueueBackedDriveStore  # noqa: E402

CHANNEL = "synthetic-helper-channel-secret"
SERVICE = "synthetic-helper-service-secret"
DEVICE = "node//synthetic-helper-pc"
OTHER = "node//synthetic-other-pc"
USER = "usr_" + "a" * 32
READY = {"task_present": True, "install_dir_present": True, "pipe_open": True,
         "interactive_session": True, "helper_build": "9f2acb5916c0"}
MISSING = {"task_present": False, "install_dir_present": False, "pipe_open": False,
           "interactive_session": True, "helper_build": None}
PUBLIC_CALLS = ("upsert_helper_ready", "load_helper_ready")
LINK_SQL = ("INSERT INTO pc_device_links (link_id,user_id,mesh_node_id,state,roots_json,"
            "created_at,updated_at,paused_at) VALUES (?,?,?,?,?,?,?,?)")
LINK_ROW = ("link-" + DEVICE, USER, DEVICE, "active", "[]",
            "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z", None)


def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(("PADIEM_", "PC_QUEUE_")):
            monkeypatch.delenv(name)


def _local_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch)
    for name, value in {
        "PADIEM_LOCAL_DEV": "1", "PADIEM_CHAT_RUNTIME_MODE": "mock",
        "PADIEM_CHAT_AUTH_MODE": "off", "PADIEM_CHAT_WEB_PROVIDER": "off",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "http://127.0.0.1:8773",
        "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path),
        "PADIEM_CHAT_SESSION_SECRET": "test-local-secret-0123456789abcdef",
    }.items():
        monkeypatch.setenv(name, value)


def _queue_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate(monkeypatch)
    for name, value in {
        "PADIEM_CHAT_CPYTHON_HOST": "1", "PADIEM_CHAT_RUNTIME_MODE": "mock",
        "PADIEM_CHAT_AUTH_MODE": "off", "PADIEM_CHAT_WEB_PROVIDER": "off",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat-com2-staging.padiem.net",
        "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path),
        "PADIEM_CHAT_SESSION_SECRET": "test-local-secret-0123456789abcdef",
        "PC_QUEUE_BACKEND": "com2", "PC_QUEUE_ORIGIN": "http://127.0.0.1:8830",
        "PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP": "1", "PC_QUEUE_SERVICE_SECRET": SERVICE,
    }.items():
        monkeypatch.setenv(name, value)


def _queue_module(name: str):
    """Load a mesh-queue module by path under a unique name (see #7109 follow-up)."""
    unique = "mesh_queue_%s_helper_ready_7987" % name
    module = sys.modules.get(unique)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(unique, QUEUE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(unique, None)
        raise
    return module


def _queue_app():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    _queue_module("schema").apply(connection)
    connection.execute(LINK_SQL, LINK_ROW)
    app = _queue_module("service").create_app(
        connection=connection, channel_secret=CHANNEL, service_secret=SERVICE,
        legacy_map_lane=False)
    return app, connection


async def _post(app, body, *, channel=CHANNEL):
    headers = {} if channel is None else {"X-Oracle-Mesh-Secret": channel}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="http://queue.invalid") as client:
        return await client.post(MESH_DEVICE_HELPER_READY_PATH, json=body, headers=headers)


def _report_door(chat_app) -> Starlette:
    """The report route on the stores a built Chat app wired, with a channel source."""
    door = Starlette(routes=[Route(MESH_DEVICE_HELPER_READY_PATH,
                                   mesh_device_helper_ready_report, methods=["POST"])])
    door.state.pc_device_pairing_store = chat_app.state.pc_device_pairing_store
    door.state.mesh_device_drive_store = chat_app.state.mesh_device_drive_store
    door.state.oracle_mesh_return_source = build_oracle_mesh_return_source(
        list(RETIRED_OWNERSHIP_MAP), CHANNEL, "mesh", None)
    assert door.state.oracle_mesh_return_source is not None
    return door


def test_both_store_shapes_expose_the_same_public_calls():
    for cls in (D1MeshDeviceDriveStore, QueueBackedDriveStore):
        for name in PUBLIC_CALLS:
            # Defined on the class itself: nothing depends on __getattr__ forwarding
            # or on a name that starts with an underscore.
            assert name in vars(cls) and not name.startswith("_"), (cls.__name__, name)
    assert set(PUBLIC_CALLS) <= QUEUE_DRIVE_METHODS


def test_local_store_shape_stores_and_reads_on_the_object_build_app_wired(tmp_path, monkeypatch):
    _local_env(monkeypatch, tmp_path)
    chat = local_cpython.build_app()
    store = chat.state.mesh_device_drive_store
    assert isinstance(store, D1MeshDeviceDriveStore)

    async def run():
        # The host's own migration ledger created the table; nothing was hand-made here.
        assert await store.load_helper_ready(device_id=DEVICE) is None
        await store.db.prepare(LINK_SQL).bind(*LINK_ROW).run()
        door = _report_door(chat)
        before = datetime.now(timezone.utc)
        answer = await _post(door, {"device_id": DEVICE, "helper": MISSING})
        assert answer.status_code == 200
        row = await store.load_helper_ready(device_id=DEVICE)
        assert row == {"device_id": DEVICE, "state": MISSING,
                       "received_at": answer.json()["received_at"]}
        assert before <= datetime.fromisoformat(row["received_at"].replace("Z", "+00:00"))
        # The helper came up.
        assert (await _post(door, {"device_id": DEVICE, "helper": READY})).status_code == 200
        assert (await store.load_helper_ready(device_id=DEVICE))["state"] == READY
        # A PC this host has no active link for is refused and never stored.
        refused = await _post(door, {"device_id": OTHER, "helper": READY})
        assert refused.status_code == 403
        assert await store.load_helper_ready(device_id=OTHER) is None
        for secret in (None, "incorrect", SERVICE):
            assert (await _post(door, {"device_id": DEVICE, "helper": MISSING},
                                channel=secret)).status_code == 403
        assert (await store.load_helper_ready(device_id=DEVICE))["state"] == READY
        assert (await _post(door, {"device_id": DEVICE, "helper": {**READY, "user": "PRIVATE"}}
                            )).status_code == 400

    asyncio.run(run())


def test_queue_store_shape_stores_and_reads_on_the_object_build_app_wired(tmp_path, monkeypatch):
    _queue_env(monkeypatch, tmp_path)
    chat = local_cpython.build_app()
    store = chat.state.mesh_device_drive_store
    assert isinstance(store, QueueBackedDriveStore)
    queue, connection = _queue_app()
    # The one network seam: the pooled client is replaced by an in-process transport,
    # so every call below still goes through the real authenticated store door.
    chat.state.queue_client._client_factory = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=queue), **kwargs)

    async def run():
        assert await store.load_helper_ready(device_id=DEVICE) is None
        # The executor's report lands on the queue service, as it does in operation.
        answer = await _post(queue, {"device_id": DEVICE, "helper": MISSING})
        assert answer.status_code == 200
        row = await store.load_helper_ready(device_id=DEVICE)
        assert row == {"device_id": DEVICE, "state": MISSING,
                       "received_at": answer.json()["received_at"]}
        assert (await _post(queue, {"device_id": DEVICE, "helper": READY})).status_code == 200
        assert (await store.load_helper_ready(device_id=DEVICE))["state"] == READY
        # The Chat host can write through the same door with a real instant.
        moment = datetime(2026, 11, 18, 14, 0, 0, tzinfo=timezone.utc)
        assert await store.upsert_helper_ready(
            device_id=DEVICE, state=MISSING, received_at=moment) is True
        assert (await store.load_helper_ready(device_id=DEVICE))["state"] == MISSING
        assert (await _post(queue, {"device_id": OTHER, "helper": READY})).status_code == 403
        assert await store.load_helper_ready(device_id=OTHER) is None

    asyncio.run(run())
    assert connection.execute(
        "SELECT count(*) FROM mesh_device_helper_ready").fetchone()[0] == 1
    connection.close()


def test_the_cloud_worker_shape_wires_no_drive_store_so_readiness_is_simply_unknown():
    # The Worker entry keeps the pairing and presence stores only; the drive store
    # (and with it this observation) exists on the host shapes above.
    worker = (ROOT / "apps" / "padiem-chat" / "worker.py").read_text(encoding="utf-8")
    assert "mesh_device_drive_store" not in worker
