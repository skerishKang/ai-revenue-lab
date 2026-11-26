from __future__ import annotations

import json
import time
import uuid

from test_internal_rpc_ingress import (  # noqa: E402
    ADAPTER_ROOT,
    SECRET,
    _env,
    _load_worker,
    _Namespace,
    _Request,
    _run,
)
from internal_rpc_ingress import proof_for, proof_for_v2  # noqa: E402

IDENTITY_SECRET = "synthetic-auth-state-identity-secret-32bytes"
DELETION_SECRET = "synthetic-auth-state-deletion-secret-32bytes"
IDENTITY_PREFIX = "/internal/auth-state/identity/"
DELETION_PREFIX = "/internal/auth-state/deletion-record/"


class _Stub:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.claimed = True

    async def claim_service_id(self, payload):
        claimed = self.claimed
        self.claimed = False
        return {"ok": True, "claimed": claimed}

    def __getattr__(self, name):
        async def call(payload):
            self.calls.append((name, payload))
            return dict(self.answer)
        return call


def _request(path, body, secret, *, at=None, service_id=None, proof=None):
    at = int(time.time()) if at is None else at
    service_id = service_id or str(uuid.uuid4())
    headers = {
        "x-padiem-service-at": str(at),
        "x-padiem-service-id": service_id,
        "x-padiem-service-proof": proof or proof_for_v2(
            secret, method="POST", path=path, at=at, service_id=service_id, body=body,
        ),
    }
    return _Request("https://identity.invalid" + path, headers=headers, body=body)


def _worker(stub, **secrets):
    module = _load_worker(
        ADAPTER_ROOT / "identity_authority_worker.py", "identity_worker_auth_state_bridge_test"
    )
    env = _env(CONTROL_PLANE_IDENTITY=_Namespace(stub), **secrets)
    return module, module.Default(env=env)


def test_auth_state_identity_door_is_secret_bound_and_allowlisted():
    stub = _Stub({"ok": True, "value": "synthetic"})
    module, worker = _worker(stub, PADIEM_AUTH_STATE_IDENTITY_RPC_SECRET=IDENTITY_SECRET)
    path = IDENTITY_PREFIX + "list_active_product_links_for_subject"
    body = b'{"canonical_subject_id":"sub_synthetic"}'
    response = _run(worker.fetch(_request(path, body, IDENTITY_SECRET)))
    assert response.status == 200
    assert json.loads(response.body) == {"ok": True, "value": "synthetic"}
    assert stub.calls == [("list_active_product_links_for_subject", {"canonical_subject_id": "sub_synthetic"})]

    response = _run(worker.fetch(_request(
        IDENTITY_PREFIX + "establish_auth_session", b"{}", IDENTITY_SECRET,
    )))
    assert response.status == 404
    assert json.loads(response.body)["error"]["code"] == "rpc_unknown_method"
    assert len(stub.calls) == 1
    assert module.AUTH_STATE_IDENTITY_RPC_METHODS == frozenset({
        "resolve_or_create_identity_subject",
        "resolve_or_create_product_link",
        "list_active_product_links_for_subject",
    })


def test_shared_ingress_secret_cannot_open_the_auth_state_door():
    stub = _Stub({"ok": True})
    _, worker = _worker(
        stub,
        PADIEM_IDENTITY_RPC_INGRESS_SECRET=SECRET,
        PADIEM_AUTH_STATE_IDENTITY_RPC_SECRET=IDENTITY_SECRET,
    )
    response = _run(worker.fetch(_request(
        IDENTITY_PREFIX + "list_active_product_links_for_subject",
        b'{"canonical_subject_id":"sub_synthetic"}',
        SECRET,
    )))
    assert response.status == 403
    assert json.loads(response.body)["error"]["code"] == "rpc_proof_invalid"
    assert stub.calls == []


def test_auth_state_deletion_door_is_one_method_and_replay_bound():
    stub = _Stub({"ok": True, "removed_by_account_deletion": True})
    module, worker = _worker(stub, PADIEM_AUTH_STATE_DELETION_RECORD_RPC_SECRET=DELETION_SECRET)
    path = DELETION_PREFIX + "resolve_subject_removed_by_account_deletion"
    body = b'{"canonical_subject_id":"sub_synthetic"}'
    request = _request(path, body, DELETION_SECRET)
    first = _run(worker.fetch(request))
    second = _run(worker.fetch(request))
    assert first.status == 200
    assert second.status == 409
    assert json.loads(second.body)["error"]["code"] == "rpc_replay_detected"
    assert stub.calls == [("resolve_subject_removed_by_account_deletion", {"canonical_subject_id": "sub_synthetic"})]
    assert module.ACCOUNT_DELETION_RECORD_RPC_ON_HTTPS_INGRESS is False
    assert module.ACCOUNT_DELETION_RECORD_RPC_ON_AUTH_STATE_HTTPS_INGRESS is True


def test_auth_state_doors_require_an_id_bound_v2_proof():
    stub = _Stub({"ok": True})
    _, worker = _worker(stub, PADIEM_AUTH_STATE_IDENTITY_RPC_SECRET=IDENTITY_SECRET)
    path = IDENTITY_PREFIX + "list_active_product_links_for_subject"
    body = b'{"canonical_subject_id":"sub_synthetic"}'
    at = int(time.time())
    legacy = proof_for(IDENTITY_SECRET, method="POST", path=path, at=at, body=body)
    unsigned = _Request(
        "https://identity.invalid" + path,
        headers={"x-padiem-service-at": str(at), "x-padiem-service-proof": legacy},
        body=body,
    )
    assert json.loads(_run(worker.fetch(unsigned)).body)["error"]["code"] == "rpc_service_id_required"
    unsigned_id = _request(path, body, IDENTITY_SECRET, at=at, proof=legacy)
    assert json.loads(_run(worker.fetch(unsigned_id)).body)["error"]["code"] == "rpc_service_id_unsigned"
    assert stub.calls == []


def test_auth_state_doors_are_absent_without_their_secrets():
    stub = _Stub({"ok": True})
    module, worker = _worker(stub)
    for prefix in (IDENTITY_PREFIX, DELETION_PREFIX):
        response = _run(worker.fetch(_request(prefix + "unknown", b"{}", IDENTITY_SECRET)))
        assert response.status == 404 and response.body == "Not Found"
    assert stub.calls == []
    unbound = module.Default(env=_env())
    response = _run(unbound.fetch(_Request("https://identity.invalid/internal/rpc/unknown", body=b"{}")))
    assert response.status == 404 and response.body == "Not Found"
