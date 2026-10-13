"""Synthetic device-originated HTTPS bootstrap contract: no production mount."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from app.connector_gateway_bootstrap_http import (
    CONNECTOR_GATEWAY_BEGIN_PATH,
    CONNECTOR_GATEWAY_FINISH_PATH,
    CONNECTOR_GATEWAY_BOOTSTRAP_ROUTES_MOUNTED,
    CONNECTOR_GATEWAY_CREDENTIAL_TRANSFER_WIRED,
    connector_gateway_bootstrap_begin,
    connector_gateway_bootstrap_finish,
)

CID = "pairing." + "a" * 32
DEVICE = "device.office.1"
LEASE = "gateway." + "b" * 32
NONCE = "c" * 64


class FakeReviewedIngress:
    def __init__(self):
        self.calls = 0
        self.permit = True
    async def verify(self, request):
        self.calls += 1
        return self.permit


class FakePrivateBroker:
    def __init__(self):
        self.calls = []
    async def gateway_bootstrap_rpc(self, payload):
        self.calls.append(payload)
        if payload["operation"] == "begin":
            return {"ok": True, "gateway": {
                "challenge_id": CID, "device_id": DEVICE,
                "lease_ref": LEASE, "nonce_hex": NONCE,
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
                "credential": False, "challenge_consumed": False,
            }}
        return {"ok": True, "gateway": {
            "challenge_id": CID, "device_id": DEVICE,
            "lease_ref": LEASE, "verified": True,
            "credential": False, "challenge_consumed": False,
        }}


def fixture(*, enabled=True, trusted=True, scheme="https"):
    app = Starlette()
    # Test-only explicit mounts: app_factory NEVER mounts either route.
    app.add_route(CONNECTOR_GATEWAY_BEGIN_PATH, connector_gateway_bootstrap_begin, methods=["POST"])
    app.add_route(CONNECTOR_GATEWAY_FINISH_PATH, connector_gateway_bootstrap_finish, methods=["POST"])
    app.state.connector_gateway_bootstrap_enabled = enabled
    guard, broker = FakeReviewedIngress(), FakePrivateBroker()
    guard.permit = trusted
    app.state.connector_gateway_trusted_tls = guard
    app.state.connector_gateway_broker_private_rpc = broker
    return TestClient(app, base_url=f"{scheme}://testserver"), guard, broker


def test_no_production_mount_or_credential_delivery_exists():
    assert CONNECTOR_GATEWAY_BOOTSTRAP_ROUTES_MOUNTED is False
    assert CONNECTOR_GATEWAY_CREDENTIAL_TRANSFER_WIRED is False
    c, gate, broker = fixture(enabled=False)
    response = c.post(CONNECTOR_GATEWAY_BEGIN_PATH, json={
        "challenge_id": CID, "device_id": DEVICE,
    })
    assert response.status_code == 503
    assert broker.calls == [] and gate.calls == 0


@pytest.mark.parametrize(("enabled", "trusted", "scheme"), [
    (False, True, "https"),
    (True, False, "https"),
    (True, True, "http"),
])
def test_tls_or_server_gate_missing_means_no_private_broker_call(enabled, trusted, scheme):
    c, guard, broker = fixture(enabled=enabled, trusted=trusted, scheme=scheme)
    response = c.post(CONNECTOR_GATEWAY_BEGIN_PATH, json={
        "challenge_id": CID, "device_id": DEVICE,
    })
    assert response.status_code in {403, 503}
    assert broker.calls == []


def test_bounded_pairing_bootstrap_proof_receipt_never_returns_secrets():
    c, guard, broker = fixture()
    first = c.post(CONNECTOR_GATEWAY_BEGIN_PATH, json={
        "challenge_id": CID, "device_id": DEVICE,
    })
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"].startswith("no-store")
    result = first.json()
    assert set(result) == {
        "ok", "challenge_id", "device_id", "lease_ref", "nonce_hex",
        "expires_at", "credential", "challenge_consumed",
    }
    assert result["credential"] is False and result["challenge_consumed"] is False
    complete = c.post(CONNECTOR_GATEWAY_FINISH_PATH, json={
        "challenge_id": CID, "device_id": DEVICE,
        "lease_ref": LEASE, "proof_hex": "d" * 64,
    })
    assert complete.status_code == 200
    assert complete.json()["verified"] is True
    assert "credential_b64" not in complete.text
    assert "raw_device_credential" not in complete.text
    assert "enrolled" not in complete.text and "online" not in complete.text
    assert [x["operation"] for x in broker.calls] == ["begin", "finish"]
    assert guard.calls == 2


@pytest.mark.parametrize(("raw","status"), [
    (b'{"challenge_id":"pairing.aaa","challenge_id":"pairing.bbb","device_id":"device.1"}', 400),
    (b'{"challenge_id":"pairing.aaa","device_id":"device.1","account_ref":"forbidden"}', 400),
    (b'{"challenge_id":1,"device_id":"device.1"}', 400),
    (b'{"challenge_id":"pairing.aaa","device_id":"device.1"', 400),
    (b"{" + b"x"*2048 + b"}", 400),
])
def test_invalid_or_duplicate_json_is_denied_before_private_rpc(raw,status):
    c, guard, broker = fixture()
    response = c.post(
        CONNECTOR_GATEWAY_BEGIN_PATH, content=raw,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == status
    assert broker.calls == []


def test_browser_origins_or_cookies_cannot_open_gateway_session():
    c, guard, broker = fixture()
    for headers in ({"Origin": "https://attacker.example"},
                    {"Cookie": "session=fake"}):
        response = c.post(CONNECTOR_GATEWAY_BEGIN_PATH, json={
            "challenge_id": CID, "device_id": DEVICE,
        }, headers=headers)
        assert response.status_code == 503
    assert broker.calls == []


def test_broker_failure_or_malformed_receipt_does_not_create_success():
    c, guard, broker = fixture()
    async def invalid(_):
        return {"ok": True, "gateway": {
            "challenge_id": CID, "device_id": DEVICE,
            "credential_b64": "forbidden",
        }}
    broker.gateway_bootstrap_rpc = invalid
    response = c.post(CONNECTOR_GATEWAY_BEGIN_PATH, json={
        "challenge_id": CID, "device_id": DEVICE,
    })
    assert response.status_code == 503
    assert "forbidden" not in response.text


def test_unconfigured_tls_verifier_is_a_hard_stop():
    c, guard, broker = fixture()
    c.app.state.connector_gateway_trusted_tls = None
    assert c.post(CONNECTOR_GATEWAY_BEGIN_PATH, json={
        "challenge_id": CID, "device_id": DEVICE,
    }).status_code == 503
    assert broker.calls == []
