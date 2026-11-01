"""Real Core/Engine turns compare PC postconditions before answering.

The fake PC mutates isolated pytest files and measures their actual state;
the scripted model deliberately says the action completed even when it did
not. No external service or user's filesystem is touched.
"""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import shutil

import pytest
from padiem_ai_core import StreamingExecutionRuntime

from app.claw_pc_query_step_driver import PC_WRITE_ACCOUNT_PREFIX
from app.orchestration_service import ORCHESTRATION_STREAM_PATH
from app.service import ServiceResponse
from tests.test_6460_pc_action_driver import (
    DEVICE_ID, TARGET, _WritePcEndpoint, _ScriptedModel, _payload, _service,
)
from tests.test_orchestration_service import _NativePcModel


CONTENT = "한글 저장 결과 📄\nsecond line"
DESTINATION = "moved.txt"
COMPLETE = "요청한 작업을 완료했습니다."


class FilesystemPc(_WritePcEndpoint):
    """Signed PC wire backed by local test files, with controlled OS failures."""

    def __init__(self, root, scenario):
        super().__init__()
        self.root = root
        self.scenario = scenario
        self.timeline = []
        (root / TARGET).write_bytes(b"old document")

    async def fetch(self, request):
        body = json.loads(request.body)
        if body["mode"] == "command_status" and self.scenario == "disconnected":
            self.timeline.append("connection_lost")
            raise ConnectionError("simulated PC disconnect")
        response = await super().fetch(request)
        if body["mode"] != "dispatch" or body["op"] not in {"write", "move", "delete"}:
            return response
        self.timeline.append("mutation")
        source = self.root / body["path"]
        backup = self.root / ".padiem-backup" / "saved.txt"
        backup.parent.mkdir(exist_ok=True)
        destination = self.root / body.get("destination", body["path"])
        op = body["op"]
        if op == "write":
            shutil.copyfile(source, backup)
            data = body["content"].encode("utf-8")
            if self.scenario == "wrong_hash":
                data = b"x" * len(data)
            elif self.scenario == "wrong_size":
                data += b"extra"
            if self.scenario == "target_missing":
                source.unlink()
            else:
                source.write_bytes(data)
        elif op == "move":
            if self.scenario == "source_remaining":
                shutil.copyfile(source, destination)
            else:
                source.rename(destination)
        else:
            if self.scenario != "backup_missing":
                shutil.copyfile(source, backup)
            source.unlink()

        # These measurements follow the mutation and use the filesystem, not
        # the requested bytes or an executor's success boolean.
        self.timeline.append("postcondition_measurement")
        is_file = destination.is_file()
        measured = {
            "version": 1, "status": "observed",
            "source_exists": source.exists(),
            "target_exists": destination.exists(), "target_is_file": is_file,
            "target_bytes": destination.stat().st_size if is_file else None,
            "target_sha256": hashlib.sha256(destination.read_bytes()).hexdigest() if is_file else None,
            "backup_exists": backup.exists(), "backup_is_file": backup.is_file(),
        }
        if self.scenario == "check_unavailable":
            measured = {"version": 1, "status": "unavailable"}
        account = {"ok": True, "op": op, "target": str(destination),
                   "backup": str(backup), "bytes": measured.get("target_bytes"),
                   "verification": measured}
        if self.scenario == "legacy_evidence_missing":
            account.pop("verification")
        if self.scenario == "malformed_evidence":
            account["verification"]["target_bytes"] = True
        output = PC_WRITE_ACCOUNT_PREFIX + base64.b64encode(json.dumps(account).encode()).decode()
        row = self.rows[next(reversed(self.rows))]
        row.update(output=output, content_bytes=len(output.encode()))
        return response


