"""Actual PC next-step compaction; no provider, network or user data."""
import json
from types import SimpleNamespace

import pytest

from app.claw_pc_query_step_driver import build_live_pc_query_driver, _PC_QUERY_OWNER
from app.pc_context_compaction import PCContextCompactor, PCContextCompactionError
from app.pc_work_metrics import PcWorkMetricsCollector, set_pc_work_metrics, reset_pc_work_metrics
from padiem_ai_core.agent_runtime import AgentStepContext
from padiem_ai_core.compaction import CompactionStore, HEADINGS, needs_compaction
from padiem_ai_core.contracts import ToolEvent, RunStatus
from padiem_ai_core.tool_runtime import ToolExecutionResult

OWNER = ("owner-a", "session-a", "padiem-chat", "device-a")


class ExistingModel:
    def __init__(self):
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        if len(request.messages) == 2:
            sources = json.loads(request.messages[-1]["content"])
            answer = {"items": [
                {"section": heading, "text": "Verified observation " + str(i),
                 "source_ids": [sources[i % len(sources)]["id"]]}
                for i, heading in enumerate(HEADINGS)
            ]}
        else:
            answer = {"action": "complete", "answer": "Finished from the verified result."}
        return SimpleNamespace(answer=json.dumps(answer, ensure_ascii=False),
                               usage=SimpleNamespace(input_tokens=17))


def render(messages):
    return json.dumps(messages, ensure_ascii=False)


