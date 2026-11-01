"""Real Engine binding/driver/Core steps; only signed PC and B14 sockets are fake."""
import asyncio
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from padiem_ai_core.output_store import OutputStore
from kagent.pc_remote_tools import validate_remote_arguments
from app.pc_remote_tools import make_remote_handler
from app.claw_pc_query_step_driver import _signed_files_call
from tests.test_6460_pc_action_driver import _service, _payload, _WritePcEndpoint
from tests.test_5574_pc_read_boundary_end_to_end import (
    _Response, _Request, _ScriptedModel, _instant_sleep, SIGNING_SECRET, DEVICE_ID,
)

FULL_OUTPUT = "first needle\n" + "large content\n" * 1_600_000 + "last evidence"
HANDLE = "f" * 64


class Endpoint(_WritePcEndpoint):
    def __init__(self, path):
        super().__init__()
        self.store = OutputStore(path)
        self.saved = None
        self.owner = None
        self.remote = []

    async def fetch(self, request):
        data = json.loads(request.body)
        mode = data["mode"]
        if mode in {"read_output", "search_output", "store_output", "job_start", "job_status", "job_output"}:
            stamp = request.headers["X-Claw-Engine-Time"]
            assert request.headers["X-Claw-Engine-Proof"] == hmac.new(
                SIGNING_SECRET.encode(), stamp.encode() + b"." + request.body.encode(), hashlib.sha256).hexdigest()
            assert data["device_id"] == DEVICE_ID
            assert request.headers["X-Claw-PC-Scope"]
            self.remote.append(data)
            if mode == "store_output":
                assert data["source"] == "pc_batch" and data["tool_call_ref"]
                result = self.store.store(data["output"], owner="batch-owner", source="pc_batch")
            elif mode == "read_output":
                result = {"content": self.store.read(self.saved["handle"], owner=self.owner,
                    offset=data["offset"], length=data["length"])}
            elif mode == "search_output":
                result = {"hits": self.store.search(self.saved["handle"], owner=self.owner,
                    pattern=data["query"], max_hits=20)}
            elif mode == "job_start":
                assert data["operation"]["op"] in {"list", "read", "write", "move", "delete"}
                assert data["tool_call_ref"]
                result = {"job_id": "dsp_background", "state": "pending"}
            elif mode == "job_status":
                result = {"job_id": data["job_id"], "state": "done", "exit_code": 0}
            else:
                result = {"job_id": data["job_id"], "content": "finished", "state": "done", "exit_code": 0}
            return _Response({"ok": True, "result": result})
        response = await super().fetch(request)
        if mode == "result":
            result = json.loads(await response.text())
            row = result["dispatch"]
            if row["kind"] == "read":
                self.owner = json.dumps([data["subject_id"], data["run_id"], DEVICE_ID])
                self.saved = self.store.store(FULL_OUTPUT, owner=self.owner, source="pc_read")
                row.update(output=self.saved["head"] + "\n...\n" + self.saved["tail"],
                    content_bytes=len(FULL_OUTPUT.encode()), output_ref=self.saved)
                return _Response(result)
        return response


class ScriptModel(_ScriptedModel):
    def __init__(self, choices, pc):
        self.choices, self.pc, self.prompts = list(choices), pc, []

    async def execute(self, request):
        from types import SimpleNamespace
        from app.pc_work_metrics import current_pc_work_metrics
        self.metrics = current_pc_work_metrics()
        self.prompts.append(request.messages[0]["content"])
        choice = self.choices.pop(0)
        if callable(choice):
            choice = choice(self.pc)
        return SimpleNamespace(answer=json.dumps(choice, ensure_ascii=False))


def tool(name, **args):
    return {"action": "tool", "tool_id": "claw.pc." + name, "arguments": args}


def run(pc, choices, *, write=False, speech="notes.txt 내용을 읽어줘"):
    model = ScriptModel(choices + [{"action": "complete", "answer": "Verified result."}], pc)
    service = _service(model, pc)
    payload = _payload([{"role": "user", "content": speech}], write=write)
    with patch.object(asyncio, "sleep", _instant_sleep):
        response = asyncio.run(service.orchestrate_payload(payload))
    assert response.status_code == 200, response.body
    execution = response.body["orchestration"]["execution"]
    assert execution["metadata"]["status"] == "completed", execution
    return execution, model


