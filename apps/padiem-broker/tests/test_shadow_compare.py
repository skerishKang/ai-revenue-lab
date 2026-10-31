import asyncio
import importlib
import time
import json
import sys
import types

import pytest

import harness_support as h
from shadow_compare import ShadowDispatcher, ShadowRecorder, compare_read
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
            dispatcher = ShadowDispatcher()
            result = await compare_read("device_directory", payload, primary=primary,
                                        shadow=shadow, recorder=ShadowRecorder(str(record)), dispatcher=dispatcher)
            assert result == expected
            await dispatcher.drain()
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
    dispatcher = ShadowDispatcher()
    for shadow in (different, error):
        result = await compare_read("device_truth", {}, primary=primary, shadow=shadow, recorder=recorder, dispatcher=dispatcher)
        assert result["ok"] is True
    with pytest.raises(ValueError):
        await compare_read("rotate_credential", {}, primary=primary, shadow=error, recorder=recorder)
    assert calls == ["device_truth", "device_truth"]
    await dispatcher.drain()
    events = [json.loads(line) for line in record.read_text().splitlines()]
    assert [event["outcome"] for event in events] == ["mismatch", "shadow_error"]
    assert "secret-value" not in record.read_text()
    assert "private internal detail" not in record.read_text()



@pytest.mark.asyncio
async def test_slow_shadow_does_not_delay_primary_response(tmp_path):
    dispatcher = ShadowDispatcher()
    async def primary(method, payload):
        await asyncio.sleep(0.05)
        return {"ok": True}
    async def slow(method, payload):
        await asyncio.sleep(5)
        return {"ok": True}
    start = time.monotonic()
    result = await compare_read("device_truth", {}, primary=primary, shadow=slow,
                                recorder=ShadowRecorder(str(tmp_path / "events")),
                                timeout_seconds=6, dispatcher=dispatcher)
    elapsed = time.monotonic() - start
    assert result == {"ok": True}
    assert elapsed < 0.75
    await dispatcher.drain()
    assert json.loads((tmp_path / "events").read_text())["outcome"] == "match"


@pytest.mark.asyncio
async def test_shadow_exception_and_recording_failure_leave_primary_unchanged(tmp_path):
    dispatcher = ShadowDispatcher()
    expected = {"ok": True, "value": 42}
    async def primary(method, payload):
        return expected
    async def shadow_error(method, payload):
        raise RuntimeError("failure")
    class BrokenRecorder:
        def record(self, method, outcome):
            raise OSError("unavailable")
    result = await compare_read("device_truth", {}, primary=primary, shadow=shadow_error,
                                recorder=BrokenRecorder(), dispatcher=dispatcher)
    assert result == expected
    await dispatcher.drain()
    async def same(method, payload):
        return expected
    result = await compare_read("device_truth", {}, primary=primary, shadow=same,
                                recorder=BrokenRecorder(), dispatcher=dispatcher)
    assert result == expected
    await dispatcher.drain()


@pytest.mark.asyncio
async def test_saturation_counts_skipped_without_calling_shadow(tmp_path):
    dispatcher = ShadowDispatcher(max_in_flight=1)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def primary(method, payload):
        return {"ok": True}
    async def shadow(method, payload):
        calls.append(method)
        started.set()
        await release.wait()
        return {"ok": True}
    recorder = ShadowRecorder(str(tmp_path / "events"))
    first = await compare_read("device_truth", {}, primary=primary, shadow=shadow,
                               recorder=recorder, dispatcher=dispatcher)
    await started.wait()
    second = await compare_read("device_truth", {}, primary=primary, shadow=shadow,
                                recorder=recorder, dispatcher=dispatcher)
    assert first == second == {"ok": True}
    assert dispatcher.skipped == 1
    assert calls == ["device_truth"]
    release.set()
    await dispatcher.drain()
    assert json.loads((tmp_path / "events").read_text())["outcome"] == "match"


@pytest.mark.asyncio
async def test_mutator_rejected_before_either_call(tmp_path):
    calls = []
    async def called(method, payload):
        calls.append(method)
        return {}
    with pytest.raises(ValueError):
        await compare_read("rotate_credential", {}, primary=called, shadow=called,
                           recorder=ShadowRecorder(str(tmp_path / "events")),
                           dispatcher=ShadowDispatcher())
    assert calls == []
