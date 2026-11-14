"""Private binding and in-process signed ingress; no listening sockets."""
import json
import time

import httpx
import pytest

from test_identity_connector_account_key_read_rpc import (
    _env, _Namespace, _Stub, _Request, _signed_request, SECRET, _worker_mod,
)
from test_identity_connector_account_key_write_rpc import METHODS, ready, wire, snapshot
from canonical_connector_account_write_rpc import CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH
from com2_identity_rpc_ingress import create_app
from internal_rpc_ingress import SERVICE_ID_HEADER, SERVICE_ID_POLICY_ENV, proof_for, proof_for_v2


@pytest.mark.asyncio
async def test_worker_binding_and_signed_door_require_existing_ingress_authority():
    class ReplayStub(_Stub):
        seen = set()
        async def claim_service_id(self, payload):
            claimed = payload["service_id"] not in self.seen
            self.seen.add(payload["service_id"])
            return {"ok": True, "claimed": claimed}
    stub = ReplayStub({"ok": True})
    closed = _worker_mod.Default(env=_env(CONTROL_PLANE_IDENTITY=_Namespace(stub)))
    opened = _worker_mod.Default(env=_env(CONTROL_PLANE_IDENTITY=_Namespace(stub),
                                         PADIEM_IDENTITY_RPC_INGRESS_SECRET=SECRET))
    for index, method in enumerate(METHODS):
        payload = wire(method, "sub_fixture")
        body = json.dumps(payload).encode()
        assert await getattr(closed, method)(payload) == {"ok": True}
        assert stub.calls[-1] == (method, payload)
        signed = _signed_request(method=method, body=body, at=int(time.time()))
        assert (await closed.fetch(signed)).status == 404
        count = len(stub.calls)
        assert (await opened.fetch(_Request("https://identity.invalid/internal/rpc/" + method,
                                            headers={}, body=body))).status == 403
        assert len(stub.calls) == count
        assert (await opened.fetch(_signed_request(method=method, body=body, at=int(time.time())))).status == 403
        at = int(time.time())
        service_id = "worker-account-write-" + str(index)
        proof = proof_for_v2(SECRET, method="POST", path="/internal/rpc/" + method, at=at,
                             service_id=service_id, body=body)
        signed = lambda: _signed_request(method=method, body=body, at=at, proof=proof,
                                         extra_headers={SERVICE_ID_HEADER: service_id})
        assert (await opened.fetch(signed())).status == 200
        assert stub.calls[-1] == (method, payload)
        assert (await opened.fetch(signed())).status == 409
    assert (await opened.fetch(_signed_request(method="resolve_connector_workspace", body=b'{"session_id":"old"}',
                                              at=int(time.time())))).status == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [None, "optional"])
async def test_cpython_ingress_preserves_signatures_nonce_and_default_off(tmp_path, actual_authority, policy, monkeypatch):
    monkeypatch.delenv(SERVICE_ID_POLICY_ENV, raising=False)
    do, subject, _, sid = actual_authority
    setattr(do.env, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH, "false")
    before = snapshot(do)
    app = create_app(authority=do, secret=SECRET, service_id_policy=policy,
                     replay_db=str(tmp_path / "replay.sqlite3"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        for index, method in enumerate(METHODS):
            path = "/internal/rpc/" + method
            body = json.dumps(wire(method, subject)).encode()
            at = int(time.time())
            service_id = "request-account-write-" + str(index)
            headers = {"x-padiem-service-at": str(at), SERVICE_ID_HEADER: service_id,
                       "x-padiem-service-proof": proof_for_v2(SECRET, method="POST", path=path, at=at,
                                                             service_id=service_id, body=body)}
            assert (await client.post(path, content=body)).status_code == 403
            legacy = {"x-padiem-service-at": str(at),
                      "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
            assert (await client.post(path, content=body, headers=legacy)).status_code == 403
            bad = headers | {"x-padiem-service-proof": "0" * 64}
            assert (await client.post(path, content=body, headers=bad)).status_code == 403
            accepted = await client.post(path, content=body, headers=headers)
            assert accepted.status_code == 200
            assert accepted.json()["error"]["code"] == "connector_account_key_write_rpc_disabled"
            assert (await client.post(path, content=body, headers=headers)).status_code == 409
        path = "/internal/rpc/resolve_connector_workspace"
        body = json.dumps({"session_id": sid}).encode()
        at = int(time.time())
        headers = {"x-padiem-service-at": str(at),
                   "x-padiem-service-proof": proof_for(SECRET, method="POST", path=path, at=at, body=body)}
        assert (await client.post(path, content=body, headers=headers)).status_code == 200
    assert snapshot(do) == before


@pytest.fixture
def actual_authority():
    return ready()
