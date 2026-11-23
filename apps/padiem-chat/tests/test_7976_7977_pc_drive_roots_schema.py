"""#7976/#7977 — drive roots, a separate not-found code, and schema/description agreement.

The operational reproductions on 2026-11-18 named four shapes the old code could
not tell apart: a registered drive root, a path with a dot segment, a folder that
is not there, and a folder outside every grant. The tool catalog also advertised
arguments the transport gate refused because it only accepted string values.
"""
from __future__ import annotations

import base64
import json
import re

import pytest

from app import mcp_gateway_execution as execution
from app import mcp_gateway_transport as transport
from app.oracle_mesh_read_return_routes import _pc_files_command
from test_261105_mcp_registered_folders import ROOTS, _call, harness  # noqa: F401

# #8060: the raw read lives in _support; the stage assertion stays here.
from _support import pc_drive_roots_schema_source as sheets

DRIVE_ROOTS = [{"name": "C:", "path": "C:"}, {"name": "D:", "path": "D:"}]


# -- 1. one spelling per root, dots folded, ``..`` still refused --------------


@pytest.mark.parametrize("value,expected", [
    ("C:", "C:"), ("C:/", "C:"), ("c:\\", "c:"),
    ("D:/.", "D:"), ("D:/./CGI", "D:/CGI"),
    ("docs/./sub", "docs/sub"), ("/tmp/./x", "/tmp/x"),
])
def test_path_normalization_folds_root_and_dot_spellings(value, expected):
    assert execution._pc_normalize_path(value) == expected


@pytest.mark.parametrize("value", ["C:/../secret", "docs/../x", "../outside"])
def test_path_normalization_keeps_dotdot_for_the_scope_check(value):
    assert ".." in execution._pc_normalize_path(value)


@pytest.mark.parametrize("value", ["C:", "C:/", "c:\\", "C:/."])
def test_every_drive_spelling_is_the_registered_root(value):
    assert execution._pc_relative_inside_roots(value, DRIVE_ROOTS)[1] == "root"


def test_an_outside_drive_and_a_dotdot_walk_stay_outside():
    assert execution._pc_relative_inside_roots("E:/", ROOTS)[1] == "outside"
    assert execution._pc_relative_inside_roots("D:/../secret", ROOTS)[1] == "outside"


# -- 2. a registered root names the folder to list, not the folder catalog ---


@pytest.mark.parametrize("value", ["D:", "D:/", "d:\\", "D:/."])
def test_pc_list_of_a_registered_drive_root_lists_that_root(monkeypatch, value):
    result, recorder = _call(monkeypatch, "pc_list", {"path": value})
    assert result["status"] == "completed"
    assert "folders" not in result
    sent = json.loads(recorder.calls[0]["body"])
    assert sent["pc_gateway"]["arguments"]["path"] == "D:"


def test_pc_search_of_a_registered_root_is_not_refused(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_search", {"path": "C:", "query": "readme"},
                             roots=DRIVE_ROOTS)
    assert result["status"] == "completed"
    sent = json.loads(recorder.calls[0]["body"])
    assert sent["pc_gateway"]["arguments"]["path"] == "C:"


def test_an_outside_drive_keeps_the_explicit_outside_code(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_list", {"path": "E:/"})
    assert result["status"] == "failed"
    assert result["code"] == "pc_path_outside_registered_roots"
    assert recorder.calls == []


# -- 3. the PC command names a real drive root and a closed not-found verdict -


def _decoded(command: str) -> list[str]:
    return [base64.b64decode(blob, validate=True).decode("utf-8")
            for blob in re.findall(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", command)]


def test_a_drive_grant_lists_the_volume_not_a_drive_relative_directory():
    command = _pc_files_command(op="list", root="D:", relative="")
    values = _decoded(command)
    assert "D:/" in values
    assert "path_not_found" in command


def test_a_missing_folder_is_a_closed_verdict_not_a_broken_page():
    command = _pc_files_command(op="list", root="D:", relative="gone")
    assert "@{error='path_not_found'}" in command
    assert "ConvertTo-Json -Compress" in command


def test_offset_beyond_the_first_page_is_sent_to_the_pc():
    command = _pc_files_command(op="list", root="D:", relative="CGI", offset=50)
    assert "-Skip 50 -First 50" in command
    assert "@{offset=50;" in command


def test_pc_path_not_found_is_a_distinct_stage():
    source = sheets.query_step_driver()
    assert '"pc_path_not_found"' in source


# -- 4. #7977: description arguments are all in the schema -------------------


def test_the_transport_admits_the_typed_arguments_the_catalog_advertises():
    assert transport.validate_tool_arguments("pc_search", {
        "path": ".", "query": "log", "recursive": True}) is True
    assert transport.validate_tool_arguments("pc_list", {
        "path": ".", "offset": 50}) is True
    assert transport.validate_tool_arguments("pc_list", {
        "path": ".", "depth": 2}) is True


@pytest.mark.parametrize("tool,arguments", [
    ("pc_search", {"path": ".", "query": "x", "recursive": "true"}),
    ("pc_list", {"path": ".", "offset": "50"}),
    ("pc_list", {"path": ".", "offset": -1}),
    ("pc_list", {"path": ".", "offset": 10_001}),
    ("pc_list", {"path": ".", "depth": 2, "offset": 50}),
])
def test_wrong_typed_arguments_are_still_refused(tool, arguments):
    assert transport.validate_tool_arguments(tool, arguments) is False


def test_offset_travels_to_the_engine_as_a_wire_argument(monkeypatch):
    result, recorder = _call(monkeypatch, "pc_list", {"path": "D:/CGI", "offset": 50})
    assert result["status"] == "completed"
    sent = json.loads(recorder.calls[0]["body"])
    assert sent["pc_gateway"]["arguments"]["offset"] == 50


#: Argument names that may appear in a tool description. A mention of any of
#: these in a tool's own description must also be a property of that tool.
_ARGUMENT_VOCABULARY = frozenset({
    "path", "query", "recursive", "depth", "offset", "length", "job_id",
    "device", "url", "action", "text", "role", "name", "value", "content",
    "mode", "old_text", "new_text", "replace_all", "destination",
})
#: Cross-tool references a description may make without owning the argument.
_CROSS_REFERENCES = frozenset({
    ("pc_devices", "device"),
})


def test_every_described_argument_is_in_that_tools_schema():
    tools = transport._static_tool_definitions(shell_user_mode_enabled=True)
    assert len(tools) >= 19
    for tool in tools:
        if not tool["name"].startswith("pc_"):
            continue
        described = tool["description"]
        properties = set(tool["inputSchema"]["properties"])
        for argument in _ARGUMENT_VOCABULARY:
            if (tool["name"], argument) in _CROSS_REFERENCES:
                continue
            if re.search(r"\b" + re.escape(argument) + r"\b", described):
                assert argument in properties, (tool["name"], argument)
