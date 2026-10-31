"""Private CPython ingress tests; no Cloudflare services or network used."""
import json
import types

import httpx
import pytest

from canonical_connector_enrollment_consent_rpc import CanonicalIdentityEnrollmentConsentRPC
from com2_identity_rpc_ingress import COM2_IDENTITY_RPC_METHODS, create_app
from internal_rpc_ingress import proof_for

SECRET = "synthetic-test-secret-" + "x" * 32
METHODS = {
    "resolve_connector_enrollment_consent_for_device": {"session_id": "synthetic", "device_id": "device"},
    "bind_connector_enrollment_challenge": {"session_id": "synthetic", "challenge_id": "challenge", "expires_at": "2099-01-01T00:00:00Z"},
    "authorize_connector_enrollment_redeem": {"challenge_id": "challenge", "consent_id": "consent", "device_id": "device", "owner_ref": "owner", "account_ref": "account", "workspace_ref": "workspace"},
}


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
