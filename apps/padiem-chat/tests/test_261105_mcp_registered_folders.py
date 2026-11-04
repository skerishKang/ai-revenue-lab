"""261105: pc_list가 등록 폴더를 먼저 알려주고, 절대 경로를 상대 경로로 바꾼다.

06:03 재시험에서 `pc_list D:\\`는 "등록된 폴더 기준 상대경로만 허용"으로, `pc_list .`은
`pc_files_path_invalid`로 끝났다. 호출자는 이 PC에 어떤 폴더가 등록되어 있는지 알 수
없었고, 도구 설명도 절대 경로를 넣도록 유도했다. 등록 폴더는 Chat이 이미 Engine의
서명된 context 호출에 돌려주는 값이므로, 같은 권위로 MCP 응답에서도 알려 준다.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient

from app import mcp_gateway_execution as execution
from app import mcp_gateway_transport as transport
from app.orchestration_bridge import B62EngineOrchestrationBridge

UID = "usr_" + "a" * 32
DEVICE = "dev_" + "c" * 32
PRINCIPAL = {"owner_id": UID, "device_id": DEVICE, "token_id": "mcp_token_fixture"}
ROOTS = [{"name": "PADIEM", "path": "D:/PADIEM"}, {"name": "D:", "path": "D:"}]


class RecordingTransport:
    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return EngineTransportResponse(status=200, headers={}, body=json.dumps({
            "ok": True,
            "orchestration": {
                "events": [{"event_id": "event_fixture", "run_id": "run_fixture",
                            "trace_id": "trace_fixture", "app_id": "padiem-chat",
                            "kind": "run_completed", "sequence": 1}],
                "execution": {"answer": json.dumps(
                    {"status": "completed", "answer": "확인했습니다."})},
            },
        }).encode())


class History:
    def __init__(self):
        self.runs = []

    async def record_chat_pc_drive_run(self, **kwargs):
        self.runs.append(kwargs)
        return "conv_fixture"


def harness(monkeypatch, *, roots=None):
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

    async def folders(request, *, session, user_id, device_id):
        return list(ROOTS if roots is None else roots)

    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution, "load_pc_delegation", delegation)
    monkeypatch.setattr(execution, "_append_lane_notice", notice)
    monkeypatch.setattr(execution, "_registered_pc_folders", folders)
    recorder = RecordingTransport()
    bridge = B62EngineOrchestrationBridge(
        client=PadiemAiEngineClient(transport=recorder, app_id="padiem-chat",
                                    caller_id="padiem-chat", credential="fixture" * 8),
        store=object(),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge, history_store=History())))
    return request, recorder


def _call(monkeypatch, tool, arguments, *, roots=None):
    request, recorder = harness(monkeypatch, roots=roots)
    result = asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, tool, arguments))
    return result, recorder


def test_pc_list_without_a_path_lists_the_registered_folders(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_list", {})
    assert result["status"] == "completed"
    assert result["folders"] == ROOTS
    assert result["output"]["entry_count"] == len(ROOTS)
    assert "PADIEM" in result["answer"] and "D:" in result["answer"]
    assert recorder.calls == []


def test_pc_list_with_a_root_slash_lists_the_registered_folders(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_list", {"path": "/"})
    assert result["status"] == "completed"
    assert result["folders"] == ROOTS
    assert recorder.calls == []


def test_pc_list_dot_with_several_folders_lists_them(monkeypatch):
    # "." can only mean one folder when the account has one grant; with two the
    # caller has to be told which names exist instead of guessing.
    result, recorder = _call(monkeypatch, "pc_list", {"path": "."})
    assert result["status"] == "completed"
    assert result["folders"] == ROOTS
    assert recorder.calls == []


def test_an_absolute_path_inside_a_folder_is_sent_relative(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_list", {"path": "D:\\PADIEM\\x"})
    assert result["status"] == "completed"
    sent = json.loads(recorder.calls[0]["body"])
    assert sent["pc_gateway"]["arguments"]["path"] == "PADIEM/x"


def test_the_deepest_grant_wins_when_two_cover_the_same_path(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_read", {"path": "D:\\PADIEM\\a\\b.txt"})
    assert result["status"] == "completed"
    sent = json.loads(recorder.calls[0]["body"])
    assert sent["pc_gateway"]["arguments"]["path"] == "PADIEM/a/b.txt"


def test_a_path_outside_every_folder_is_refused_with_the_list(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_list", {"path": "C:\\other"})
    assert result["status"] == "failed"
    assert result["code"] == "pc_path_outside_registered_roots"
    assert result["folders"] == ROOTS
    assert recorder.calls == []


def test_reading_the_folder_itself_is_refused_with_the_list(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_read", {"path": "D:\\PADIEM"})
    assert result["status"] == "failed"
    assert result["code"] == "pc_path_outside_registered_roots"
    assert result["folders"] == ROOTS
    assert recorder.calls == []


def test_a_move_destination_outside_the_folders_is_refused(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_move",
                             {"path": "D:\\PADIEM\\a.txt", "destination": "C:\\a.txt"})
    assert result["status"] == "failed"
    assert result["code"] == "pc_path_outside_registered_roots"
    assert recorder.calls == []


def test_pc_list_is_an_unresolved_path_when_folders_cannot_be_read(monkeypatch):
    # The folder read is the same authority the Engine asks; when it cannot
    # answer, the previous behaviour stays and no list is invented.
    result, recorder = _call(monkeypatch, "pc_list", {}, roots=[])
    assert result["status"] == "unavailable"
    assert result["code"] == "pc_registered_folders_unavailable"
    assert recorder.calls == []


def test_transport_accepts_pc_list_with_no_arguments():
    assert transport.validate_tool_arguments("pc_list", {}) is True
    assert transport.validate_tool_arguments("pc_read", {}) is False
    assert transport.validate_tool_arguments("pc_list", {"path": "/"}) is True


def test_each_file_tool_description_points_at_the_folder_list():
    for name in ("pc_list", "pc_read", "pc_write", "pc_search"):
        description = transport._TOOLS[name]["description"]
        assert "등록" in description
        if name != "pc_list":
            # Only pc_list answers the list; every other tool sends the caller
            # there first instead of suggesting an absolute path.
            assert "pc_list" in description