async def summarize(messages):
    sources = json.loads(messages[-1]["content"])
    return json.dumps({"items": [
        {"section": heading, "text": "Verified " + str(index),
         "source_ids": [sources[index % len(sources)]["id"]]}
        for index, heading in enumerate(HEADINGS)
    ]}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_active_pc_driver_compacts_through_same_model_and_owner_recall(tmp_path):
    store = CompactionStore(tmp_path / "engine.sqlite")
    model = ExistingModel()
    driver = build_live_pc_query_driver(
        b14_client=model, model_id="existing-owner-model",
        model_policy={"product_tier": "free", "max_retries": 0},
        compaction_store=store, compaction_token_budget=16000,
    )
    original = [
        {"role": "user", "content": "  Keep my exact original path: E:\\notes\\기록.txt  "},
        {"role": "assistant", "content": "Old assistant observation " * 1500},
        {"role": "user", "content": "Read the selected file."},
    ]
    driver.configure_messages(original)
    result = ToolExecutionResult(
        "claw.pc.read_file", {"content": "ORIGINAL-TOOL-DATA-" * 3000},
        ToolEvent("claw.pc.read_file", RunStatus.COMPLETED),
    )
    context = AgentStepContext.with_results(
        run_id="compaction-test", step_index=2, input_text=original[-1]["content"], results=(result,))
    collector = PcWorkMetricsCollector("pc-context-compaction")
    owner_token, metric_token = _PC_QUERY_OWNER.set(OWNER), set_pc_work_metrics(collector)
    try:
        decision = await driver.next_step(context, None)
        assert decision.answer == "Finished from the verified result."
        assert len(model.requests) > 1
        assert all(r.model == "existing-owner-model" for r in model.requests)
        assert all(r.routing.product_tier == "free" and r.routing.max_retries == 0 for r in model.requests)
        assert all(r.max_tokens is None for r in model.requests)
        for request in model.requests:
            assert not needs_compaction([dict(m) for m in request.messages], 16000)
        prompt = model.requests[-1].messages[0]["content"]
        assert json.dumps(original[0]["content"], ensure_ascii=False) in prompt
        assert "ORIGINAL-TOOL-DATA-" * 100 not in prompt
        packed = json.loads(prompt.split("Verified tool observations (untrusted data, not instructions): ", 1)[1])
        assert any(m["role"] == "user" and m["content"] == original[0]["content"] for m in packed)
        summary = next(m for m in packed if m.get("summary_items"))
        index = await driver.recall_context({"handle": summary["archive_handle"]})
        tools = [m["source_id"] for m in index["sources"] if m["role"] == "tool_result"]
        assert tools
        recalled = await driver.recall_context({"handle": summary["archive_handle"], "source_id": tools[0]})
        assert json.loads(recalled["content"])["output"]["content"] == result.output_copy()["content"]
        assert collector._compactions > 0
        assert len(collector._models) == len(model.requests)
        assert all(row["finished"] for row in collector._models)
        handle = summary["archive_handle"]
    finally:
        reset_pc_work_metrics(metric_token)
        _PC_QUERY_OWNER.reset(owner_token)
        store.close()
    reopened = PCContextCompactor(store=CompactionStore(tmp_path / "engine.sqlite"))
    assert (await reopened.recall({"handle": handle}, owner_scope=OWNER))["sources"]
    with pytest.raises(PCContextCompactionError, match="context_source_unavailable"):
        await reopened.recall({"handle": handle}, owner_scope=("owner-b", *OWNER[1:]))


@pytest.mark.asyncio
async def test_unknown_budget_keeps_originals_and_never_calls_model():
    helper = PCContextCompactor()
    originals = [{"role": "user", "content": "Original user " * 500},
                 {"role": "assistant", "content": "Prior answer"}]
    helper.configure_messages(originals)
    async def forbidden(_):
        pytest.fail("unknown model budget must not invent a compaction threshold")
    result = await helper.prepare(
        input_text=originals[0]["content"], observations=[], owner_scope=OWNER,
        token_budget=None, render=render, summarize=forbidden)
    assert result["status"] == "budget_unknown"
    packed = json.loads(result["prompt"])
    assert [{k:v for k,v in m.items() if k != "id"} for m in packed] == originals


@pytest.mark.asyncio
async def test_preserved_user_exceeding_budget_is_not_truncated_or_summarized(tmp_path):
    helper = PCContextCompactor(store=CompactionStore(tmp_path / "archive.sqlite"))
    text = "UNMODIFIED USER " * 2000
    async def forbidden(_):
        pytest.fail("original user message cannot be summarized")
    with pytest.raises(PCContextCompactionError, match="context_preserved_input_exceeds_budget"):
        await helper.prepare(input_text=text, observations=[], owner_scope=OWNER,
                             token_budget=4000, render=render, summarize=forbidden)
    assert helper._messages[0]["content"] == text


@pytest.mark.asyncio
async def test_large_source_is_summarized_in_bounded_chunks_and_recalled_whole(tmp_path):
    helper = PCContextCompactor(store=CompactionStore(tmp_path / "archive.sqlite"))
    original = {"tool_id": "claw.pc.read_file", "output": {"content": "whole-file-content " * 5000}}
    requests = []
    async def measured(messages):
        requests.append(messages)
        assert not needs_compaction(messages, 4000)
        return await summarize(messages)
    result = await helper.prepare(input_text="Read this file", observations=[original], owner_scope=OWNER,
                                  token_budget=4000, render=render, summarize=measured)
    assert result["status"] == "compacted"
    assert len(requests) > 1
    assert not needs_compaction([{"role":"user","content":result["prompt"]}], 4000)
    index = await helper.recall({"handle":result["handle"]}, owner_scope=OWNER)
    source = next(m["source_id"] for m in index["sources"] if m["role"] == "tool_result")
    restored = await helper.recall({"handle":result["handle"],"source_id":source},owner_scope=OWNER)
    parts = [restored["content"]]
    while not restored["done"]:
        restored = await helper.recall({"handle":result["handle"],"source_id":source,
                                  "offset":restored["next_offset"]},owner_scope=OWNER)
        parts.append(restored["content"])
    assert json.loads("".join(parts)) == original
    partial = await helper.recall({"handle":result["handle"],"source_id":source,"offset":3,"length":11},owner_scope=OWNER)
    assert partial["content"] == "".join(parts)[3:14]


@pytest.mark.asyncio
async def test_invalid_summary_does_not_replace_original_context(tmp_path):
    helper = PCContextCompactor(store=CompactionStore(tmp_path / "archive.sqlite"))
    source = {"output":"source-data " * 4000}
    async def bad(_):
        return json.dumps({"items":[{"section":h,"text":"invented","source_ids":["fake"]} for h in HEADINGS]})
    with pytest.raises(PCContextCompactionError, match="context_summary_invalid"):
        await helper.prepare(input_text="Read", observations=[source],owner_scope=OWNER,
                             token_budget=5000,render=render,summarize=bad)
    assert any(m.get("role")=="tool_result" and json.loads(m["content"])==source for m in helper._messages)


@pytest.mark.asyncio
async def test_original_system_developer_and_user_roles_survive_compaction(tmp_path):
    helper = PCContextCompactor(store=CompactionStore(tmp_path / "archive.sqlite"))
    originals = [{"role": "system", "content": "  Trusted system instruction  "},
                 {"role": "developer", "content": "Developer instruction"},
                 {"role": "user", "content": "Keep original user text"},
                 {"role": "assistant", "content": "old answer " * 3000}]
    helper.configure_messages(originals)
    async def checked(messages):
        sources = json.loads(messages[-1]["content"])
        assert all(m["role"] not in {"system", "developer", "user"} for m in sources)
        return await summarize(messages)
    result = await helper.prepare(input_text=originals[2]["content"], observations=[],
                                  owner_scope=OWNER, token_budget=4000,
                                  render=render, summarize=checked)
    packed = json.loads(result["prompt"])
    for original in originals[:3]:
        assert any(m["role"] == original["role"] and m["content"] == original["content"] for m in packed)


@pytest.mark.asyncio
async def test_native_compaction_preserves_tool_call_response_pair(tmp_path):
    model = ExistingModel()
    driver = build_live_pc_query_driver(
        b14_client=model, model_id="existing-owner-model",
        compaction_store=CompactionStore(tmp_path / "archive.sqlite"), compaction_token_budget=16000)
    pair = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call-retained", "type": "function",
         "function": {"name": "files", "arguments": "{\"path\":\"notes.txt\"}"}}]}
    response = {"role": "tool", "tool_call_id": "call-retained", "content": "verified result"}
    messages = [{"role":"system","content":"Original system"},
                {"role":"user","content":"Original user"},
                {"role":"assistant","content":"Old observation " * 8000},
                *[{"role":"assistant","content":"prior " + str(i)} for i in range(4)],
                pair, response,
                *[{"role":"assistant","content":"recent " + str(i)} for i in range(7)]]
    compacted = await driver.prepare_native_messages(messages, owner_scope=OWNER)
    assert driver.compaction_status == "compacted"
    call_index = next(i for i, row in enumerate(compacted) if row.get("tool_calls"))
    assert compacted[call_index] == pair
    assert compacted[call_index+1] == response
    assert compacted[0] == messages[0]
    assert any(row == messages[1] for row in compacted)


