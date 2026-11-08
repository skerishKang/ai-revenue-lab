"""Managed(contract) PC mark route and SYSTEM audit (2026-11-08 decision).

The route, the real pairing store over migrated SQLite and the MCP audit store
are real. Only the administrator verdict is a stand-in, because the platform
role table is provisioned per deployment.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing  # noqa: E402

from app.mcp_gateway_store import D1McpGatewayStore  # noqa: E402
from app.pc_device_pairing_routes import (  # noqa: E402
    PC_PAIRING_MANAGED_PATH,
    PC_PAIRING_PATH,
)
from app.pc_device_pairing_store import D1PcPairingStore  # noqa: E402


class _Admin:
    def __init__(self, *, admin: bool) -> None:
        self.admin = admin

    async def is_global_model_admin(self, *, user_id: str) -> bool:
        return bool(self.admin and user_id == pairing.OWNER)


def _app(conn, *, admin: bool):
    app = pairing.app_with(D1PcPairingStore(pairing.RealSQLiteD1(conn)))
    app.state.central_model_admin_authorizer = _Admin(admin=admin)
    return app


def _url(link_id: str) -> str:
    return PC_PAIRING_MANAGED_PATH.replace("{link_id}", link_id)


async def _adopt(store):
    return await store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=pairing.NODE,
        root_paths=[], now=pairing._now(),
    )


def test_admin_marks_and_unmarks_one_link() -> None:
    async def journey():
        conn = pairing.database()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        app = _app(conn, admin=True)
        async with pairing.client(app) as session:
            marked = await session.post(_url(link["link_id"]), json={"managed": True})
            assert marked.status_code == 200, marked.text
            body = marked.json()
            assert body["ok"] is True
            assert body["link"]["managed"] is True
            assert body["link"]["managed_at"]
            assert await store.is_managed_link(
                user_id=pairing.OWNER, mesh_node_id=pairing.NODE) is True
            unmarked = await session.post(_url(link["link_id"]), json={"managed": False})
        assert unmarked.status_code == 200, unmarked.text
        assert unmarked.json()["link"]["managed"] is False
        assert await store.is_managed_link(
            user_id=pairing.OWNER, mesh_node_id=pairing.NODE) is False
    pairing.run(journey())


def test_non_admin_is_refused_before_the_link_is_read() -> None:
    messages: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    async def journey():
        conn = pairing.database()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        app = _app(conn, admin=False)
        logger = logging.getLogger("padiem_chat.request")
        handler = _Capture()
        logger.addHandler(handler)
        try:
            async with pairing.client(app) as session:
                refused = await session.post(_url(link["link_id"]), json={"managed": True})
        finally:
            logger.removeHandler(handler)
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "pc_pairing_managed_not_admin"
        assert await store.is_managed_link(
            user_id=pairing.OWNER, mesh_node_id=pairing.NODE) is False
    pairing.run(journey())
    assert any("pc_link_managed" in message and "denied" in message for message in messages)


def test_body_must_be_a_boolean_managed_flag() -> None:
    async def journey():
        conn = pairing.database()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        app = _app(conn, admin=True)
        async with pairing.client(app) as session:
            bad = await session.post(_url(link["link_id"]), json={"managed": "yes"})
            extra = await session.post(
                _url(link["link_id"]), json={"managed": True, "extra": 1})
        assert bad.status_code == 400
        assert bad.json()["error"]["code"] == "pc_pairing_body_invalid"
        assert extra.status_code == 400
    pairing.run(journey())


def test_unknown_link_is_404_and_revoked_link_is_409() -> None:
    async def journey():
        conn = pairing.database()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        app = _app(conn, admin=True)
        async with pairing.client(app) as session:
            missing = await session.post(
                _url("pclink_" + "0" * 32), json={"managed": True})
            await store.revoke_link(
                user_id=pairing.OWNER, link_id=link["link_id"], now=pairing._now())
            revoked = await session.post(_url(link["link_id"]), json={"managed": True})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "pc_pairing_link_not_found"
        assert revoked.status_code == 409
        assert revoked.json()["error"]["code"] == "pc_pairing_link_not_active"
    pairing.run(journey())


def test_mcp_audit_stores_command_bytes_and_never_the_body() -> None:
    async def journey():
        conn = pairing.database()
        conn.execute("PRAGMA foreign_keys=OFF")
        store = D1McpGatewayStore(pairing.RealSQLiteD1(conn))
        await store.audit(
            identity={"user_id": pairing.OWNER, "device_id": pairing.NODE,
                      "token_id": "mcp_" + "d" * 32},
            tool_name="pc_shell",
            arguments={"command": "whoami", "mode": "system"},
            status="denied",
            command_bytes=6,
        )
        row = conn.execute(
            "SELECT command_bytes, request_digest, status FROM padiem_mcp_audit"
        ).fetchone()
        assert row["command_bytes"] == 6
        assert row["status"] == "denied"
        assert row["request_digest"]
        dump = " ".join(str(value) for value in conn.execute(
            "SELECT * FROM padiem_mcp_audit").fetchone())
        assert "whoami" not in dump
    pairing.run(journey())



def _database_without_103() -> sqlite3.Connection:
    """Every migration except 103: the queue's own schema stops at 102."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    for path in sorted(pairing.MIGRATIONS.glob("*.sql")):
        if path.name.startswith("103"):
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
    return conn


