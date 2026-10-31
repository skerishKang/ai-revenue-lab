import importlib
import json
import sys
import types

import pytest

import harness_support as h
from shadow_compare import ShadowRecorder, compare_read
from test_differential_parity import _DoStorage


@pytest.mark.asyncio
async def test_real_do_and_broker_read_shadow_records_only_outcome(monkeypatch, tmp_path):
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
    env = types.SimpleNamespace(LOCAL_AGENT_BROKER_AUTHORITY_REF=h.AUTHORITY,
                                LOCAL_AGENT_BROKER_PEPPER=h.PEPPER)
    do = worker.LocalAgentBrokerDurableObject(types.SimpleNamespace(storage=storage), env)
    app = h.build_app(tmp_path)
    record = tmp_path / "shadow.jsonl"
    try:
        seed = h.register_payload()
        assert (await do.register_binding(seed))["ok"]
        assert app.state.broker._runtime.register_binding(seed)["ok"]
        async with h.client_for(app) as client:
            async def primary(method, payload):
                return await getattr(do, method)(payload)
            async def shadow(method, payload):
                response = await h.rpc(client, method, payload)
                assert response.status_code == 200
                return response.json()
            payload = {"account_ref": h.ACCOUNT, "workspace_ref": h.WORKSPACE}
            expected = await primary("device_directory", payload)
            result = await compare_read("device_directory", payload, primary=primary,
                                        shadow=shadow, recorder=ShadowRecorder(str(record)))
            assert result == expected
        event = json.loads(record.read_text().strip())
        assert event["outcome"] == "match"
        assert set(event) == {"at", "method", "outcome"}
        assert h.ACCOUNT not in record.read_text()
        assert h.WORKSPACE not in record.read_text()
    finally:
        app.state.broker_storage.close()
        storage.close()
        sys.modules.pop("local_agent_broker_worker", None)


@pytest.mark.asyncio
async def test_shadow_mismatch_error_and_mutators_are_not_exposed(tmp_path):
    record = tmp_path / "events"
    calls = []
    async def primary(method, payload):
        calls.append(method)
        return {"ok": True, "private": "secret-value"}
    async def different(method, payload):
        return {"ok": False}
    async def error(method, payload):
        raise RuntimeError("private internal detail")
    recorder = ShadowRecorder(str(record))
    for shadow in (different, error):
        result = await compare_read("device_truth", {}, primary=primary, shadow=shadow, recorder=recorder)
        assert result["ok"] is True
    with pytest.raises(ValueError):
        await compare_read("rotate_credential", {}, primary=primary, shadow=error, recorder=recorder)
    assert calls == ["device_truth", "device_truth"]
    events = [json.loads(line) for line in record.read_text().splitlines()]
    assert [event["outcome"] for event in events] == ["mismatch", "shadow_error"]
    assert "secret-value" not in record.read_text()
    assert "private internal detail" not in record.read_text()
