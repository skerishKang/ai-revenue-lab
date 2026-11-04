"""2026-11-04 — PC file tools answer early and continue by job id.

Two changes are pinned here:

* a folder listing is one page of 50 rows, so the reply the PC has to carry
  stays small (the transfer, not the command, is what costs seconds);
* pc_list and pc_read may hand back the dispatch they started, and the same
  tool continues it. That continuation must never stage a second dispatch, and
  a job id belonging to another user, token or PC is refused.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient

from app import mcp_gateway_execution as execution
from app import mcp_gateway_transport as transport
from app import oracle_mesh_read_return_routes as routes
from app.orchestration_bridge import B62EngineOrchestrationBridge

ROOT = "C:/Users/limone/AppData/Local/Padiem/MeshCentralTrial"
UID = "usr_" + "a" * 32
OTHER_UID = "usr_" + "b" * 32
DEVICE = "dev_" + "c" * 32
OTHER_DEVICE = "dev_" + "d" * 32
TOKEN = "mcp_token_fixture"
JOB = "dsp_" + "e" * 32
RUN = "run_" + "f" * 24


def test_folder_listing_is_a_page_of_fifty_rows():
    assert routes.PC_FILES_LIST_PAGE_SIZE == 50
    command = routes._pc_files_command(op="list", root=ROOT, relative=".")
    assert "Select-Object -Skip 0 -First 50" in command
    # The four fields the model sees: name, kind, size, modified time.
    assert "Select-Object Name, Length, LastWriteTimeUtc, PSIsContainer" in command
    assert "total=$n" in command and "has_more=" in command
    # A caller may still ask for a different page; the default is what shrank.
    explicit = routes._pc_files_command(op="list", root=ROOT, relative=".", page_size=200)
    assert "Select-Object -Skip 0 -First 200" in explicit


def test_job_id_is_a_closed_argument_of_the_read_only_file_tools():
    assert transport.validate_tool_arguments("pc_list", {"job_id": JOB})
    assert transport.validate_tool_arguments("pc_read", {"job_id": JOB})
    # A continuation is the job id and nothing else.
    assert not transport.validate_tool_arguments("pc_list", {"path": ".", "job_id": JOB})
    assert not transport.validate_tool_arguments("pc_list", {"job_id": "dsp_not-a-dispatch"})
    # 261105: a bare pc_list is a request for the approved folder list, so the
    # caller can name a relative path at all. Every other tool still needs one.
    assert transport.validate_tool_arguments("pc_list", {})
    assert not transport.validate_tool_arguments("pc_read", {})
    # A mutation must report its own verification, so it never continues by id.
    assert not transport.validate_tool_arguments("pc_write", {"job_id": JOB})
    assert not transport.validate_tool_arguments("pc_search", {"job_id": JOB})
    # The existing path call is unchanged.
    assert transport.validate_tool_arguments("pc_list", {"path": "."})


class _Transport:
    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return EngineTransportResponse(status=200, headers={}, body=json.dumps({"ok": True,
            "orchestration": {"events": [{"event_id": "event_fixture", "run_id": RUN,
                "trace_id": "trace_fixture", "app_id": "padiem-chat",
                "kind": "run_completed", "sequence": 1}],
                "execution": {"answer": json.dumps({
                    "status": "completed", "answer": "PC 폴더 목록을 읽었습니다.",
                    "output": "{}"})}}}).encode())


class _History:
    def __init__(self, row=None, run=None):
        self.row = row
        self.run = run
        self.runs = []

    async def get_pc_output_dispatch_for_owner(self, *, user_id, dispatch_id):
        return self.row

    async def get_claw_run(self, uid, run_id):
        return self.run

    async def record_chat_pc_drive_run(self, **kwargs):
        self.runs.append(kwargs)
        return "conv_fixture"


class _McpStore:
    def __init__(self, owned=True):
        self.owned = owned

    async def owns_job_receipt(self, *, identity, job_id):
        return self.owned


def _harness(monkeypatch, *, row, run=None, owned=True):
    async def owner(request, uid):
        return SimpleNamespace(session_id="session_fixture"), "sub_" + "a" * 32, "workspace_fixture"

    async def context(request, **kwargs):
        return SimpleNamespace(selected_confirmed=True, tool_available=True,
            selection_offline=False, selected_device_id=DEVICE,
            execution_device_id=DEVICE)

    async def grant(request, session, **kwargs):
        return True

    async def delegation(request, uid):
        return {"version": 1, "rules": []}

    async def notice(*args, **kwargs):
        return True

    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution, "load_pc_delegation", delegation)
    monkeypatch.setattr(execution, "_append_lane_notice", notice)
    # The real plan and target hint are used: a continuation must reach the
    # Engine through the same canonical plan the first call used.
    engine, history = _Transport(), _History(row=row, run=run)
    bridge = B62EngineOrchestrationBridge(
        client=PadiemAiEngineClient(transport=engine, app_id="padiem-chat",
                                    caller_id="padiem-chat", credential="fixture" * 8),
        store=object())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge, history_store=history,
        mcp_gateway_store=_McpStore(owned))))
    principal = {"owner_id": UID, "device_id": DEVICE, "token_id": TOKEN}
    return request, engine, history, principal


def _owned_row(**overrides):
    row = {"dispatch_id": JOB, "user_id": UID, "device_id": DEVICE, "kind": "command",
           "run_id": RUN}
    row.update(overrides)
    return row


def test_owned_job_continues_on_the_run_it_already_belongs_to(monkeypatch):
    request, engine, history, principal = _harness(
        monkeypatch, row=_owned_row(), run={"run_id": RUN, "conversation_id": "conv_fixture"})
    result = asyncio.run(execution.execute_mcp_pc_tool(request, principal, "pc_list",
                                                       {"job_id": JOB}))

    assert result["status"] == "completed"
    # No second dispatch, no second run row: the continuation reads that one.
    assert not history.runs
    assert len(engine.calls) == 1
    sent = json.loads(engine.calls[0]["body"])
    assert sent["session_id"] == RUN
    assert sent["pc_gateway"]["arguments"] == {"job_id": JOB}
    assert sent["pc_gateway"]["tool_id"] == "claw.pc.list_files"
    assert sent["pc_gateway"]["source"] == "mcp"


@pytest.mark.parametrize("row,owned", [
    (_owned_row(user_id=OTHER_UID), True),
    (_owned_row(device_id=OTHER_DEVICE), True),
    (_owned_row(kind="desktop"), True),
    (_owned_row(), False),
    (None, True),
])
def test_foreign_job_is_refused_before_the_engine_is_asked(monkeypatch, row, owned):
    request, engine, history, principal = _harness(
        monkeypatch, row=row, run={"run_id": RUN, "conversation_id": "conv_fixture"},
        owned=owned)
    result = asyncio.run(execution.execute_mcp_pc_tool(request, principal, "pc_read",
                                                       {"job_id": JOB}))

    assert result["status"] == "denied"
    assert result["code"] == "pc_job_not_owned"
    assert not engine.calls
    assert not history.runs
