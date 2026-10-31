"""Private CPython ingress tests; no Cloudflare services or network used."""
import json
import sqlite3
import time
import types

import httpx
import pytest

from canonical_connector_enrollment_consent_rpc import CanonicalIdentityEnrollmentConsentRPC
from com2_identity_rpc_ingress import (
    COM2_IDENTITY_RPC_METHODS,
    SERVICE_ID_REPLAY_DB_ENV,
    SqliteServiceIdReplayStore,
    create_app,
)
from internal_rpc_ingress import (
    SERVICE_ID_HEADER,
    SERVICE_ID_POLICY_ENV,
    proof_for,
    proof_for_v2,
)

SECRET = "synthetic-test-secret-" + "x" * 32
METHODS = {
    "resolve_connector_enrollment_consent_for_device": {"session_id": "synthetic", "device_id": "device"},
    "bind_connector_enrollment_challenge": {"session_id": "synthetic", "challenge_id": "challenge", "expires_at": "2099-01-01T00:00:00Z"},
    "authorize_connector_enrollment_redeem": {"challenge_id": "challenge", "consent_id": "consent", "device_id": "device", "owner_ref": "owner", "account_ref": "account", "workspace_ref": "workspace"},
}

# The policy and replay path are configuration, so a test never inherits them.
@pytest.fixture(autouse=True)
def _isolated_configuration(monkeypatch):
    monkeypatch.delenv(SERVICE_ID_POLICY_ENV, raising=False)
    monkeypatch.delenv(SERVICE_ID_REPLAY_DB_ENV, raising=False)


class Identity(CanonicalIdentityEnrollmentConsentRPC):
    env = types.SimpleNamespace()


