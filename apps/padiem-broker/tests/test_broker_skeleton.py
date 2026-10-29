"""padiem-broker skeleton: storage CAS and the proof-gated RPC door (#5573 A3/C).

No Cloudflare call, no network: an in-process ASGI client, an in-memory SQLite
storage for the CAS/transaction contract, and a temporary file DB for the
service composition (WAL is part of the contract under test).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

import storage as broker_storage
import service as broker_service

SECRET = "broker-rpc-ingress-secret-0123456789"
PEPPER = "broker-pepper-0123456789abcdef0123456789"
AUTHORITY = "control-plane.local-agent-broker.skeleton-test.v1"
ACCOUNT = "usr_" + "a" * 32
WORKSPACE = "ws.skeleton.1"
BINDING = "bind.skeleton.1"
DEVICE = "device.skeleton.1"
CREDENTIAL = b"skeleton-device-credential-bytes"


def _proof(path: str, body: bytes, *, at: int | None = None) -> dict[str, str]:
    at = int(time.time()) if at is None else at
    signed = b"\n".join((b"v1", b"POST", path.encode(), str(at).encode(), body))
    digest = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return {"x-padiem-service-at": str(at), "x-padiem-service-proof": "v1=" + digest}


def _environ(tmp_path: Path) -> dict[str, str]:
    return {
        "LOCAL_AGENT_BROKER_RPC_INGRESS": "1",
        "PADIEM_BROKER_RPC_INGRESS_SECRET": SECRET,
        "LOCAL_AGENT_BROKER_PEPPER": PEPPER,
        "LOCAL_AGENT_BROKER_AUTHORITY_REF": AUTHORITY,
        "PADIEM_BROKER_DB_PATH": str(tmp_path / "broker.sqlite3"),
    }


async def _rpc(client: httpx.AsyncClient, method: str, payload: dict):
    body = json.dumps(payload, separators=(",", ":")).encode()
    path = f"/internal/rpc/{method}"
    return await client.post(path, content=body, headers={
        "content-type": "application/json", **_proof(path, body),
    })


def test_storage_cas_and_transaction_contract():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    storage = broker_storage.SqLiteDurableStorage(connection)
    storage.sql.exec(
        "CREATE TABLE t (id TEXT PRIMARY KEY, version INTEGER NOT NULL)"
    )
    result = storage.sql.exec("INSERT INTO t (id, version) VALUES (?, ?)", "a", 1)
    assert result.rowsWritten == 1
    assert storage.sql.exec("SELECT * FROM t").toArray() == [{"id": "a", "version": 1}]

    # A rolled-back transaction leaves no trace, the DO transactionSync stance.
    with pytest.raises(RuntimeError):
        def fail():
            storage.sql.exec("UPDATE t SET version = version + 1 WHERE id = ?", "a")
            raise RuntimeError("boom")
        storage.transactionSync(fail)
    assert storage.sql.exec("SELECT version FROM t").toArray() == [{"version": 1}]

    # A conditional CAS loser reports zero written rows.
    loser = storage.sql.exec(
        "UPDATE t SET version = version + 1 WHERE id = ? AND version = ?", "a", 99
    )
    assert loser.rowsWritten == 0


@pytest.fixture()
def broker_app(tmp_path):
    app = broker_service.build_app(environ=_environ(tmp_path))
    yield app
    app.state.broker_storage.close()


@pytest.mark.asyncio
async def test_health_and_proof_gate(broker_app):
    transport = httpx.ASGITransport(app=broker_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://broker.local") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        # No proof, stale proof, unknown method, unpaved path.
        denied = await client.post(
            "/internal/rpc/open_session", content=b"{}",
            headers={"content-type": "application/json"},
        )
        assert denied.status_code == 403

        path = "/internal/rpc/open_session"
        body = b"{}"
        stale = await client.post(path, content=body, headers={
            "content-type": "application/json",
            **_proof(path, body, at=int(time.time()) - 3600),
        })
        assert stale.status_code == 403

        unknown = await _rpc(client, "create_tenant", {})
        assert unknown.status_code == 404
        not_ours = await client.post(
            "/internal/store", content=b"{}", headers={"content-type": "application/json"},
        )
        assert not_ours.status_code == 404


@pytest.mark.asyncio
async def test_session_lifecycle_over_the_proof_door(broker_app):
    broker = broker_app.state.broker
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    seeded = broker._runtime.register_binding({
        "binding_ref": BINDING, "device_id": DEVICE,
        "account_ref": ACCOUNT, "workspace_ref": WORKSPACE,
        "credential_b64": base64.b64encode(CREDENTIAL).decode(),
        "now": now,
    })
    assert seeded["ok"] is True

    transport = httpx.ASGITransport(app=broker_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://broker.local") as client:
        opened = await _rpc(client, "open_session", {
            "session_id": "sess.skeleton.1", "binding_ref": BINDING,
            "credential_b64": base64.b64encode(CREDENTIAL).decode(),
            "account_ref": ACCOUNT, "workspace_ref": WORKSPACE, "now": now,
        })
        assert opened.status_code == 200, opened.text
        opened_body = opened.json()
        assert opened_body["ok"] is True
        # No raw credential or credential payload comes back — only the
        # generation counter and boolean flags the canonical projection has.
        assert base64.b64encode(CREDENTIAL).decode() not in opened.text
        assert "credential_b64" not in opened.text
        assert opened_body["session"]["raw_session_secret"] is False

        authenticated = await _rpc(client, "authenticate_device_session", {
            "session_id": "sess.skeleton.1", "binding_ref": BINDING,
            "credential_b64": base64.b64encode(CREDENTIAL).decode(),
        })
        assert authenticated.status_code == 200
        assert authenticated.json()["ok"] is True
        assert authenticated.json()["device_session"]["account_ref"] == ACCOUNT

        denied = await _rpc(client, "authenticate_device_session", {
            "session_id": "sess.skeleton.1", "binding_ref": BINDING,
            "credential_b64": base64.b64encode(b"wrong").decode(),
        })
        assert denied.status_code == 200
        assert denied.json() == {
            "ok": False,
            "error": {"code": "device_session_auth_failed",
                      "message": denied.json()["error"]["message"]},
        }
        assert b"wrong" not in denied.content.lower()

        revoked = await _rpc(client, "revoke_binding", {"binding_ref": BINDING, "now": now})
        assert revoked.status_code == 200 and revoked.json()["ok"] is True
        after = await _rpc(client, "authenticate_device_session", {
            "session_id": "sess.skeleton.1", "binding_ref": BINDING,
            "credential_b64": base64.b64encode(CREDENTIAL).decode(),
        })
        assert after.json()["ok"] is False


def test_service_refuses_to_boot_without_secret_or_pepper(tmp_path):
    missing_secret = _environ(tmp_path)
    missing_secret["PADIEM_BROKER_RPC_INGRESS_SECRET"] = ""
    with pytest.raises(broker_service.BrokerConfigError):
        broker_service.build_app(environ=missing_secret)

    missing_pepper = _environ(tmp_path)
    missing_pepper["LOCAL_AGENT_BROKER_PEPPER"] = ""
    with pytest.raises(broker_service.BrokerConfigError):
        broker_service.build_app(environ=missing_pepper)

    short = _environ(tmp_path)
    short["PADIEM_BROKER_RPC_INGRESS_SECRET"] = "short"
    with pytest.raises(broker_service.BrokerConfigError):
        broker_service.build_app(environ=short)
