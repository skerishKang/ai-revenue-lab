"""#5015: a PC folder listing must hand the next step a path read_file accepts.

The listing command returns Select-Object rows that carry only ``Name``. Passed
through unchanged, the model had no ``relative_path`` to submit even though the
tool contract and the server-verified folder context both name that field, so the
read step re-sent the folder root and the Chat endpoint refused it before creating
any dispatch. These tests drive the handler with the real wire shape.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_LIST_FILES_TOOL_ID,
    PC_READ_FILE_TOOL_ID,
    _make_pc_file_handler,
)

RUN_ID = "run_5015_projection"
SUBJECT = "sub_" + "5" * 32
PRODUCT = "b54-padiem-claw"
DEVICE = "pc-com2"
DISPATCH_ID = "dsp_5015"
WIRE_ROWS = (
    "["
    "{\"Name\":\"meshcentral-padiem-trial.txt\",\"Length\":113,"
    "\"LastWriteTimeUtc\":\"2026-10-19T09:00:00Z\",\"PSIsContainer\":false},"
    "{\"Name\":\"notes\",\"Length\":null,"
    "\"LastWriteTimeUtc\":\"2026-10-19T09:00:00Z\",\"PSIsContainer\":true},"
    "{\"Length\":7,\"PSIsContainer\":false}"
    "]"
)


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, PRODUCT, DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


async def _no_sleep(_seconds: float) -> None:
    return None


def _install_wire(monkeypatch, output: str, *, kind: str = "command") -> None:
    termination = "exited" if kind == "read" else "no_exit_code"
    exit_code = 0 if kind == "read" else None
    encoded = output.encode("utf-8")

    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        if mode == "dispatch":
            assert kwargs["payload"]["op"] == (
                "read" if kind == "read" else "list"
            )
            return {
                "dispatch": {
                    "run_id": RUN_ID, "kind": kind, "dispatch_id": DISPATCH_ID,
                }
            }
        if mode == "command_status":
            return {
                "dispatch": {
                    "dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                    "kind": kind, "state": "done",
                }
            }
        if mode == "result":
            return {
                "dispatch": {
                    "dispatch_id": DISPATCH_ID, "run_id": RUN_ID, "kind": kind,
                    "output": output,
                    "result_sha256": "a" * 64,
                    "content_sha256": "a" * 64,
                    "content_bytes": len(encoded),
                    "termination": termination,
                    "exit_code": exit_code,
                }
            }
        raise AssertionError("unexpected mode " + str(mode))

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


def _handler(op: str, tool_id: str):
    return _make_pc_file_handler(
        tool_id=tool_id, op=op, service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
    )


def test_root_listing_projects_one_readable_relative_path_per_row(monkeypatch) -> None:
    _install_wire(monkeypatch, WIRE_ROWS)
    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    listed = json.loads(result["output"])
    assert listed["ok"] is True
    assert listed["path"] == "."
    assert result["entry_count"] == 3
    rows = listed["entries"]
    assert rows[0]["relative_path"] == "meshcentral-padiem-trial.txt"
    # The original Select-Object columns stay verbatim; only a path is added.
    assert rows[0]["Name"] == "meshcentral-padiem-trial.txt"
    assert rows[0]["Length"] == 113
    assert rows[1]["relative_path"] == "notes"
    # A row with no Name never receives an invented path.
    assert "relative_path" not in rows[2]
    assert result["execution_confirmed"] is True
    assert result["termination"] == "no_exit_code"


def test_single_entry_folder_is_projected(monkeypatch) -> None:
    # ConvertTo-Json collapses one row to a bare object, not an array.
    _install_wire(monkeypatch,
                  "{\"Name\":\"one.txt\",\"Length\":4,\"PSIsContainer\":false}")
    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    listed = json.loads(result["output"])
    assert listed["entries"] == [
        {"Name": "one.txt", "Length": 4, "PSIsContainer": False,
         "relative_path": "one.txt"}
    ]
    assert result["entry_count"] == 1


def test_subfolder_listing_prefixes_each_row_with_the_listed_folder(monkeypatch) -> None:
    _install_wire(monkeypatch, "[{\"Name\":\"report.txt\",\"Length\":20,"
                              "\"PSIsContainer\":false}]")
    result = asyncio.run(
        _handler("list", PC_LIST_FILES_TOOL_ID)({"path": "notes/sub"})
    )

    listed = json.loads(result["output"])
    assert listed["path"] == "notes/sub"
    assert listed["entries"][0]["relative_path"] == "notes/sub/report.txt"


def test_legacy_wrapped_listing_keeps_its_own_relative_path(monkeypatch) -> None:
    _install_wire(monkeypatch, json.dumps({
        "ok": True,
        "entries": [{"Name": "already.txt", "relative_path": "already.txt"}],
        "truncated": True,
    }))
    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    listed = json.loads(result["output"])
    assert listed["entries"][0]["relative_path"] == "already.txt"
    assert listed["truncated"] is True
    assert result["truncated"] is True


def test_projected_path_is_the_value_the_read_step_submits(monkeypatch) -> None:
    _install_wire(monkeypatch, WIRE_ROWS)
    listed = json.loads(
        asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))["output"]
    )
    target = listed["entries"][0]["relative_path"]

    assert target != "."
    _install_wire(monkeypatch, "meshcentral trial content", kind="read")
    read = asyncio.run(
        _handler("read", PC_READ_FILE_TOOL_ID)({"path": target})
    )

    assert read["content"] == "meshcentral trial content"
    assert read["content_bytes"] == len("meshcentral trial content")


def test_empty_folder_listing_still_projects_an_entry_list(monkeypatch) -> None:
    _install_wire(monkeypatch, "null")
    result = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    listed = json.loads(result["output"])
    assert listed["entries"] == []
    assert result["entry_count"] == 0


@pytest.mark.parametrize(
    "list_path,expected",
    [
        (".", "x.txt"),
        ("notes", "notes/x.txt"),
        ("notes\\sub", "notes/sub/x.txt"),
    ],
)
def test_prefix_rule_matches_the_accepted_folder_shapes(
    list_path: str, expected: str
) -> None:
    rows = driver._pc_list_entries_with_paths(list_path, [{"Name": "x.txt"}])

    assert rows[0]["relative_path"] == expected


def test_helper_never_stitches_a_separator_into_a_nested_name() -> None:
    rows = driver._pc_list_entries_with_paths("notes", [{"Name": "sub/b.txt"}])

    # A Name that is not a single folder entry is left unprojected rather than
    # doubled into a path the endpoint would not resolve the same way.
    assert "relative_path" not in rows[0]


@pytest.mark.parametrize("list_path", ["./notes", "notes/../other", "notes//sub",
                                       "notes/", "/etc", "C:/x"])
def test_normalizer_refuses_the_shapes_the_chat_endpoint_refuses(list_path: str) -> None:
    # A trailing or doubled separator is an empty segment, which the Chat
    # endpoint refuses as well: the projection stays exactly as strict as its
    # consumer instead of inventing a path that would be rejected later.
    assert driver._pc_list_folder_prefix(list_path) is None


def test_a_refused_folder_shape_gets_no_invented_path() -> None:
    rows = driver._pc_list_entries_with_paths("./notes", [{"Name": "x.txt"}])

    assert "relative_path" not in rows[0]


def test_real_wire_listing_feeds_the_step_driver_read_selection(monkeypatch) -> None:
    """The handler's real output, not a hand-written one, must name the file.

    This is the exact chain that stopped before #5015: the step driver reads
    ``entries[0].relative_path`` from the listing observation, and the PC command
    only returned ``Name``.
    """
    from padiem_ai_core.agent_runtime import AgentStepContext
    from padiem_ai_core.contracts import RunStatus, ToolEvent
    from padiem_ai_core.tool_runtime import ToolExecutionResult

    from app.claw_pc_query_step_driver import StructuredPCQueryStepDriver

    _install_wire(monkeypatch, WIRE_ROWS)
    listed = asyncio.run(_handler("list", PC_LIST_FILES_TOOL_ID)({"path": "."}))

    observed = ToolExecutionResult(
        tool_id=PC_LIST_FILES_TOOL_ID,
        output={"output": listed["output"], "entry_count": listed["entry_count"]},
        event=ToolEvent(tool_id=PC_LIST_FILES_TOOL_ID, status=RunStatus.COMPLETED),
    )

    async def select_step(*, context, compiled_profile, observations):
        if not observations:
            return {
                "action": "tool", "tool_id": PC_LIST_FILES_TOOL_ID,
                "arguments": {"path": ".", "intent": "read"},
            }
        assert len(observations) == 1
        rows = json.loads(observations[0]["output"]["output"])["entries"]
        row = next(r for r in rows if r.get("PSIsContainer") is False)
        return {
            "action": "tool", "tool_id": PC_READ_FILE_TOOL_ID,
            "arguments": {"path": row["relative_path"]},
        }

    # #5573/#5574: the Chat lane's list+read ceiling is not a grant; the same
    # driver instance first takes the model's read-intent listing step, then
    # the read step over its observation.
    driver = StructuredPCQueryStepDriver(
        select_step=select_step,
        allowed_tool_ids=frozenset({PC_LIST_FILES_TOOL_ID, PC_READ_FILE_TOOL_ID}),
    )
    first = asyncio.run(driver.next_step(
        AgentStepContext.with_results(
            run_id=RUN_ID,
            step_index=1,
            input_text="폴더 목록을 보고 TXT를 읽어줘",
            results=(),
        ),
        object(),
    ))
    assert first.invocation.tool_id == PC_LIST_FILES_TOOL_ID

    context = AgentStepContext.with_results(
        run_id=RUN_ID,
        step_index=2,
        input_text="폴더 목록을 보고 TXT를 읽어줘",
        results=(observed,),
    )
    step = asyncio.run(driver.next_step(context, object()))

    assert step.invocation.arguments == {
        "path": "meshcentral-padiem-trial.txt"
    }


@pytest.mark.parametrize("path,roots,expected", [
    ("C:/APP/data/sub", ["c:\\app\\data\\"], "sub"),
    ("C:/app/data/", ["C:/app/data"], "."),
    ("C:/app/data/sub/file.txt", ["C:/app", "C:/app/data/"], "sub/file.txt"),
    ("C:/app/database/x", ["C:/app/data"], "C:/app/database/x"),
    ("C:/other/x", ["C:/app/data"], "C:/other/x"),
    ("C:/app/data/../outside", ["C:/app/data"], "../outside"),
    ("relative/sub", ["C:/app/data"], "relative/sub"),
    ("C:/app/data/sub", None, "C:/app/data/sub"),
    ("C:/app/data/sub", [None, 4, ""], "C:/app/data/sub"),
    ("//server/share/root/sub", ["\\\\server\\share\\root"], "sub"),
])
def test_verified_root_normalization_preserves_relative_path_guard(path, roots, expected):
    normalized = driver._pc_path_against_verified_roots(path, {"roots": roots})
    assert normalized == expected
    if expected.startswith(("C:", "../")):
        assert driver._pc_list_folder_prefix(normalized) is None
