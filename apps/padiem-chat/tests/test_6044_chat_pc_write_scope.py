"""#6044: the Chat PC lane opens writes on request, and the part can move and delete.

Three things are pinned here. A request the owner phrased as a change selects the
canonical ``files_write`` plan (write_file, move_file, delete_file) and nothing
else; a request phrased as a read keeps selecting the read plans, so opening the
write lane never widens what a read turn may do. And the two new part routes act
for the owner whose own link grants the folder, while another account's request
is refused before any command is built.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_5895_pc_file_exchange as exchange      # noqa: E402

from app import chat_pc_drive                     # noqa: E402
from app import pc_file_exchange_routes as routes  # noqa: E402

pairing = exchange.pairing
OWNER = exchange.OWNER
OTHER_ACCOUNT = "usr_" + "d" * 32
DEVICE_ID = "dev_" + "a" * 32
WRITE_TOOL_IDS = {"claw.pc.write_file", "claw.pc.move_file", "claw.pc.delete_file"}


def test_a_write_request_opens_the_files_write_scope():
    plan = chat_pc_drive.chat_pc_plan_for_tool("files_write")

    assert plan is not None, "a write request must select a plan"
    assert tuple((step["step_id"], step["tool_id"]) for step in plan["steps"]) == (
        ("write_file", "claw.pc.write_file"),
        ("move_file", "claw.pc.move_file"),
        ("delete_file", "claw.pc.delete_file"),
    ), "the write plan is the canonical three-step shape the Engine admits"
    # The model is offered the tool under the same name the Engine's closed
    # scope map already knows.
    write_names = {tool.name for tool in chat_pc_drive.pc_tools_for_turn("이 파일 저장해 줘")}
    assert "files_write" in write_names
    # The target hint keeps the Engine's key, so the write plan carries its target
    # exactly as the read plans do.
    assert chat_pc_drive._tool_arguments_for_plan(plan, DEVICE_ID) == {
        "files_write": {"device_id": DEVICE_ID},
    }
    # Browser is independent; the existing file scopes stay unchanged.
    bridge = (Path(__file__).resolve().parents[1] / "app/orchestration_bridge.py").read_text(
        encoding="utf-8",
    )
    assert '("query_drives", "files_list", "files", "files_write", "browser")' in bridge


def test_a_read_request_does_not_open_the_write_scope():
    for tool_name in ("query_drives", "files_list", "files"):
        plan = chat_pc_drive.chat_pc_plan_for_tool(tool_name)
        assert plan is not None, tool_name
        tool_ids = {step["tool_id"] for step in plan["steps"]}
        assert not (tool_ids & WRITE_TOOL_IDS), tool_name

    read_names = {tool.name for tool in chat_pc_drive.pc_tools_for_turn("폴더에 뭐가 있는지 알려 줘")}
    assert read_names == {"query_drives", "files_list", "files", "browser"}
    assert "files_write" not in read_names
    assert chat_pc_drive.pc_write_intent("이름을 최종으로 바꿔 줘")
    assert not chat_pc_drive.pc_write_intent("지난주 회의록 읽어 줘")

    read = chat_pc_drive.chat_pc_plan_for_tool("files")
    write = chat_pc_drive.chat_pc_plan_for_tool("files_write")
    assert read != write
    assert read["steps"] != write["steps"]
    # A read plan's target hint is the read key, never the write one.
    assert chat_pc_drive._tool_arguments_for_plan(read, DEVICE_ID) == {
        "files": {"device_id": DEVICE_ID},
    }


def test_move_moves_one_file_with_the_backup_that_comes_first(monkeypatch):
    state, captured, link_id, _ = exchange._state(monkeypatch)

    status, body = exchange._answer(pairing.run(routes.pc_file_exchange_move(
        exchange._Request(state, body={
            "path": "축사/초안.txt", "destination": "축사/최종.txt", "link_id": link_id,
        })
    )))

    assert status == 200 and body["ok"] is True, body
    assert body["name"] == "최종.txt"
    command = captured[0]["command"]
    assert ".padiem-backup" in command
    assert 0 < command.index("Copy-Item") < command.index("Move-Item")
    # The account line survives the command builder's own wording: what the
    # owner is told is still that one marked line, however it is concatenated.
    assert "PADIEM_PC_ACCOUNT=" in command
    assert "Write-Output" in command
    # And the whole command is one line, which is not a style rule: the agent on
    # the customer's PC never finishes a multi-line script through
    # `powershell -command -`, so a builder that spreads statements cannot run
    # there at all (#5573, measured 2026-10-28).
    assert "\n" not in command
    assert "\r" not in command


def test_delete_deletes_one_file_already_copied_to_the_backup(monkeypatch):
    state, captured, link_id, _ = exchange._state(monkeypatch)

    status, body = exchange._answer(pairing.run(routes.pc_file_exchange_delete(
        exchange._Request(state, body={"path": "축사/초안.txt", "link_id": link_id})
    )))

    assert status == 200 and body["ok"] is True, body
    command = captured[0]["command"]
    assert ".padiem-backup" in command
    assert 0 < command.index("Copy-Item") < command.index("Remove-Item")


def test_another_account_cannot_move_or_delete(monkeypatch):
    """The link belongs to the owner; this request comes from another account.

    Both routes must answer before a command exists: a refused request cannot
    have queued a change for someone else's PC.
    """
    state, captured, _link_id, _ = exchange._state(monkeypatch, uid=OTHER_ACCOUNT)

    for call, body in (
        (routes.pc_file_exchange_move,
         {"path": "축사/초안.txt", "destination": "축사/최종.txt"}),
        (routes.pc_file_exchange_delete, {"path": "축사/초안.txt"}),
    ):
        status, _answer_body = exchange._answer(pairing.run(
            call(exchange._Request(state, body=body)),
        ))
        assert 400 <= status < 500, (call.__name__, status)
    assert captured == []