def test_large_read_is_stored_and_model_follows_read_and_search_handles(tmp_path):
    pc = Endpoint(tmp_path)
    execution, model = run(pc, [
        tool("read_file", path="notes.txt"),
        lambda pc: tool("read_output", handle=pc.saved["handle"], offset=0, length=12),
        lambda pc: tool("search_output", handle=pc.saved["handle"], query="last evidence"),
    ])
    assert len(FULL_OUTPUT.encode()) > 20_000_000
    assert pc.ops == ["read"]
    assert [item["mode"] for item in pc.remote] == ["read_output", "search_output"]
    assert "last evidence" in model.prompts[-1]
    assert all(len(prompt) < 30000 for prompt in model.prompts)
    assert execution["answer"] == "Verified result."


def test_background_job_receipt_status_and_output_are_reachable(tmp_path):
    pc = Endpoint(tmp_path)
    execution, model = run(pc, [
        tool("start_job", operation={"op": "read", "path": "notes.txt"}),
        tool("job_status", job_id="dsp_background"),
        tool("job_output", job_id="dsp_background", offset=0, length=100),
    ])
    assert [item["mode"] for item in pc.remote] == ["job_start", "job_status", "job_output"]
    assert model.metrics.snapshot()["background_job_count"] == 1
    assert '"state":"pending"' in model.prompts[1].replace(chr(92), "").replace(" ", "")
    assert "finished" in model.prompts[-1]
    assert execution["answer"] == "Verified result."


def test_batch_uses_actual_runner_and_existing_file_handlers(tmp_path):
    pc = Endpoint(tmp_path)
    execution, model = run(pc, [tool("batch", operations=[
        {"op": "list", "path": "."}, {"op": "read", "path": "notes.txt"},
    ], stop_on_error=True)])
    assert pc.ops == ["list", "read"]
    assert "claw.pc.read_file" in model.prompts[-1]
    assert '"completed":2' in model.prompts[-1].replace(chr(92), "").replace(" ", "")
    metrics = model.metrics.snapshot()
    assert metrics["tool_calls"]["claw.pc.list_files"]["calls"] == 1
    assert metrics["tool_calls"]["claw.pc.read_file"]["calls"] == 1
    assert metrics["stored_output_count"] >= 1
    assert execution["answer"] == "Verified result."


def test_mutation_batch_without_user_evidence_dispatches_nothing(tmp_path):
    pc = Endpoint(tmp_path)
    execution, _ = run(pc, [tool("batch", operations=[
        {"op": "write", "path": "notes.txt", "content": "injected"},
        {"op": "delete", "path": "other.txt"},
    ], stop_on_error=False)], write=True, speech="문서 설명해줘")
    assert "?" in execution["answer"]
    assert pc.dispatches == [] and pc.remote == []


@pytest.mark.parametrize("name,args", [
    ("start_job", {"operation": {"op": "shell", "command": "anything"}}),
    ("batch", {"operations": [{"op": "read", "path": "notes.txt", "owner": "attacker"}], "stop_on_error": True}),
    ("read_output", {"handle": HANDLE, "offset": True, "length": 10}),
    ("job_status", {"job_id": "dsp_example", "device_id": "other"}),
])
def test_remote_schema_has_no_owner_command_or_nested_authority(name, args):
    with pytest.raises(ValueError):
        validate_remote_arguments("claw.pc." + name, args)


@pytest.mark.asyncio
async def test_cancelled_batch_never_dispatches_second_step_even_when_stop_on_error_false():
    from types import SimpleNamespace
    from kagent.pc_query_adapter import PC_QUERY_OWNER, PC_QUERY_RUN_SCOPE
    from app.pc_remote_tools import record_remote_admission
    owner = ("subject", "run", "padiem-chat", DEVICE_ID)
    state = {"claim": {"admitted": "files", "ops": ["list", "read"]}}
    entered, exited = asyncio.Event(), asyncio.Event()
    calls = []
    async def read(args):
        calls.append(args["path"])
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()
    async def signed(**kwargs):
        raise AssertionError("No result may be stored after cancellation")
    arguments = {"operations": [{"op": "read", "path": "one.txt"},
                                 {"op": "read", "path": "two.txt"}], "stop_on_error": False}
    owner_token, scope_token = PC_QUERY_OWNER.set(owner), PC_QUERY_RUN_SCOPE.set(state)
    try:
        record_remote_admission(SimpleNamespace(scope_state=state), "claw.pc.batch", arguments)
        handler = make_remote_handler("claw.pc.batch", service=None, request_factory=None,
            secret=None, signed_call=signed, file_handlers={"claw.pc.read_file": read})
        task = asyncio.create_task(handler(arguments))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(exited.wait(), 2)
        await asyncio.sleep(0.05)
        assert calls == ["one.txt"]
    finally:
        PC_QUERY_RUN_SCOPE.reset(scope_token)
        PC_QUERY_OWNER.reset(owner_token)


