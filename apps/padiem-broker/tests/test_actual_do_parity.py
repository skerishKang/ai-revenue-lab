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
