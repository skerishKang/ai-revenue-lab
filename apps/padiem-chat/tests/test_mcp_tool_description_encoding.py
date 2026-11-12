"""Every MCP tool definition must ship readable Korean, never mojibake.

#7097 rebuilt the pc_shell property blocks through a CP949 round trip and
replaced the Korean descriptions with U+FFFD. External MCP clients then saw
" PC\u0394\u0398. pc_devices\u02dc..." in tools/list because the bytes no
longer decoded as UTF-8 Korean. This module fails whenever a surfaced tool
name, title, description, or inputSchema description carries a replacement
character, a Latin-Extended character that only appears when UTF-8 Korean is
read as CP949, or a reversible CP949->UTF-8 double encoding.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.mcp_gateway_transport import _static_tool_definitions


APP_DIR = Path(__file__).resolve().parents[1] / "app"
MCP_SOURCES = ("mcp_gateway_shell.py", "mcp_gateway_transport.py")
# U+00B7 is the only intentional non-ASCII, non-Hangul character the Korean
# copy uses ("표시 이름·기기 ID"). Every other Latin-1/Extended character is
# the fingerprint of UTF-8 Korean decoded as CP949.
ALLOWED_LATIN = frozenset({"\u00b7"})
HANGUL_FIRST, HANGUL_LAST = "\uac00", "\ud7a3"

CANONICAL_DEVICE = (
    "대상 PC입니다. pc_devices가 알려 준 표시 이름이나 id6를 씁니다. "
    "비우면 연결의 기본 PC를 씁니다."
)
CANONICAL_SHELL_JOB_ID = "pc_shell 또는 pc_shell_start가 돌려준 Claw 작업 ID입니다."


def _mojibake_reasons(value: str) -> list[str]:
    reasons = []
    if "\ufffd" in value:
        reasons.append("U+FFFD replacement character")
    bad_latin = sorted(
        {char for char in value
         if 0x0080 <= ord(char) <= 0x024F and char not in ALLOWED_LATIN}
    )
    if bad_latin:
        reasons.append(
            "Latin-Extended characters " + ", ".join("U+%04X" % ord(char) for char in bad_latin)
        )
    try:
        repaired = value.encode("cp949").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return reasons
    if repaired != value and any(HANGUL_FIRST <= char <= HANGUL_LAST for char in repaired):
        reasons.append("reversible CP949->UTF-8 double encoding")
    return reasons


def _schema_strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _schema_strings(value, path + "." + str(key) if path else str(key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _schema_strings(value, "%s[%d]" % (path, index))


def _tool_fields(tool: dict):
    yield "name", tool["name"]
    for field in ("title", "description"):
        value = tool.get(field)
        assert isinstance(value, str), "tool %s has a non-string %s" % (tool["name"], field)
        yield field, value
    for path, value in _schema_strings(tool.get("inputSchema") or {}):
        yield "inputSchema." + path, value


@pytest.mark.parametrize("shell_user_mode_enabled", [False, True])
def test_every_surfaced_mcp_tool_text_is_clean(shell_user_mode_enabled):
    tools = _static_tool_definitions(shell_user_mode_enabled=shell_user_mode_enabled)
    # Exact on purpose: #7065 added pc_edit and #7603 adds pc_mkdir, so
    # seventeen tools ship copy now.
    assert len(tools) == 17, [tool["name"] for tool in tools]

    failures = []
    for tool in tools:
        for field, value in _tool_fields(tool):
            reasons = _mojibake_reasons(value)
            if reasons:
                failures.append("%s.%s: %s -> %r" % (tool["name"], field, ", ".join(reasons), value))

    assert failures == [], "MCP tool text is not readable Korean:\n" + "\n".join(failures)


def test_pc_shell_stop_descriptions_match_the_canonical_korean():
    tools = {tool["name"]: tool for tool in _static_tool_definitions(shell_user_mode_enabled=True)}
    stop_properties = tools["pc_shell_stop"]["inputSchema"]["properties"]

    assert stop_properties["device"]["description"] == CANONICAL_DEVICE
    assert stop_properties["job_id"]["description"] == CANONICAL_SHELL_JOB_ID

    # The same meaning must read the same on every tool that carries it.
    device_texts = {
        tool["inputSchema"]["properties"]["device"]["description"]
        for tool in tools.values()
        if "device" in tool["inputSchema"]["properties"]
    }
    assert device_texts == {CANONICAL_DEVICE}
    assert (tools["pc_shell_read"]["inputSchema"]["properties"]["job_id"]["description"]
            == stop_properties["job_id"]["description"])


def test_tools_list_survives_a_json_round_trip():
    tools = _static_tool_definitions(shell_user_mode_enabled=True)
    wire = json.dumps({"tools": tools}, ensure_ascii=False, allow_nan=False)
    assert "\ufffd" not in wire
    assert json.loads(wire) == {"tools": tools}


def test_mcp_gateway_sources_carry_no_replacement_characters():
    failures = []
    for name in MCP_SOURCES:
        data = (APP_DIR / name).read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as error:
            failures.append("%s is not valid UTF-8: %s" % (name, error))
            continue
        count = data.count(b"\xef\xbf\xbd")
        if count:
            failures.append("%s carries %d U+FFFD bytes" % (name, count))
    assert failures == [], "\n".join(failures)