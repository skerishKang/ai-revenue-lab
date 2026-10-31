"""Offline Google OAuth signed ingress replay contracts."""
import asyncio
import json
import sqlite3
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CP = ROOT / "packages/padiem-control-plane"
sys.path.insert(0, str(CP))
sys.path.insert(0, str(CP / "tests"))
import test_internal_rpc_ingress as base
from internal_rpc_ingress import proof_for, proof_for_v2
from service_id_replay import SqliteServiceIdReplayStore

PATH = "/internal/rpc/workspace_connector_state"
BODY = b'{"workspace_ref":"test-workspace"}'
SECRET = "synthetic-test-secret-" + "x" * 32
ID = "request-00000000000001"

class Sql:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
    def exec(self, statement, *args):
        return self.db.execute(statement, args)

class Stub:
    def __init__(self, durable):
        self.durable = durable
        self.calls = 0
    async def claim_service_id(self, payload):
        return await self.durable.claim_service_id(payload)
    async def workspace_connector_state(self, payload):
        self.calls += 1
        return {"ok": True}

def setup_worker():
    module = base._load_worker(CP / "google_oauth_worker.py", "google_replay_worker_test")
    durable = object.__new__(module.GoogleOAuthDurableObject)
    storage = types.SimpleNamespace(sql=Sql())
    durable._service_ids = SqliteServiceIdReplayStore(storage)
    stub = Stub(durable)
    env = types.SimpleNamespace(
        GOOGLE_OAUTH_STATE=base._Namespace(stub),
        PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET=SECRET,
    )
    return module.Default(env=env), durable, stub, env, storage

def signed(version=2, service_id=ID):
    at = int(time.time())
    if version == 2:
        proof = proof_for_v2(SECRET, method="POST", path=PATH, at=at, service_id=service_id, body=BODY)
    else:
        proof = proof_for(SECRET, method="POST", path=PATH, at=at, body=BODY)
    headers = {"x-padiem-service-at": str(at), "x-padiem-service-proof": proof}
    if version == 2:
        headers["x-padiem-service-id"] = service_id
    return base._Request("https://example.invalid" + PATH, headers=headers, body=BODY)

def run(worker, request):
    return asyncio.run(worker.fetch(request))

def test_fresh_sqlite_table_first_request_and_replay():
    worker, _, stub, _, storage = setup_worker()
    assert storage.sql.db.execute("SELECT name FROM sqlite_master WHERE name='service_request_ids'").fetchone() is None
    first = run(worker, signed())
    second = run(worker, signed())
    assert first.status == 200
    assert second.status == 409 and json.loads(second.body)["error"]["code"] == "rpc_replay_detected"
    assert stub.calls == 1

def test_storage_error_is_503_and_never_dispatches():
    worker, durable, stub, _, _ = setup_worker()
    class Broken:
        def exec(self, *args):
            raise RuntimeError("storage unavailable")
    durable._service_ids = SqliteServiceIdReplayStore(types.SimpleNamespace(sql=Broken()))
    response = run(worker, signed())
    assert response.status == 503 and json.loads(response.body)["error"]["code"] == "rpc_replay_guard_error"
    assert stub.calls == 0

def test_v1_follows_optional_and_required_policy():
    worker, _, stub, env, _ = setup_worker()
    assert run(worker, signed(version=1)).status == 200
    env.PADIEM_RPC_SERVICE_ID_POLICY = "required"
    response = run(worker, signed(version=1))
    assert response.status == 403 and json.loads(response.body)["error"]["code"] == "rpc_service_id_required"
    assert stub.calls == 1