@pytest.mark.asyncio
async def test_enrollment_routes_match_canonical_disabled_authority():
    import time
    authority = Identity()
    app = create_app(authority=authority, secret=SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        for method, payload in METHODS.items():
            assert method in COM2_IDENTITY_RPC_METHODS
            path = "/internal/rpc/" + method
            body = json.dumps(payload).encode()
            at = int(time.time())
            headers = {"x-padiem-service-at": str(at), "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
            response = await client.post(path, content=body, headers=headers)
            assert response.status_code == 200
            assert response.json() == await getattr(authority, method)(payload)
            assert response.json()["error"]["code"] == "connector_enrollment_rpc_disabled"
            assert (await client.post(path, content=body)).status_code == 403
        path = "/internal/rpc/grant_connector_enrollment_consent"
        response = await client.post(path, content=b"{}")
        assert response.status_code == 403
        response = await client.post("/internal/rpc/unknown_method", content=b"{}")
        assert response.status_code == 404


def test_refuses_missing_authority_or_secret():
    with pytest.raises(ValueError):
        create_app(authority=None, secret=SECRET)
    with pytest.raises(ValueError):
        create_app(authority=Identity(), secret="")


@pytest.mark.asyncio
async def test_valid_consent_binding_authorization_and_withdrawal_over_http():
    import time
    from datetime import datetime, timedelta, timezone
    from test_identity_connector_enrollment_consent_rpc import harness, grant_payload, SESSION_ID, DEVICE, SUBJECT

    authority, records, _, _ = harness()
    grant = await authority.grant_connector_enrollment_consent(grant_payload())
    assert grant["ok"]
    consent_id = grant["consent"]["consent_id"]
    app = create_app(authority=authority, secret=SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        async def call(method, payload):
            path = "/internal/rpc/" + method
            body = json.dumps(payload).encode()
            at = int(time.time())
            headers = {"x-padiem-service-at": str(at), "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
            response = await client.post(path, content=body, headers=headers)
            assert response.status_code == 200
            return response.json()

        consent = await call("resolve_connector_enrollment_consent_for_device", {"session_id": SESSION_ID, "device_id": DEVICE})
        assert consent["ok"] and consent["consent"]["consent_id"] == consent_id
        challenge = "pairing." + "f" * 32
        bound = await call("bind_connector_enrollment_challenge", {"session_id": SESSION_ID, "challenge_id": challenge, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
        assert bound["ok"]
        payload = {"challenge_id": challenge, "consent_id": consent_id, "device_id": DEVICE, "owner_ref": SUBJECT, "account_ref": "account.shared.test", "workspace_ref": "workspace.shared.test"}
        assert (await call("authorize_connector_enrollment_redeem", payload))["ok"]
        records.withdraw_preverified_consent(consent_id=consent_id, owner_subject_id=SUBJECT, now=datetime.now(timezone.utc))
        denied = await call("authorize_connector_enrollment_redeem", payload)
        assert denied["error"]["code"] == "enrollment_consent_withdrawn"


# --- signed request ids and replay refusal (#6417) ---------------------------

V2_METHOD = "resolve_connector_enrollment_consent_for_device"
V2_PATH = "/internal/rpc/" + V2_METHOD
V2_BODY = json.dumps(METHODS[V2_METHOD]).encode()


def _v2_headers(service_id, *, path=V2_PATH, body=V2_BODY, at=None):
    at = int(time.time()) if at is None else at
    return {
        "x-padiem-service-at": str(at),
        SERVICE_ID_HEADER: service_id,
        "x-padiem-service-proof": proof_for_v2(
            SECRET, method="POST", path=path, at=at, service_id=service_id, body=body
        ),
    }


def _v1_headers(*, path=V2_PATH, body=V2_BODY, at=None):
    at = int(time.time()) if at is None else at
    return {
        "x-padiem-service-at": str(at),
        "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body),
    }


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")


def _app(tmp_path, *, policy="required", db="replay.sqlite3"):
    return create_app(
        authority=Identity(), secret=SECRET, service_id_policy=policy,
        replay_db=str(tmp_path / db),
    )


@pytest.mark.asyncio
async def test_a_replayed_signed_request_is_refused(tmp_path):
    async with _client(_app(tmp_path)) as client:
        first = await client.post(V2_PATH, content=V2_BODY, headers=_v2_headers("req-0000000000000001"))
        replay = await client.post(V2_PATH, content=V2_BODY, headers=_v2_headers("req-0000000000000001"))
        fresh = await client.post(V2_PATH, content=V2_BODY, headers=_v2_headers("req-0000000000000002"))

    assert first.status_code == 200
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "rpc_replay_detected"
    assert fresh.status_code == 200


@pytest.mark.asyncio
async def test_the_replay_memory_is_a_row_in_the_durable_file(tmp_path):
    captured = _v2_headers("req-0000000000000009")
    async with _client(_app(tmp_path)) as client:
        assert (await client.post(V2_PATH, content=V2_BODY, headers=captured)).status_code == 200

    # The id is in the file, not in this process's memory: a set would forget
    # it on restart, which is the one thing a replay guard must not do.
    with sqlite3.connect(str(tmp_path / "replay.sqlite3")) as raw:
        rows = raw.execute(
            "SELECT service_id FROM service_request_ids WHERE service_id=?",
            ("req-0000000000000009",),
        ).fetchall()
    assert rows == [("req-0000000000000009",)]

    fresh_store = SqliteServiceIdReplayStore(str(tmp_path / "replay.sqlite3"))
    assert await fresh_store.claim(
        "req-0000000000000009", expires_at=int(time.time()) + 300
    ) is False

    async with _client(_app(tmp_path)) as restarted:
        replay = await restarted.post(V2_PATH, content=V2_BODY, headers=captured)
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "rpc_replay_detected"


@pytest.mark.asyncio
async def test_the_policy_decides_what_a_v1_request_gets(tmp_path):
    for policy, status in (("optional", 200), ("legacy", 200), ("required", 403)):
        async with _client(_app(tmp_path, policy=policy)) as client:
            response = await client.post(V2_PATH, content=V2_BODY, headers=_v1_headers())
        assert (policy, response.status_code) == (policy, status), policy
        if status == 403:
            assert response.json()["error"]["code"] == "rpc_service_id_required"

    # An id outside the signature is not an identity, under every policy.
    headers = _v1_headers()
    headers[SERVICE_ID_HEADER] = "req-0000000000000003"
    async with _client(_app(tmp_path, policy="optional")) as client:
        unsigned = await client.post(V2_PATH, content=V2_BODY, headers=headers)
    assert unsigned.status_code == 403
    assert unsigned.json()["error"]["code"] == "rpc_service_id_unsigned"


@pytest.mark.asyncio
async def test_a_v2_request_without_replay_memory_fails_closed():
    app = create_app(
        authority=Identity(), secret=SECRET, service_id_policy="optional", replay_db=""
    )
    async with _client(app) as client:
        response = await client.post(
            V2_PATH, content=V2_BODY, headers=_v2_headers("req-0000000000000004")
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rpc_replay_guard_unavailable"


def test_a_required_policy_without_replay_memory_fails_at_composition():
    with pytest.raises(ValueError):
        create_app(
            authority=Identity(), secret=SECRET, service_id_policy="required", replay_db=""
        )


def test_the_replay_store_requires_a_durable_path():
    for path in ("", "   ", ":memory:", None):
        with pytest.raises(ValueError):
            SqliteServiceIdReplayStore(path)


@pytest.mark.asyncio
async def test_the_sqlite_store_forgets_expired_ids(tmp_path):
    clock = [1_000_000]
    store = SqliteServiceIdReplayStore(
        str(tmp_path / "replay.sqlite3"), clock=lambda: clock[0]
    )
    assert await store.claim("req-0000000000000005", expires_at=1_000_010) is True
    assert await store.claim("req-0000000000000005", expires_at=1_000_010) is False
    clock[0] = 1_000_020
    assert await store.claim("req-0000000000000005", expires_at=1_000_030) is True