def test_existing_link_reads_work_without_migration_103() -> None:
    async def journey():
        conn = _database_without_103()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        listed = await store.list_links(user_id=pairing.OWNER)
        assert [row["link_id"] for row in listed] == [link["link_id"]]
        assert "managed" not in listed[0]
        read = await store._read_link(pairing.OWNER, link["link_id"])
        assert read is not None and "managed_at" not in read
        assert await store.is_managed_link(
            user_id=pairing.OWNER, mesh_node_id=pairing.NODE) is False
    pairing.run(journey())


def test_set_managed_without_migration_103_is_503() -> None:
    async def journey():
        conn = _database_without_103()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        app = _app(conn, admin=True)
        async with pairing.client(app) as session:
            refused = await session.post(_url(link["link_id"]), json={"managed": True})
        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == "pc_pairing_not_ready"
        assert await store.is_managed_link(
            user_id=pairing.OWNER, mesh_node_id=pairing.NODE) is False
    pairing.run(journey())


def test_mcp_audit_records_without_command_bytes_column() -> None:
    async def journey():
        conn = _database_without_103()
        conn.execute("PRAGMA foreign_keys=OFF")
        store = D1McpGatewayStore(pairing.RealSQLiteD1(conn))
        await store.audit(
            identity={"user_id": pairing.OWNER, "device_id": pairing.NODE,
                      "token_id": "mcp_" + "d" * 32},
            tool_name="pc_shell",
            arguments={"command": "whoami", "mode": "system"},
            status="denied",
            command_bytes=6,
        )
        row = conn.execute(
            "SELECT status, request_digest FROM padiem_mcp_audit"
        ).fetchone()
        assert row["status"] == "denied"
        assert row["request_digest"]
        columns = {item[1] for item in conn.execute(
            "PRAGMA table_info(padiem_mcp_audit)").fetchall()}
        assert "command_bytes" not in columns
        dump = " ".join(str(value) for value in conn.execute(
            "SELECT * FROM padiem_mcp_audit").fetchone())
        assert "whoami" not in dump
    pairing.run(journey())


def test_admin_reads_the_managed_state() -> None:
    async def journey():
        conn = pairing.database()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        app = _app(conn, admin=True)
        async with pairing.client(app) as session:
            await session.post(_url(link["link_id"]), json={"managed": True})
            marked = await session.get(_url(link["link_id"]))
            assert marked.status_code == 200, marked.text
            assert marked.json() == {"ok": True, "link_id": link["link_id"], "managed": True}
            await session.post(_url(link["link_id"]), json={"managed": False})
            unmarked = await session.get(_url(link["link_id"]))
            assert unmarked.status_code == 200
            assert unmarked.json() == {"ok": True, "link_id": link["link_id"], "managed": False}
    pairing.run(journey())


def test_managed_state_refuses_non_admin() -> None:
    async def journey():
        conn = pairing.database()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        app = _app(conn, admin=True)
        async with pairing.client(app) as session:
            await session.post(_url(link["link_id"]), json={"managed": True})
        others = _app(conn, admin=False)
        async with pairing.client(others) as session:
            refused = await session.get(_url(link["link_id"]))
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "pc_pairing_managed_not_admin"
    pairing.run(journey())


def test_managed_state_unknown_link_is_404() -> None:
    async def journey():
        conn = pairing.database()
        app = _app(conn, admin=True)
        async with pairing.client(app) as session:
            missing = await session.get(_url("pclink_" + "0" * 32))
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "pc_pairing_link_not_found"
    pairing.run(journey())


def test_managed_state_without_migration_103_is_503() -> None:
    async def journey():
        conn = _database_without_103()
        store = D1PcPairingStore(pairing.RealSQLiteD1(conn))
        link = await _adopt(store)
        app = _app(conn, admin=True)
        async with pairing.client(app) as session:
            not_ready = await session.get(_url(link["link_id"]))
        assert not_ready.status_code == 503
        assert not_ready.json()["error"]["code"] == "pc_pairing_not_ready"
    pairing.run(journey())


def test_pairings_list_carries_the_admin_flag() -> None:
    async def journey():
        conn = pairing.database()
        admin_app = _app(conn, admin=True)
        async with pairing.client(admin_app) as session:
            seen = await session.get(PC_PAIRING_PATH)
        assert seen.status_code == 200
        assert seen.json()["admin"] is True
        others = _app(conn, admin=False)
        async with pairing.client(others) as session:
            denied = await session.get(PC_PAIRING_PATH)
        assert denied.status_code == 200
        assert denied.json()["admin"] is False
    pairing.run(journey())
