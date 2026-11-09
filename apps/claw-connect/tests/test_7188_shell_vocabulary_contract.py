"""#7188 R4 ② — the shared shell table and the helper's vocabulary agree.

``padiem_ai_core.pc_shell_selection`` is the one table the chat tool resolves
shell names through. The helper (``claw_connect.user_session_helper``) stays
the final allowlist authority on the PC and does not import the table — its
single-file build must not grow the Core package. What this contract pins
instead: every name the tool accepts resolves, on the user lane, to a helper
shell that really runs, with the same argv shape the helper built before the
table existed.

The table module is loaded straight from the repository tree because this
environment's installed ``padiem_ai_core`` copy predates the new module.
"""
from __future__ import annotations

import importlib.util
import os

import pytest

from claw_connect import user_session_helper as helper

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_TABLE_PATH = os.path.join(
    _ROOT, "packages", "padiem-ai-core", "padiem_ai_core", "pc_shell_selection.py"
)
_spec = importlib.util.spec_from_file_location("_pc_shell_selection_7188", _TABLE_PATH)
selection = importlib.util.module_from_spec(_spec)
import sys  # noqa: E402

sys.modules[_spec.name] = selection  # 3.14 dataclasses resolve the module here
_spec.loader.exec_module(selection)


def _request(shell: str, command: str) -> helper.HelperRequest:
    return helper.HelperRequest(
        request_id="req_" + "0" * 32, nonce="x", shell=shell, command=command,
        timeout_seconds=0,
    )


def test_every_tool_shell_name_resolves_into_the_helpers_vocabulary():
    for name in selection.PC_SHELL_NAMES:
        resolved = selection.resolve_shell(name, lane="user")
        assert resolved in helper.SUPPORTED_SHELLS, (name, resolved)
    # bash resolves to the helper's wsl shell (#7105 vocabulary meeting).
    assert selection.resolve_shell("bash", lane="user") == helper.SHELL_WSL


def test_helper_build_argv_shape_is_unchanged_per_resolved_name():
    """The helper's argv per resolved name stays what it served before."""
    ps = helper.build_argv(_request(
        selection.resolve_shell("powershell", lane="user"), "hostname"))
    assert ps[0] == "powershell.exe" and "-EncodedCommand" in ps
    cmd = helper.build_argv(_request(
        selection.resolve_shell("cmd", lane="user"), "hostname"))
    assert cmd[:4] == ["cmd.exe", "/d", "/s", "/c"] and cmd[4] == "hostname"
    wsl = helper.build_argv(_request(
        selection.resolve_shell("bash", lane="user"), "uname -a"))
    assert wsl[0] == "wsl.exe" and "bash" in wsl and "-lc" in wsl
    whoami = helper.build_argv(_request(
        selection.resolve_user_helper_shell("bash", command="whoami"), "whoami"))
    assert whoami == ["whoami.exe"]


def test_helper_refuses_what_the_table_refuses():
    """An unsupported name is refused by the helper's own final authority."""
    with pytest.raises(selection.UnknownShellName):
        selection.resolve_shell("fish", lane="user")
    with pytest.raises(helper.UserHelperError) as refused:
        helper.build_argv(_request("fish", "hostname"))
    assert refused.value.code == helper.USER_HELPER_REFUSED
