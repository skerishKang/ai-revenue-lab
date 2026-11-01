"""#3782 — the browser lane's own command builder and claim (no PC, no network).

These pin the Owner's decision: the browser lane is separate from the file
lane's seven ops, its command is one line, and its request is a closed shape
that cannot carry a cookie, a password or a script.
"""
from __future__ import annotations

import base64
import json
import re

import pytest

from app.claw_pc_browser_command import (
    PC_BROWSER_OPS,
    PcBrowserCommandError,
    browser_arguments,
    browser_envelope,
    browser_scope_claim,
    pc_browser_command,
)


def _envelope_from(command: str) -> dict:
    """Read back the base64 request the command would feed to the PC child."""
    encoded = re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", command).group(1)
    return json.loads(base64.b64decode(encoded).decode("utf-8"))


def test_the_lane_owns_four_ops_and_no_file_op():
    assert PC_BROWSER_OPS == ("browser_open", "browser_read",
                              "browser_screenshot", "browser_act")
    # The file lane's words are not in this lane, so a claim cannot cross over.
    assert not set(PC_BROWSER_OPS) & {"list", "read", "read_chunk", "search",
                                      "write", "move", "delete"}


def test_open_carries_its_own_address_and_no_remembered_page():
    command = pc_browser_command("browser_open", arguments={"url": "https://example.com"})
    envelope = _envelope_from(command)
    # The canonical public-URL contract owns normalization; the lane repeats it.
    assert envelope == {
        "tool_id": "claw.pc.browser_open",
        "arguments": {"url": "https://example.com/"},
    }
    # An open names its own address; no remembered page rides along.
    assert "url" not in envelope


def test_read_needs_the_server_remembered_page_and_never_invents_one():
    with pytest.raises(PcBrowserCommandError) as missing:
        pc_browser_command("browser_read")
    assert missing.value.code == "browser_not_running"
    envelope = _envelope_from(
        pc_browser_command("browser_read", page_url="https://example.com/notice"))
    assert envelope == {
        "tool_id": "claw.pc.browser_read",
        "arguments": {},
        "url": "https://example.com/notice",
    }


def test_screenshot_and_act_also_target_the_remembered_page():
    shot = _envelope_from(pc_browser_command(
        "browser_screenshot", page_url="https://example.com"))
    assert shot["tool_id"] == "claw.pc.browser_screenshot"
    assert shot["url"] == "https://example.com/"
    act = _envelope_from(pc_browser_command(
        "browser_act", page_url="https://example.com",
        arguments={"action": "click", "text": "공지사항"}))
    assert act["arguments"] == {"action": "click", "text": "공지사항"}


def test_a_cookie_password_or_script_has_no_field_to_travel_in():
    for arguments in (
        {"url": "https://example.com", "cookie": "session=abc"},
        {"cookie": "session=abc"},
        {"script": "alert(1)"},
        {"action": "evaluate"},
    ):
        with pytest.raises(PcBrowserCommandError):
            browser_arguments("browser_act" if "action" in arguments else "browser_read",
                              arguments)
    # A value is only ever the text typed into a field, never a cookie value.
    assert browser_arguments("browser_act", {"action": "type", "name": "검색",
                                             "value": "공지"}) == {
        "action": "type", "name": "검색", "value": "공지"}


def test_only_public_http_addresses_are_accepted():
    for url in ("file:///C:/x.html", "javascript:alert(1)", "http://127.0.0.1/x", ""):
        with pytest.raises(PcBrowserCommandError):
            browser_arguments("browser_open", {"url": url})


def test_click_needs_a_target_and_type_needs_the_text():
    with pytest.raises(PcBrowserCommandError):
        browser_arguments("browser_act", {"action": "click"})
    with pytest.raises(PcBrowserCommandError):
        browser_arguments("browser_act", {"action": "type", "name": "검색"})
    with pytest.raises(PcBrowserCommandError):
        browser_arguments("browser_act", {"action": "evaluate", "name": "x"})


def test_the_command_is_one_line_and_uses_the_reviewed_child_module():
    command = pc_browser_command("browser_open", arguments={"url": "https://example.com"})
    assert "\n" not in command and "\r" not in command
    assert "kagent.pc_browser_child" in command
    assert "-P -m" in command
    # No shell-out to a second program and no script evaluation.
    assert "javascript" not in command.lower()
    assert "Invoke-Expression" not in command


def test_a_claim_from_the_file_lane_never_admits_the_browser():
    files = {"version": 1, "requested": "files", "admitted": "files",
             "source": "declared", "ops": ["list", "read"]}
    assert browser_scope_claim(files) is False
    browser = {"version": 1, "requested": "browser", "admitted": "browser",
               "source": "declared",
               "ops": ["browser_open", "browser_read", "browser_screenshot", "browser_act"]}
    assert browser_scope_claim(browser) is True
    # A browser claim may not smuggle a file op into its vocabulary.
    assert browser_scope_claim({**browser, "ops": ["browser_open", "read"]}) is False
    assert browser_scope_claim({**browser, "admitted": "files"}) is False


def test_envelope_keeps_korean_titles_intact_through_base64():
    envelope = _envelope_from(pc_browser_command(
        "browser_act", page_url="https://example.com",
        arguments={"action": "type", "role": "textbox", "name": "검색", "value": "공지제목"}))
    assert envelope["arguments"]["value"] == "공지제목"
    assert envelope["arguments"]["name"] == "검색"
