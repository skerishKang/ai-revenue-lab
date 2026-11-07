"""Managed(contract) PC mark route and SYSTEM audit (2026-11-08 decision).

The route, the real pairing store over migrated SQLite and the MCP audit store
are real. Only the administrator verdict is a stand-in, because the platform
role table is provisioned per deployment.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing  # noqa: E402

from app.mcp_gateway_store import D1McpGatewayStore  # noqa: E402
from app.pc_device_pairing_routes import PC_PAIRING_MANAGED_PATH  # noqa: E402
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
