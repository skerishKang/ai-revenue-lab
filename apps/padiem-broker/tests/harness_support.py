"""Shared fixtures for the broker skeleton and its differential harness.

The proof helper signs exactly the #6149 v1 contract; payload builders create
canonical broker requests with a caller-supplied `now` where the RPC accepts
one, and the wall clock only where the broker itself decides (session auth).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

import service as broker_service

SECRET = "broker-rpc-ingress-secret-0123456789"
PEPPER = "broker-pepper-0123456789abcdef0123456789"
AUTHORITY = "control-plane.local-agent-broker.skeleton-test.v1"
ACCOUNT = "usr_" + "a" * 32
WORKSPACE = "ws.skeleton.1"
BINDING = "bind.skeleton.1"
DEVICE = "device.skeleton.1"
CREDENTIAL = b"skeleton-device-credential-bytes"
SESSION = "sess.skeleton.1"


def now_iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def proof_headers(path: str, body: bytes, *, at: int | None = None) -> dict[str, str]:
    at = int(time.time()) if at is None else at
    signed = b"\n".join((b"v1", b"POST", path.encode(), str(at).encode(), body))
    digest = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return {"x-padiem-service-at": str(at), "x-padiem-service-proof": "v1=" + digest}


def environ(tmp_path: Path) -> dict[str, str]:
    return {
        "PADIEM_BROKER_RPC_INGRESS_SECRET": SECRET,
        "LOCAL_AGENT_BROKER_PEPPER": PEPPER,
        "LOCAL_AGENT_BROKER_AUTHORITY_REF": AUTHORITY,
        "PADIEM_BROKER_DB_PATH": str(tmp_path / "broker.sqlite3"),
    }


def build_app(tmp_path: Path):
    return broker_service.build_app(environ=environ(tmp_path))


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://broker.local"
    )


async def rpc(client: httpx.AsyncClient, method: str, payload: dict, *, at: int | None = None):
    body = json.dumps(payload, separators=(",", ":")).encode()
    path = f"/internal/rpc/{method}"
    return await client.post(path, content=body, headers={
        "content-type": "application/json", **proof_headers(path, body, at=at),
    })


def register_payload(*, binding=BINDING, device=DEVICE, account=ACCOUNT,
                     workspace=WORKSPACE, credential=CREDENTIAL) -> dict:
    return {
        "binding_ref": binding, "device_id": device,
        "account_ref": account, "workspace_ref": workspace,
        "credential_b64": base64.b64encode(credential).decode(), "now": now_iso(),
    }


def open_session_payload(*, session=SESSION, binding=BINDING, account=ACCOUNT,
                         workspace=WORKSPACE, credential=CREDENTIAL,
                         now: str | None = None, ttl: int = 900) -> dict:
    return {
        "session_id": session, "binding_ref": binding,
        "credential_b64": base64.b64encode(credential).decode(),
        "account_ref": account, "workspace_ref": workspace,
        "now": now or now_iso(), "ttl_seconds": ttl,
    }


def auth_payload(*, session=SESSION, binding=BINDING, credential=CREDENTIAL) -> dict:
    return {
        "session_id": session, "binding_ref": binding,
        "credential_b64": base64.b64encode(credential).decode(),
    }


def revoke_payload(*, binding=BINDING, now: str | None = None) -> dict:
    return {"binding_ref": binding, "now": now or now_iso()}


def enqueue_payload(*, command="cmd.skeleton.1", binding=BINDING, now: str | None = None) -> dict:
    return {
        "command_id": command, "binding_ref": binding,
        "run_id": "run.skeleton.1", "tool_request_ref": "tool.skeleton.1",
        "request_fingerprint": "f" * 64, "now": now or now_iso(),
    }
