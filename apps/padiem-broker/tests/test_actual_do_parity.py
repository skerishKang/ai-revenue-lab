"""Compare real DO entrypoint methods with the broker HTTP app in process.

Workers platform classes and SQLite storage are doubles; the DO class itself is
the actual production Python entrypoint, not a BrokerComposition substitute.
"""
import base64
import importlib
import sys
import types

import pytest

import harness_support as h
from test_differential_parity import _DoStorage, _normalize


@pytest.mark.asyncio
async def test_real_do_session_rotation_and_cas_parity(monkeypatch, tmp_path):
    class DurableObject:
        def __init__(self, ctx, env):
            self.ctx, self.env = ctx, env

    workers = types.ModuleType("workers")
    workers.DurableObject = DurableObject
    workers.WorkerEntrypoint = type("WorkerEntrypoint", (), {})
    workers.Response = type("Response", (), {})
    monkeypatch.setitem(sys.modules, "workers", workers)
    monkeypatch.delitem(sys.modules, "local_agent_broker_worker", raising=False)
    worker = importlib.import_module("local_agent_broker_worker")
    storage = _DoStorage()
    env = types.SimpleNamespace(
        LOCAL_AGENT_BROKER_AUTHORITY_REF=h.AUTHORITY,
        LOCAL_AGENT_BROKER_PEPPER=h.PEPPER,
    )
    do = worker.LocalAgentBrokerDurableObject(types.SimpleNamespace(storage=storage), env)
    app = h.build_app(tmp_path)
    try:
        payload = h.register_payload()
        assert (await do.register_binding(payload))["ok"] is True
        assert app.state.broker._runtime.register_binding(payload)["ok"] is True
        async with h.client_for(app) as client:
            async def compare(method, data):
                expected = await getattr(do, method)(data)
                response = await h.rpc(client, method, data)
                assert response.status_code == 200
                assert _normalize(response.json()) == _normalize(expected)
                return expected

            assert (await compare("open_session", h.open_session_payload()))["ok"] is True
            assert (await compare("authenticate_device_session", h.auth_payload()))["ok"] is True
            bad = h.auth_payload(credential=b"wrong")
            assert (await compare("authenticate_device_session", bad))["ok"] is False
            rotate = {
                "binding_ref": h.BINDING,
                "expected_generation": 1,
                "new_credential_b64": base64.b64encode(b"synthetic-next-credential").decode(),
                "now": h.now_iso(),
            }
            assert (await compare("rotate_credential", rotate))["ok"] is True
            loser = await compare("rotate_credential", rotate)
            assert loser["error"]["code"] == "stale_device_credential_generation"
            assert (await compare("authenticate_device_session", h.auth_payload()))["ok"] is False
    finally:
        app.state.broker_storage.close()
        storage.close()
        sys.modules.pop("local_agent_broker_worker", None)


@pytest.mark.asyncio
async def test_concurrent_cas_do_entrypoint_and_http_have_same_winner_loser(monkeypatch, tmp_path):
    import asyncio

    class DurableObject:
        def __init__(self, ctx, env):
            self.ctx, self.env = ctx, env

    workers = types.ModuleType("workers")
    workers.DurableObject = DurableObject
    workers.WorkerEntrypoint = type("WorkerEntrypoint", (), {})
    workers.Response = type("Response", (), {})
    monkeypatch.setitem(sys.modules, "workers", workers)
    monkeypatch.delitem(sys.modules, "local_agent_broker_worker", raising=False)
    worker = importlib.import_module("local_agent_broker_worker")
    storage = _DoStorage()
    env = types.SimpleNamespace(LOCAL_AGENT_BROKER_AUTHORITY_REF=h.AUTHORITY, LOCAL_AGENT_BROKER_PEPPER=h.PEPPER)
    do = worker.LocalAgentBrokerDurableObject(types.SimpleNamespace(storage=storage), env)
    app = h.build_app(tmp_path)
    try:
        data = h.register_payload()
        assert (await do.register_binding(data))["ok"]
        assert app.state.broker._runtime.register_binding(data)["ok"]
        rotate = {"binding_ref": h.BINDING, "expected_generation": 1,
                  "new_credential_b64": base64.b64encode(b"synthetic-next-credential").decode(),
                  "now": h.now_iso()}
        async with h.client_for(app) as client:
            do_results, responses = await asyncio.gather(
                asyncio.gather(do.rotate_credential(rotate), do.rotate_credential(rotate)),
                asyncio.gather(h.rpc(client, "rotate_credential", rotate), h.rpc(client, "rotate_credential", rotate)),
            )
        assert all(response.status_code == 200 for response in responses)
        actual = [response.json() for response in responses]
        for results in (do_results, actual):
            assert sum(result["ok"] is True for result in results) == 1
            assert [result["error"]["code"] for result in results if not result["ok"]] == ["stale_device_credential_generation"]
        assert sorted((_normalize(r) for r in do_results), key=lambda r: r["ok"]) == sorted((_normalize(r) for r in actual), key=lambda r: r["ok"])
    finally:
        app.state.broker_storage.close()
        storage.close()
        sys.modules.pop("local_agent_broker_worker", None)


def test_shared_sqlite_connection_serializes_competing_transactions(tmp_path):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from storage import SqLiteDurableStorage

    store = SqLiteDurableStorage.open(str(tmp_path / "race.sqlite3"))
    store.sql.exec("CREATE TABLE versions (id INTEGER PRIMARY KEY, generation INTEGER)")
    store.sql.exec("INSERT INTO versions VALUES (1, 1)")
    start = threading.Barrier(2)

    def attempt():
        start.wait(timeout=5)
        def operation():
            time.sleep(0.05)
            return store.sql.exec("UPDATE versions SET generation=2 WHERE id=1 AND generation=1").rowsWritten
        return store.transactionSync(operation)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = [future.result(timeout=5) for future in (executor.submit(attempt), executor.submit(attempt))]
        assert sorted(outcomes) == [0, 1]
        assert store.sql.exec("SELECT generation FROM versions").toArray() == [{"generation": 2}]
    finally:
        store.close()
