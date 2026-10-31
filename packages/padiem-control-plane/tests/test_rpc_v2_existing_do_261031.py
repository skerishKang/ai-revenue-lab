"""Exercise real Worker -> real DO claim code on an existing empty SQLite store."""
import asyncio
import json
import sqlite3
import time
import types

import pytest

from internal_rpc_ingress import proof_for, proof_for_v2
from service_id_replay import SqliteServiceIdReplayStore
from test_rpc_service_id_replay_261031 import (
    SECRET, _Namespace, _Request, _load_identity_worker,
)
from test_engine_admission_rpc_ingress_261031 import _load_worker as _load_admission_worker


class Cursor:
    def __init__(self, cursor):
        self.rowsWritten = max(cursor.rowcount, 0)


class Sql:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)

    def exec(self, statement, *args):
        return Cursor(self.db.execute(statement, args))


class Storage:
    def __init__(self):
        self.sql = Sql()


def request(method, *, request_id=None):
    path = '/internal/rpc/' + method
    body = b'{}'
    at = int(time.time())
    if request_id is None:
        signature = proof_for(SECRET, method='POST', path=path, at=at, body=body)
    else:
        signature = proof_for_v2(SECRET, method='POST', path=path, at=at,
                                 service_id=request_id, body=body)
    headers = {'x-padiem-service-at': str(at), 'x-padiem-service-proof': signature}
    if request_id is not None:
        headers['x-padiem-service-id'] = request_id
    return _Request(path=path, headers=headers, body=body)


@pytest.mark.parametrize('kind', ['identity', 'admission'])
def test_existing_do_initializes_replay_table_and_refuses_duplicates(kind):
    async def run():
        if kind == 'identity':
            module = _load_identity_worker()
            do_type = module.CanonicalIdentityDurableObject
            method = 'resolve_auth_session'
            binding = 'CONTROL_PLANE_IDENTITY'
            secret_binding = 'PADIEM_IDENTITY_RPC_INGRESS_SECRET'
        else:
            module = _load_admission_worker()
            do_type = module.CanonicalEngineAdmissionDurableObject
            method = 'fetch_entitlement_snapshot'
            binding = 'CONTROL_PLANE_ENGINE_ADMISSION'
            secret_binding = 'PADIEM_ENGINE_ADMISSION_RPC_INGRESS_SECRET'
        storage = Storage()
        do = object.__new__(do_type)
        do._service_ids = SqliteServiceIdReplayStore(storage)
        calls = []
        async def dispatch(payload):
            calls.append(payload)
            return {'ok': True}
        setattr(do, method, dispatch)
        env = types.SimpleNamespace(**{binding: _Namespace(do), secret_binding: SECRET,
                                      'PADIEM_RPC_SERVICE_ID_POLICY': 'required'})
        worker = module.Default(env=env)
        assert storage.sql.db.execute("SELECT name FROM sqlite_master WHERE name='service_request_ids'").fetchone() is None
        first = await worker.fetch(request(method, request_id='request-0000000000000001'))
        second = await worker.fetch(request(method, request_id='request-0000000000000001'))
        assert first.status == 200
        assert second.status == 409
        assert json.loads(second.body)['error']['code'] == 'rpc_replay_detected'
        assert len(calls) == 1
        required = await worker.fetch(request(method))
        assert required.status == 403
        env.PADIEM_RPC_SERVICE_ID_POLICY = 'optional'
        legacy = await worker.fetch(request(method))
        assert legacy.status == 200
    asyncio.run(run())


def test_durable_store_recreates_table_and_releases_expired_ids():
    async def run():
        clock = [100]
        storage = Storage()
        store = SqliteServiceIdReplayStore(storage, clock=lambda: clock[0])
        assert await store.claim('id', expires_at=110) is True
        assert await store.claim('id', expires_at=110) is False
        clock[0] = 111
        assert await store.claim('id', expires_at=120) is True
        storage.sql.db.execute('DROP TABLE service_request_ids')
        assert await store.claim('id', expires_at=120) is True
    asyncio.run(run())