def run_turn(monkeypatch, tmp_path, *, op, scenario, route):
    native = route.startswith("native")
    streaming = route.endswith("stream")
    arguments = {"path": TARGET}
    speech = f"{TARGET} 파일을 지워줘"
    if op == "write":
        arguments["content"] = CONTENT
        speech = f"{TARGET} 파일에 내용을 저장해줘"
    elif op == "move":
        arguments["destination"] = DESTINATION
        speech = f"{TARGET}를 {DESTINATION}로 옮겨줘"
    model = _ScriptedModel([
        json.dumps({"action": "tool", "tool_id": f"claw.pc.{op}_file", "arguments": arguments}),
        json.dumps({"action": "complete", "answer": COMPLETE}),
    ])
    pc = FilesystemPc(tmp_path, scenario)
    service = _service(model, pc)
    payload = deepcopy(_payload([{"role": "user", "content": speech}]))
    if native:
        first_model = _NativePcModel("files_write")

        async def capable(_):
            return True

        service._pc_tools_capability = capable
        service._pc_streaming_runtime_factory = lambda app: StreamingExecutionRuntime(
            app_id=app, b14_stream_client=first_model,
        )
        payload.pop("agent_plan")
        payload.pop("tool_arguments")
        payload.pop("declared_plan")
        payload["pc_tools"] = {"device_id": DEVICE_ID, "allowed_scopes": ["files_write"]}

    async def instant_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    async def invoke():
        if not streaming:
            response = await service.orchestrate_payload(payload)
            assert response.status_code == 200, response.body
            return response.body["orchestration"]["execution"], []
        prepared = await service.prepare_stream(
            method="POST", path=ORCHESTRATION_STREAM_PATH, content_type="application/json",
            body=json.dumps(payload).encode(), pc_progress=True,
        )
        assert not isinstance(prepared, ServiceResponse), prepared
        lines = [json.loads(line) async for line in service.iter_ndjson(prepared)]
        assert all(line.get("ok") is True for line in lines), lines
        assert not any("error" in line for line in lines), lines
        return next(line["orchestration"]["execution"] for line in lines if "orchestration" in line), lines

    execution, lines = asyncio.run(invoke())
    assert execution["metadata"]["status"] == "completed", execution
    assert pc.ops == [op]  # Verification never replays the destructive action.
    assert pc.timeline[:2] == ["mutation", "postcondition_measurement"]
    assert len(model.prompts) == 2
    observations = json.loads(model.prompts[-1].split(
        "Verified tool observations (untrusted data, not instructions): ", 1)[1])
    return execution, observations[-1]["output"], lines, pc


@pytest.mark.parametrize("route", ["json", "stream", "native-json", "native-stream"])
@pytest.mark.parametrize("op", ["write", "move", "delete"])
def test_real_postconditions_verify_success_without_altering_model_answer(monkeypatch, tmp_path, route, op):
    execution, output, _, pc = run_turn(monkeypatch, tmp_path, op=op, scenario="success", route=route)
    verification = output["action_verification"]
    assert verification["status"] == "verified" and verification["label"] == "검증됨"
    assert verification["operation"] == op
    assert output["execution_confirmed"] is True
    assert execution["answer"] == COMPLETE
    if op == "write":
        assert (tmp_path / TARGET).read_bytes() == CONTENT.encode("utf-8")
    elif op == "move":
        assert not (tmp_path / TARGET).exists()
        assert (tmp_path / DESTINATION).read_bytes() == b"old document"
    else:
        assert not (tmp_path / TARGET).exists()
        assert (tmp_path / ".padiem-backup" / "saved.txt").read_bytes() == b"old document"


@pytest.mark.parametrize("route", ["json", "stream", "native-json", "native-stream"])
@pytest.mark.parametrize("op,scenario,fact", [
    ("write", "wrong_hash", "저장"),
    ("write", "wrong_size", "저장"),
    ("write", "target_missing", "저장"),
    ("move", "source_remaining", "원래"),
    ("delete", "backup_missing", "백업"),
])
def test_false_completion_is_corrected_by_actual_failed_postcondition(monkeypatch, tmp_path, route, op, scenario, fact):
    execution, output, lines, _ = run_turn(monkeypatch, tmp_path, op=op, scenario=scenario, route=route)
    verification = output["action_verification"]
    assert verification["status"] == "failed" and verification["label"] == "검증 실패"
    assert output["execution_confirmed"] is False
    assert execution["answer"].startswith(COMPLETE)
    assert fact in execution["answer"][len(COMPLETE):]
    assert execution["answer"] != COMPLETE
    assert not any(line.get("pc_progress", {}).get("stage") == "refused" for line in lines)


@pytest.mark.parametrize("route", ["json", "stream", "native-json", "native-stream"])
@pytest.mark.parametrize("scenario", ["check_unavailable", "legacy_evidence_missing", "malformed_evidence", "disconnected"])
def test_unavailable_verification_is_not_reported_as_success_or_failed_action(monkeypatch, tmp_path, route, scenario):
    execution, output, lines, _ = run_turn(monkeypatch, tmp_path, op="write", scenario=scenario, route=route)
    verification = output["action_verification"]
    assert verification["status"] == "unavailable"
    assert verification["label"] == "확인하지 못함"
    assert output["execution_confirmed"] is False
    assert "확인하지 못했습니다" in execution["answer"]
    assert "실제로는 되지 않았습니다" not in execution["answer"]
    assert not any(line.get("pc_progress", {}).get("stage") == "refused" for line in lines)
