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
        assert response.status_code == 404


def test_refuses_missing_authority_or_secret():
    with pytest.raises(ValueError):
        create_app(authority=None, secret=SECRET)
    with pytest.raises(ValueError):
        create_app(authority=Identity(), secret="")
