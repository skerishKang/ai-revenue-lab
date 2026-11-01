"""Native B14 function selection reaches the real Engine/Core remote tool binding."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from padiem_ai_core import StreamingExecutionRuntime
from padiem_ai_core.compaction import CompactionStore
from padiem_ai_core.b14_streaming import B14StreamEvent, B14StreamToolCall
from padiem_ai_core.b14_execution import B14RouteMetadata
from kagent.pc_remote_tools import REMOTE_NAMES, remote_tool_specs
from app.pc_tools_turn import CatalogToolCapabilities, definitions, _native_remote_scope
from padiem_ai_core.orchestration import OrchestrationError
from tests.test_6460_pc_action_driver import _service, _payload
from tests.test_5574_pc_read_boundary_end_to_end import _instant_sleep, DEVICE_ID
from tests.test_pc_remote_tools_integration import Endpoint, ScriptModel, tool


class Native:
    def __init__(self, name, arguments):
        self.name, self.arguments, self.requests = name, arguments, []

    async def stream(self, request):
        self.requests.append(request)
        route = B14RouteMetadata(selected_provider="test", selected_model="test/route")
        yield B14StreamEvent(tool_call=B14StreamToolCall(
            id="native-call", name=self.name, arguments=self.arguments), route=route)
        yield B14StreamEvent(done=True, finish_reason="tool_calls", route=route)

    def stream_auto(self, request):
        return self.stream(request)


def run_native(pc, native_name, native_args, choices=(), *, scope="files", speech="notes.txt 내용을 읽어줘"):
    model = ScriptModel([*choices, {"action": "complete", "answer": "Verified native result."}], pc)
    native = Native(native_name, native_args)
    service = _service(model, pc)
    async def capable(_):
        return True
    service._pc_tools_capability = capable
    service._pc_streaming_runtime_factory = lambda app: StreamingExecutionRuntime(app_id=app, b14_stream_client=native)
    payload = _payload([{"role": "user", "content": speech}], write=scope == "files_write")
    for key in ("agent_plan", "tool_arguments", "declared_plan"):
        payload.pop(key, None)
    payload["pc_tools"] = {"device_id": DEVICE_ID, "allowed_scopes": [scope]}
    with patch.object(asyncio, "sleep", _instant_sleep):
        response = asyncio.run(service.orchestrate_payload(payload))
    return response, model, native, payload


def test_native_file_read_then_structured_handle_read_uses_actual_core_binding(tmp_path):
    pc = Endpoint(tmp_path)
    response, followup, native, _ = run_native(pc, "files", {"path": "notes.txt"}, [
        lambda pc: tool("read_output", handle=pc.saved["handle"], offset=0, length=12),
    ])
    assert response.status_code == 200, response.body
    assert response.body["orchestration"]["execution"]["answer"] == "Verified native result."
    assert pc.ops == ["read"]
    assert [r["mode"] for r in pc.remote] == ["read_output"]
    assert "first needle" in followup.prompts[-1]
    assert len(native.requests) == 1


def test_native_background_job_then_status_and_output_use_actual_core_binding(tmp_path):
    pc = Endpoint(tmp_path)
    response, followup, native, _ = run_native(pc, "start_job", {"operation": {"op": "read", "path": "notes.txt"}}, [
        tool("job_status", job_id="dsp_background"),
        tool("job_output", job_id="dsp_background", offset=0, length=100),
    ])
    assert response.status_code == 200, response.body
    assert response.body["orchestration"]["execution"]["answer"] == "Verified native result."
    assert [r["mode"] for r in pc.remote] == ["job_start", "job_status", "job_output"]
    assert "finished" in followup.prompts[-1]
    assert len(native.requests) == 1


def test_native_batch_reaches_existing_per_file_executor(tmp_path):
    pc = Endpoint(tmp_path)
    response, _, _, _ = run_native(pc, "batch", {"operations": [
        {"op": "list", "path": "."}, {"op": "read", "path": "notes.txt"},
    ], "stop_on_error": True})
    assert response.status_code == 200, response.body
    assert pc.ops == ["list", "read"]


def test_native_recall_uses_owner_scoped_archive_through_real_tool_runtime(tmp_path, monkeypatch):
    import tests.test_6460_pc_action_driver as fixtures
    from app.claw_pc_query_step_driver import build_live_pc_query_driver
    store = CompactionStore(tmp_path / "archive.sqlite")
    payload = _payload([{"role": "user", "content": "기록을 다시 보여줘"}], write=False)
    owner = (payload["subject_id"], payload["session_id"], payload["app_id"], DEVICE_ID)
    store.save([
        {"id": "native-original", "role": "tool_result", "content": "Archived ORIGINAL source content"},
        {"id": "native-archive", "role": "archive_index", "source_ids": ["native-original"]},
    ], owner=json.dumps(owner, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    def factory(**kwargs):
        return build_live_pc_query_driver(compaction_store=store, **kwargs)
    monkeypatch.setattr(fixtures, "build_live_pc_query_driver", factory)
    pc = Endpoint(tmp_path / "output")
    try:
        response, followup, native, _ = run_native(pc, "recall_context", {
            "handle": "native-archive", "source_id": "native-original",
        }, speech="기록을 다시 보여줘")
        assert response.status_code == 200, response.body
        assert response.body["orchestration"]["execution"]["answer"] == "Verified native result."
        assert "Archived ORIGINAL source content" in followup.prompts[-1]
        assert not pc.remote and not pc.dispatches
        assert len(native.requests) == 1
    finally:
        store.close()


@pytest.mark.parametrize("name,args", [
    ("start_job", {"operation": {"op": "write", "path": "notes.txt", "content": "blocked"}}),
    ("batch", {"operations": [{"op": "delete", "path": "notes.txt"}], "stop_on_error": True}),
])
def test_native_wrappers_cannot_widen_read_only_scope(tmp_path, name, args):
    pc = Endpoint(tmp_path)
    response, _, _, _ = run_native(pc, name, args)
    assert response.status_code != 200
    assert response.body["error"]["code"] == "pc_tool_scope_denied"
    assert not pc.remote and not pc.dispatches


def test_native_definitions_reuse_canonical_schemas_and_remove_unoffered_mutations():
    values = {tool.name: tool for tool in definitions({"allowed_scopes": ["files"]})}
    assert set(REMOTE_NAMES) <= set(values)
    specs = {spec.id.removeprefix("claw.pc."): spec for spec in remote_tool_specs()}
    for name in set(REMOTE_NAMES) - {"start_job", "batch"}:
        assert dict(values[name].parameters) == specs[name].input_schema
    for name in ("start_job", "batch"):
        schema = values[name].to_provider_schema()["function"]["parameters"]
        operation = schema["properties"]["operation"] if name == "start_job" else schema["properties"]["operations"]["items"]
        assert list(operation["properties"]["op"]["enum"]) == ["list", "read"]
    drive_names = {tool.name for tool in definitions({"allowed_scopes": ["query_drives"]})}
    assert "start_job" not in drive_names and "batch" not in drive_names


def test_handle_access_reuses_a_supplied_narrow_scope():
    context = {"allowed_scopes": ["files", "files_list", "files_write"]}
    assert _native_remote_scope(context, "claw.pc.read_output", {}) == "files_list"
    with pytest.raises(OrchestrationError):
        _native_remote_scope({"allowed_scopes": ["files_list"]}, "claw.pc.start_job", {"operation": {"op": "read", "path": "notes.txt"}})


def catalog(rows, status=200):
    calls = []
    class Binding:
        async def fetch(self, request):
            calls.append(request)
            async def text():
                return json.dumps({"catalog": rows})
            return SimpleNamespace(status=status, text=text)
    def request(url, **kwargs):
        return SimpleNamespace(js_object=SimpleNamespace(url=url, **kwargs))
    return CatalogToolCapabilities(Binding(), request), calls


@pytest.mark.asyncio
async def test_context_budget_comes_from_same_selected_b14_catalog_row():
    reader, calls = catalog([
        {"id": "other/model", "context_window": 999999, "tags": ["tools"], "pilot_available": True},
        {"id": "selected/model", "context_window": 32768, "tags": ["tools"], "pilot_available": True},
    ])
    assert await reader("selected/model") is True
    assert await reader.context_budget("selected/model") == 32768
    assert await reader.context_budget("missing/model") is None
    assert all(c.url == "https://b14.internal/api/pilot/models" and c.method == "GET" for c in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [None, True, False, 0, -1, "32768", 32768.0])
async def test_unknown_or_invalid_context_budget_does_not_invent_a_threshold(budget):
    reader, _ = catalog([{"id": "selected/model", "context_window": budget}])
    assert await reader.context_budget("selected/model") is None


@pytest.mark.asyncio
async def test_catalog_outage_disables_tools_and_keeps_context_budget_unknown():
    reader, _ = catalog([], status=503)
    assert await reader("selected/model") is False
    assert await reader.context_budget("selected/model") is None