@pytest.mark.asyncio
@pytest.mark.parametrize("actual,expected_status", [("original", "verified"), ("changed", "failed")])
async def test_durable_background_write_metadata_uses_existing_postcondition_verifier(actual, expected_status):
    import base64
    from app.pc_remote_tools import _job_action_result
    from app.claw_pc_query_step_driver import PC_WRITE_ACCOUNT_PREFIX
    expected = b"original"
    account = {"ok": True, "op": "write", "target": "notes.txt",
        "verification": {"version": 1, "status": "observed", "source_exists": True,
            "target_exists": True, "target_is_file": True,
            "target_bytes": len(actual.encode()), "target_sha256": hashlib.sha256(actual.encode()).hexdigest()}}
    async def signed(**kwargs):
        assert kwargs["mode"] == "result" and kwargs["payload"] == {"dispatch_id": "dsp_durable"}
        return {"ok": True, "dispatch": {"dispatch_id": "dsp_durable", "run_id": "run",
            "kind": "command", "output": PC_WRITE_ACCOUNT_PREFIX + base64.b64encode(json.dumps(account).encode()).decode(),
            "termination": "exited", "exit_code": 0}}
    result = await _job_action_result({"job_id": "dsp_durable", "state": "done",
        "operation": {"op": "write", "path": "notes.txt", "expected_bytes": len(expected),
                      "expected_sha256": hashlib.sha256(expected).hexdigest()}},
        owner=("subject", "run", "padiem-chat", DEVICE_ID), service=None,
        request_factory=None, secret=None, signed_call=signed)
    assert result["action_verification"]["status"] == expected_status
    assert result["source_tool_id"] == "claw.pc.write_file"


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_drive_result_retains_validated_output_handle_and_counts_storage(valid):
    from kagent.pc_query_adapter import PC_QUERY_OWNER, make_query_drives_handler
    from app.claw_pc_query_step_driver import _pc_observing_handler
    from app.pc_work_metrics import PcWorkMetricsCollector, set_pc_work_metrics, reset_pc_work_metrics
    metadata = {"handle": HANDLE, "size": 10000, "head": "first", "tail": "last", "truncated": True}
    class DriveEndpoint:
        async def fetch(self, request):
            body = json.loads(request.body)
            row = {"dispatch_id": "dsp_drive", "run_id": "run", "kind": "command", "device_id": DEVICE_ID}
            if body["mode"] == "command_status":
                row["state"] = "done"
            elif body["mode"] == "result":
                row.update(output="first...last", output_ref=metadata,
                    content_bytes=10000 if valid else 9999,
                    termination="no_exit_code", exit_code=None)
            return _Response({"ok": True, "dispatch": row})
    handler = _pc_observing_handler(make_query_drives_handler(service=DriveEndpoint(),
        request_factory=_Request, secret=SIGNING_SECRET,
        endpoint_url="https://padiem-chat.internal/internal/chat/engine-pc-drive"),
        tool_id="claw.pc.query_drives")
    owner_token = PC_QUERY_OWNER.set(("subject", "run", "padiem-chat", DEVICE_ID))
    collector = PcWorkMetricsCollector("pcturn_" + "1" * 64)
    metric_token = set_pc_work_metrics(collector)
    try:
        with patch.object(asyncio, "sleep", _instant_sleep):
            result = await handler({})
        if valid:
            assert result["output_ref"] == metadata
        else:
            assert result["ok"] is False
        assert collector.snapshot()["stored_output_count"] == int(valid)
    finally:
        reset_pc_work_metrics(metric_token)
        PC_QUERY_OWNER.reset(owner_token)