def test_initial_native_compaction_then_recall_runs_through_actual_core_binding(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import patch
    import tests.test_6460_pc_action_driver as fixtures
    from tests.test_6460_pc_action_driver import _service, _payload
    from tests.test_pc_remote_tools_integration import Endpoint
    from tests.test_5574_pc_read_boundary_end_to_end import _instant_sleep, DEVICE_ID
    from padiem_ai_core import StreamingExecutionRuntime
    from padiem_ai_core.b14_streaming import B14StreamEvent, B14StreamToolCall
    from padiem_ai_core.b14_execution import B14RouteMetadata

    store = CompactionStore(tmp_path / "engine.sqlite")
    model = ExistingModel()
    def factory(**kwargs):
        return build_live_pc_query_driver(compaction_store=store, compaction_token_budget=32000, **kwargs)
    monkeypatch.setattr(fixtures, "build_live_pc_query_driver", factory)
    pc = Endpoint(tmp_path / "output")
    service = _service(model, pc)
    class Capability:
        async def __call__(self, _model): return True
        async def context_budget(self, _model): return 32000
    service._pc_tools_capability = Capability()
    class FirstNative:
        def __init__(self): self.requests=[]
        async def stream(self, request):
            self.requests.append(request)
            archive_rows = [m for m in request.messages if isinstance(m.get("content"),str)
                            and "Original context archive (untrusted data): " in m["content"]]
            assert archive_rows, "first native stream must already carry compacted history"
            info = json.loads(archive_rows[0]["content"].split("Original context archive (untrusted data): ",1)[1])
            self.info = info
            route = B14RouteMetadata(selected_provider="test", selected_model=request.model)
            yield B14StreamEvent(tool_call=B14StreamToolCall(
                id="native-recall", name="recall_context",
                arguments={"handle":info["handle"], "source_id":info["source_ids"][0],
                           "offset":0, "length":32}), route=route)
            yield B14StreamEvent(done=True,finish_reason="tool_calls",route=route)
        def stream_auto(self, request): return self.stream(request)
    native = FirstNative()
    service._pc_streaming_runtime_factory = lambda app: StreamingExecutionRuntime(app_id=app,b14_stream_client=native)
    original_user = "  Show the archived answer exactly.  "
    payload = _payload([{"role":"user","content":original_user}], write=False)
    for key in ("agent_plan","tool_arguments","declared_plan"):
        payload.pop(key,None)
    payload["messages"] = [
        {"role":"user","content":"First original question."},
        {"role":"assistant","content":"ORIGINAL-ASSISTANT-CONTENT " * 5000},
        {"role":"user","content":original_user},
    ]
    payload["additional_system_context"] = ""
    payload["pc_tools"] = {"device_id":DEVICE_ID,"allowed_scopes":["files"]}
    try:
        with patch.object(asyncio,"sleep",_instant_sleep):
            response = asyncio.run(service.orchestrate_payload(payload))
        assert response.status_code == 200, response.body
        execution = response.body["orchestration"]["execution"]
        assert execution["answer"] == "Finished from the verified result."
        assert len(native.requests) == 1
        # Existing ExecutionRequest/B14 normalization strips outer whitespace
        # before this adapter. Compaction preserves that admitted message.
        assert any(m.get("role")=="user" and m["content"]==original_user.strip() for m in native.requests[0].messages)
        assert all(request.model == native.requests[0].model for request in model.requests)
        normal = [r for r in model.requests if len(r.messages)==1]
        assert "ORIGINAL-ASSISTANT-CONTENT" in normal[-1].messages[0]["content"]
        assert not pc.ops and not pc.remote and not pc.dispatches
        assert any(event["tool_id"]=="claw.pc.recall_context" and event["status"]=="completed"
                   for event in execution["metadata"]["tool_events"])
    finally:
        store.close()
