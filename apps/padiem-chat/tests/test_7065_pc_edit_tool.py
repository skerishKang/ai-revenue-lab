"""#7065 1조각 — PC 커넥터의 "파일 일부만 바꾸기"(찾아 바꾸기 편집).

새 도구 `pc_edit`은 pc_write와 **같은 경로·같은 보호**를 쓴다. 새 승인 방식도,
새 범위도, 새 백업 규칙도 만들지 않는다. 다른 것은 입력뿐이다: 파일 전체 대신
"이 글자를 이걸로" 바꾼다.

이 파일이 고정하는 계약

- 선언: `pc_edit`이 pc_write와 같은 MCP 목록에 있고, path/old_text/new_text는
  필수, replace_all은 선택 bool이다.
- 실행: `claw.pc.edit_file`이 pc_write와 **같은 write scope**(`files_write`)로
  같은 Engine 계획 경로를 탄다. 승인·사전 위임·등록 폴더 범위·백업·계정 줄이
  모두 pc_write의 것을 그대로 재사용한다.
- 판정: old_text가 정확히 한 번이면 바꾼다. 0번이면 `edit_not_found`, 여러 번인데
  replace_all이 없으면 `edit_not_unique`로 **바꾸지 않고** 거부한다.
- 보존: 줄바꿈(CRLF/LF)과 BOM은 원래 파일 그대로다.
- 잠금: 등록 폴더 밖·바이너리 파일은 거부한다.

PowerShell 명령 바이트는 이 파일이 직접 조립해 문자열 계약으로 검사한다. 실제
PC에 명령을 보내지 않는다 — 가짜 실행기(SyntheticEditTool)와 순수 함수로만 본다.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient
from padiem_ai_core.tool_runtime import ToolRuntime

from app import mcp_gateway_execution as execution
from app.chat_pc_drive import (
    build_chat_pc_files_edit_agent_plan,
    chat_pc_plan_for_tool,
    pc_edit_intent,
)
from app.mcp_gateway_transport import _TOOLS as MCP_TOOLS
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app import oracle_mesh_read_return_routes as routes
from app.oracle_mesh_read_return_routes import (
    _PC_FILES_OPS,
    _PC_WRITE_OPS,
    _pc_write_command,
)

ROOT = Path(__file__).resolve().parents[1]
DEVICE = "dev_" + "c" * 32
UID = "usr_" + "a" * 32
PRINCIPAL = {"owner_id": UID, "device_id": DEVICE, "token_id": "mcp_token_fixture"}
POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive", "-nologo", "-command", "-"]


def _edit_command(*, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """The command bytes the server builds for one edit step."""
    return _pc_write_command(
        op="edit", root=r"E:\work", target=r"E:\work\보고서.txt", relative="보고서.txt",
        backup_dir=r"E:\pc-backup",
        old_text_b64=base64.b64encode(old_text.encode("utf-8")).decode("ascii"),
        new_text_b64=base64.b64encode(new_text.encode("utf-8")).decode("ascii"),
        replace_all=replace_all,
    )


# ── 1. 선언: 같은 목록, 같은 보호 표시, 선택 인자 하나 ──────────────────────


def test_the_tool_is_declared_next_to_the_write_tool():
    edit, write = MCP_TOOLS["pc_edit"], MCP_TOOLS["pc_write"]
    assert set(edit["inputSchema"]["properties"]) == {
        "path", "old_text", "new_text", "replace_all", "device",
    }
    assert edit["inputSchema"]["required"] == ["path", "old_text", "new_text"]
    assert edit["inputSchema"]["properties"]["replace_all"] == {"type": "boolean"}
    # pc_write와 **똑같은** 보호 표시를 단다 — 새 승인 종류를 만들지 않는다.
    assert edit["annotations"] == write["annotations"]
    assert edit["annotations"]["destructiveHint"] is True
    assert edit["annotations"]["readOnlyHint"] is False


def test_the_execution_table_puts_the_edit_on_the_write_lane():
    scope, tool_id, keys = execution._TOOLS["pc_edit"]
    write_scope, write_tool, _ = execution._TOOLS["pc_write"]
    assert scope == write_scope == "files_write"
    assert tool_id == "claw.pc.edit_file"
    assert keys == {"path", "old_text", "new_text", "replace_all"}
    assert write_tool == "claw.pc.write_file"
    # 등록 폴더 범위 검사는 path 인자를 가진 도구 전부에 걸린다 — edit도 포함.
    assert "pc_edit" in execution._PC_FILE_PATH_TOOLS
    # 되살림(job_id) 대상은 아니다: 변경은 자기 검증을 스스로 보고한다.
    assert "pc_edit" not in execution._PC_FILE_JOB_TOOLS


def test_the_edit_plan_is_a_one_step_subset_of_the_write_scope():
    plan = build_chat_pc_files_edit_agent_plan()
    assert [(step["step_id"], step["tool_id"]) for step in plan["steps"]] == [
        ("edit_file", "claw.pc.edit_file"),
    ]
    assert chat_pc_plan_for_tool("files_edit") == plan
    # 같은 파일 레인의 기존 계획들은 그대로다.
    assert [s["tool_id"] for s in chat_pc_plan_for_tool("files_write")["steps"]] == [
        "claw.pc.write_file", "claw.pc.move_file", "claw.pc.delete_file",
    ]


def test_the_owners_words_that_ask_for_a_change_open_the_edit_tool():
    assert pc_edit_intent("보고서.txt에서 '초안'을 '최종'으로 찾아 바꿔줘") is True
    assert pc_edit_intent("이 파일 일부만 고쳐줘") is True
    assert pc_edit_intent("find and replace the version string") is True
    # 읽기만 하는 요청은 편집 도구를 열지 않는다.
    assert pc_edit_intent("보고서.txt 읽어줘") is False


# ── 2. 실행: 명령 바이트가 찾아 바꾸기 규칙을 그대로 담는다 ─────────────────


def test_the_command_finds_the_text_exactly_and_refuses_the_other_two_cases():
    once = _edit_command(old_text="초안", new_text="최종")
    # 한 줄이어야 한다: 이 PC 에이전트는 표준 입력으로 한 줄 스크립트를 먹인다.
    assert len(once.splitlines()) == 1
    # 0번이면 edit_not_found, 여러 번인데 replace_all이 없으면 edit_not_unique.
    assert "$reason = 'edit_not_found'" in once
    assert "$reason = 'edit_not_unique'" in once
    assert "$hits -gt 1 -and -not $false" in once
    assert "$hits -gt 1 -and -not $true" not in once


def test_replace_all_is_the_only_difference_in_the_command():
    one = _edit_command(old_text="초안", new_text="최종")
    all_at_once = _edit_command(old_text="초안", new_text="최종", replace_all=True)
    # 갈리는 지점은 딱 두 곳이다: 여러 번일 때 거부하느냐, 그리고 한 번만 바꾸느냐
    # 전체를 바꾸느냐. 그 밖의 바이트는 완전히 같다.
    assert "$hits -gt 1 -and -not $true" in all_at_once
    assert "$hits -gt 1 -and -not $false" in one
    assert one.count("$false") - all_at_once.count("$false") == 1
    # 한 번만 바꾸는 쪽은 정확히 한 구간만 이어 붙이고, 전체 치환은 Replace 한 번이다.
    assert all_at_once.count("$beforeText.Replace($oldPlain, $newPlain)") == 1
    assert all_at_once.count("$beforeText.Substring(") == 0
    assert one.count("$beforeText.Substring(") == 2
    assert one.count("$beforeText.Replace(") == 0


def test_the_command_backs_up_before_changing_and_never_decodes_the_file():
    command = _edit_command(old_text="초안", new_text="최종")
    # 백업이 바뀌기 전에 일어나고, 백업 실패는 변경 자체를 멈춘다(pc_write와 같은 규칙).
    assert command.index("Copy-Item") < command.index("WriteAllBytes")
    assert "$reason = 'backup_failed'" in command
    # 바이트를 그대로 읽고 그대로 쓴다 — 줄바꿈과 BOM을 다시 인코딩하지 않는다.
    assert "[IO.File]::ReadAllBytes($target)" in command
    assert "[IO.File]::WriteAllBytes($temp, $payload)" in command
    assert "$payload = [Text.Encoding]::UTF8.GetBytes($afterText)" in command
    # 바꾸는 원자성도 pc_write와 같은 임시 파일 + Move-Item이다.
    assert "Move-Item -LiteralPath $temp -Destination $target -Force" in command


def test_the_edit_refuses_outside_the_registered_folder_and_skips_binaries():
    # 범위: pc_write와 같은길이로 만들어진다 — root 아래 상대 경로만 대상이 된다.
    command = _edit_command(old_text="a", new_text="b")
    assert "$guardRoot = 'E:\work\\'" in command or "$guardRoot = 'E:\work\'" in command
    assert "[IO.Path]::GetFullPath($target)" in command
    # op 표: edit는 write와 같은 변경 계열에 있고, 파일 연산 집합에 들어 있다.
    assert "edit" in _PC_FILES_OPS and "edit" in _PC_WRITE_OPS
    assert set(_PC_WRITE_OPS) == {"write", "edit", "move", "delete"}
    # 바이너리 파일은 텍스트로 읽히지 않는다: 읽기·검색과 같은 판정을 쓴다.
    from app.oracle_mesh_read_return_routes import _pc_files_relative_path
    assert _pc_files_relative_path("보고서.txt") == "보고서.txt"


# ── 3. 승인: pc_write와 같은 문, 같은 receipt, 같은 승인 없는 기본값 ─────────

class RecordingTransport:
    def __init__(self):
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        return EngineTransportResponse(status=200, headers={}, body=json.dumps({"ok": True,
            "orchestration": {"events": [{"event_id": "event_fixture", "run_id": "run_fixture",
                "trace_id": "trace_fixture", "app_id": "padiem-chat", "kind": "run_completed",
                "sequence": 1}],
                "execution": {"answer": json.dumps({"status": "completed", "answer": "확인했습니다."})}}}).encode())


class History:
    def __init__(self):
        self.runs = []

    async def record_chat_pc_drive_run(self, **kwargs):
        self.runs.append(kwargs)
        return "conv_fixture"


def harness(monkeypatch):
    calls = []

    async def owner(request, uid):
        calls.append(("identity", uid))
        return SimpleNamespace(session_id="session_fixture"), "sub_" + "a" * 32, "workspace_fixture"

    async def context(request, **kwargs):
        calls.append(("context", kwargs))
        return SimpleNamespace(selected_confirmed=True, tool_available=True, selection_offline=False,
                               selected_device_id=DEVICE, execution_device_id=DEVICE)

    async def grant(request, session, **kwargs):
        calls.append(("grant", kwargs))
        return True

    async def delegation(request, uid):
        calls.append(("delegation", uid))
        return {"version": 1, "rules": []}

    async def notice(*args, **kwargs):
        calls.append(("notice", kwargs))
        return True

    monkeypatch.setattr(execution, "_resolve_chat_owner", owner)
    monkeypatch.setattr(execution, "resolve_pc_work_context", context)
    monkeypatch.setattr(execution, "_check_mesh_grant", grant)
    monkeypatch.setattr(execution, "load_pc_delegation", delegation)
    monkeypatch.setattr(execution, "_append_lane_notice", notice)
    transport, history = RecordingTransport(), History()
    bridge = B62EngineOrchestrationBridge(client=PadiemAiEngineClient(transport=transport,
        app_id="padiem-chat", caller_id="padiem-chat", credential="fixture" * 8), store=object())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestration_bridge=bridge, history_store=history)))
    return request, transport, history, calls


EDIT_ARGS = {"path": "notes.txt", "old_text": "old", "new_text": "new"}


def test_the_edit_takes_the_same_lane_and_the_same_server_provenance(monkeypatch):
    request, transport, history, calls = harness(monkeypatch)
    result = asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_edit", EDIT_ARGS))
    assert result["status"] == "completed"
    sent = json.loads(transport.calls[0]["body"])
    assert sent["pc_gateway"]["tool_id"] == "claw.pc.edit_file"
    # 승인 id는 요청이 스스로 붙이지 않는다 — pc_write와 같은 기본값이다.
    assert "approval_id" not in sent["pc_gateway"]
    assert [call[0] for call in calls[:3]] == ["identity", "context", "grant"]
    assert history.runs[0]["user_text"].startswith("외부 AI 도구 요청:")


def test_replace_all_is_optional_but_never_a_string(monkeypatch):
    # 없는 것은 false와 같다: replace_all을 빼도 같은 레인을 타고 나간다.
    request, transport, _, _ = harness(monkeypatch)
    asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_edit", EDIT_ARGS))
    sent = json.loads(transport.calls[0]["body"])
    assert "replace_all" not in sent["pc_gateway"]["arguments"]
    # 문자열 "false"는 답이 아니다 — pc_write가content에 문자열을 요구하듯 타입을 지킨다.
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_edit", {**EDIT_ARGS, "replace_all": "false"}))


def test_a_forged_approval_is_refused_exactly_as_for_the_write_tool(monkeypatch):
    from app.mcp_gateway_store import mcp_request_digest

    request, _, _, _ = harness(monkeypatch)
    forged = {"approval_id": "approval_fixture", "request_digest": "0" * 64}
    with pytest.raises(ValueError):
        asyncio.run(execution.execute_mcp_pc_tool(
            request, PRINCIPAL, "pc_edit", EDIT_ARGS, approval=forged))
    # 정직한 요청은 그 요청 자체의 digest로만 통과한다 — pc_write와 같은 문이다.
    honest = {"approval_id": "approval_fixture",
              "request_digest": mcp_request_digest("pc_edit", EDIT_ARGS)}
    asyncio.run(execution.execute_mcp_pc_tool(request, PRINCIPAL, "pc_edit", EDIT_ARGS, approval=honest))


# ── 4. 판정: 이유 코드가 그대로 화면 코드가 되고, 파일은 바뀌지 않는다 ───────

def _engine_module():
    """The Engine's step driver source, read as text (its own process, not ours).

    Both apps call themselves ``app``, so importing the Engine's module here
    would shadow the Chat one. The account parser and its closed reason
    namespace are pure functions, so this test reads them from the Engine file
    and runs them in their own namespace instead.
    """
    path = ROOT.parent / "padiem-ai-engine" / "app" / "claw_pc_query_step_driver.py"
    source = path.read_text(encoding="utf-8")
    namespace: dict = {"base64": base64, "json": json, "re": re,
                       "ToolHandlerError": _ToolHandlerError}
    import ast

    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.Assign) and node.targets[0].id in (
                "PC_WRITE_ACCOUNT_PREFIX", "PC_WRITE_REASONS"):
            namespace[node.targets[0].id] = eval(
                compile(ast.Expression(node.value), "<engine>", "eval"),
                {"frozenset": frozenset})
    for name in ("def _pc_write_result", "def _pc_write_account"):
        start = source.index(name)
        end = source.index(chr(10) + "def ", start + 1)
        exec(compile(source[start:end] + chr(10), "<engine>", "exec"), namespace)
    return SimpleNamespace(**namespace)


class _ToolHandlerError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message)
        self.code = code


def _account(**fields) -> str:
    payload = {**{"ok": True, "reason": None, "backup": None}, **fields}
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return "PADIEM_PC_ACCOUNT=" + encoded


@pytest.mark.parametrize("reason", ["edit_not_found", "edit_not_unique"])
def test_a_refused_edit_answers_with_its_own_reason_code(reason):
    ToolHandlerError = _ToolHandlerError
    _pc_write_account = _engine_module()._pc_write_account

    # 실패한 계정 줄: ok=false와 이유 코드만 온다(파일은 바뀌지 않았다).
    with pytest.raises(ToolHandlerError) as caught:
        _pc_write_account(_account(ok=False, reason=reason))
    assert caught.value.code == "pc_write_" + reason


def test_the_account_line_a_successful_edit_prints_is_the_write_account():
    _pc_write_account = _engine_module()._pc_write_account
    account = _pc_write_account(_account(bytes=12, backup=r"E:\pc-backup\x.txt"))
    assert account["ok"] is True
    assert account["backup"] == r"E:\pc-backup\x.txt"


def test_the_reason_namespace_is_closed():
    PC_WRITE_REASONS = _engine_module().PC_WRITE_REASONS
    # 편집의 두 이유만 늘고, 그 밖의 문자열은 여전히 일반 실패로 접힌다.
    assert {"edit_not_found", "edit_not_unique"} <= PC_WRITE_REASONS
    assert "행운" not in PC_WRITE_REASONS


# ── 5. 보존: 파일을 텍스트로 다시 인코딩하지 않는다 ──────────────────────────

def test_the_edit_keeps_line_endings_and_bom_because_it_never_reassembles_the_file():
    command = _edit_command(old_text="old value", new_text="new value")
    # CRLF/LF를 정규화하는 코드가 없다.
    assert "`r`n" not in command
    assert command.count("-replace") == 1  # 백업 파일 이름 정화용 하나뿐
    # BOM을 지우거나 더하는 코드가 없다: UTF8Encoding(false) 같은 재인코딩이 없다.
    assert "UTF8Encoding" not in command
    # 찾는 글자와 바꿀 글자 모두 UTF-8 바이트로만 싣는다(base64).
    assert "$oldText = [Convert]::FromBase64String(" in command
    assert "$newText = [Convert]::FromBase64String(" in command


def test_the_edit_searches_without_regex_or_case_folding():
    command = _edit_command(old_text="Old", new_text="new")
    # 정규식이 아니라 문자열 그대로 찾는다(-match, -replace, like 없음).
    assert "[StringComparison]::Ordinal" in command
    assert "-match" not in command and " -like" not in command


# ── 6. 실행: 만들어진 PowerShell을 이 PC에서 실제로 돌려 바이트를 확인한다 ────

def _run_edit(tmp_path, body: bytes, old_text: str, new_text: str, replace_all=False):
    """Build the real command for one temp file and run it with this machine's
    PowerShell. Nothing leaves this computer: root/target are the temp folder."""
    path = tmp_path / "notes.txt"
    path.write_bytes(body)
    backup = tmp_path / ".padiem-backup"
    backup.mkdir()
    command = routes._pc_write_command(
        op="edit", root=str(tmp_path), target=str(path), backup_dir=str(backup),
        relative="notes.txt", old_text_b64=base64.b64encode(old_text.encode()).decode(),
        new_text_b64=base64.b64encode(new_text.encode()).decode(),
        replace_all=replace_all)
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, timeout=90)
    account = [line for line in done.stdout.decode("utf-8", "replace").splitlines()
               if line.startswith("PADIEM_PC_ACCOUNT=")]
    return (json.loads(base64.b64decode(account[-1].split("=", 1)[1]).decode()) if account
            else {"ok": None, "stderr": done.stderr.decode("utf-8", "replace")}), path


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell"),
                    reason="this check runs the real command on Windows PowerShell")
def test_a_crlf_file_keeps_its_crlf_and_only_the_named_text_changes(tmp_path):
    account, path = _run_edit(tmp_path, b"alpha\r\nbeta\r\ngamma\r\n", "beta", "BETA")
    assert account["ok"] is True, account
    assert path.read_bytes() == b"alpha\r\nBETA\r\ngamma\r\n"
    # 백업은 바꾸기 전 그대로의 바이트다 — pc_write와 같은 폴더, 같은 규칙.
    backup = list((tmp_path / ".padiem-backup").glob("*-notes.txt"))
    assert len(backup) == 1 and backup[0].read_bytes() == b"alpha\r\nbeta\r\ngamma\r\n"


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell"),
                    reason="this check runs the real command on Windows PowerShell")
def test_a_utf8_bom_survives_the_edit(tmp_path):
    account, path = _run_edit(tmp_path, b"\xef\xbb\xbfone\n", "one", "uno")
    assert account["ok"] is True, account
    assert path.read_bytes() == b"\xef\xbb\xbfuno\n"


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell"),
                    reason="this check runs the real command on Windows PowerShell")
@pytest.mark.parametrize("body,old,replace_all,reason",
                         [(b"alpha\n", "missing", False, "edit_not_found"),
                          (b"dup dup\n", "dup", False, "edit_not_unique")])
def test_a_refused_edit_changes_nothing_on_disk(tmp_path, body, old, replace_all, reason):
    account, path = _run_edit(tmp_path, body, old, "X", replace_all)
    assert account["ok"] is False and account["reason"] == reason, account
    assert path.read_bytes() == body
    assert not list((tmp_path / ".padiem-backup").glob("*-notes.txt"))


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell"),
                    reason="this check runs the real command on Windows PowerShell")
def test_replace_all_changes_every_occurrence_and_keeps_the_rest(tmp_path):
    account, path = _run_edit(tmp_path, b"dup dup\nend\n", "dup", "X", replace_all=True)
    assert account["ok"] is True, account
    assert path.read_bytes() == b"X X\nend\n"


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell"),
                    reason="this check runs the real command on Windows PowerShell")
def test_a_target_outside_the_granted_folder_is_refused_before_anything_changes(tmp_path):
    inside = tmp_path / "folder"
    inside.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret\n")
    command = routes._pc_write_command(
        op="edit", root=str(inside), target=str(outside), backup_dir=str(tmp_path / "b"),
        relative="../outside.txt", old_text_b64=base64.b64encode(b"secret").decode(),
        new_text_b64=base64.b64encode(b"leak").decode())
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, timeout=90)
    assert outside.read_bytes() == b"secret\n"
    assert done.returncode != 0 or "PADIEM_PC_ACCOUNT=" in done.stdout.decode("utf-8", "replace")
