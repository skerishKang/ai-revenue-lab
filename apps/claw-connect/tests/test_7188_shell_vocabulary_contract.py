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
import sys

import pytest

from claw_connect import user_session_helper as helper

if sys.platform != "win32":
    @pytest.fixture(autouse=True)
    def _fake_system_executables(monkeypatch):
        """One deterministic fake system directory for non-Windows runs.

        The argv *shape* per resolved name is what this contract pins; where
        the executable actually lives is the OS's answer, exercised for real
        on the Windows jobs.
        """
        fake = "/fake-padiem-system32"
        monkeypatch.setattr(helper, "system_executable",
                            lambda name: os.path.join(fake, name))
        monkeypatch.setattr(helper, "windows_powershell_executable",
                            lambda: os.path.join(fake, "WindowsPowerShell", "v1.0", "powershell.exe"))
        yield

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
    # bash resolves to itself: the helper's Git Bash stage-2 shell since
    # #7188 R4 ④ (the owner banned WSL on the PC; the wsl shell is gone).
    assert selection.resolve_shell("bash", lane="user") == helper.SHELL_BASH
    assert not hasattr(helper, "SHELL_WSL")


def test_helper_build_argv_shape_is_unchanged_per_resolved_name():
    """The helper's argv per resolved name stays what it served before.

    #7564: the system executables moved from bare names to the full path the
    OS reports, so the shape assertions name the executable by that path.
    """
    ps = helper.build_argv(_request(
        selection.resolve_shell("powershell", lane="user"), "hostname"))
    assert ps[0] == helper.windows_powershell_executable() and "-EncodedCommand" in ps
    cmd = helper.build_argv(_request(
        selection.resolve_shell("cmd", lane="user"), "hostname"))
    assert cmd[:4] == [helper.system_executable("cmd.exe"), "/d", "/s", "/c"] and cmd[4] == "hostname"
    bash = helper.build_argv(_request(
        selection.resolve_shell("bash", lane="user"), "uname -a"))
    # bash runs the located Git Bash with the same -lc shape the SYSTEM lane
    # uses; never wsl.exe, never System32's WSL bash.
    assert bash[0].endswith("bash.exe") and bash[1] == "-lc" and bash[2] == "uname -a"
    assert "system32" not in bash[0].lower() and "wsl" not in bash[0].lower()
    whoami = helper.build_argv(_request(
        selection.resolve_user_helper_shell("bash", command="whoami"), "whoami"))
    assert whoami == [helper.system_executable("whoami.exe")]


def test_helper_refuses_what_the_table_refuses():
    """An unsupported name is refused by the helper's own final authority."""
    with pytest.raises(selection.UnknownShellName):
        selection.resolve_shell("fish", lane="user")
    with pytest.raises(helper.UserHelperError) as refused:
        helper.build_argv(_request("fish", "hostname"))
    assert refused.value.code == helper.USER_HELPER_REFUSED


def test_the_git_bash_candidate_sources_are_one_shared_order():
    """#7188 R4 ④ — both lanes probe the same sources in the same order.

    The helper's single-file build must not import the Core table, so the
    copies are pinned equal here: registry keys, PATH relatives and the fixed
    standard roots.
    """
    assert helper.GIT_BASH_REGISTRY_KEYS == selection.GIT_BASH_REGISTRY_KEYS
    assert helper.GIT_BASH_PATH_RELATIVES == selection.GIT_BASH_PATH_RELATIVES
    assert helper.GIT_BASH_FIXED_CANDIDATES == selection.GIT_BASH_CANDIDATES


def test_locate_git_bash_order_registry_then_path_then_fixed():
    """The locate order is registry, PATH git.exe relatives, fixed roots."""
    seen = []

    def open_key(hive, subkey):
        seen.append(("reg", hive, subkey))
        return None

    def which(name):
        seen.append(("which", name))
        return None

    def expandvars(value):
        seen.append(("expand", value))
        return "% definitely not here%\bin\bash.exe"

    found = helper.locate_git_bash(open_key=open_key, which=which,
                                   expandvars=expandvars, isfile=lambda p: False)
    assert found is None
    kinds = [item[0] for item in seen]
    assert kinds.count("reg") == 3
    assert kinds.index("which") > max(i for i, k in enumerate(kinds) if k == "reg")
    assert kinds.index("expand") > kinds.index("which")
    assert seen[0][0] == "reg"


def test_locate_git_bash_never_returns_the_wsl_bash():
    """A planted System32 path is refused at every probe stage."""
    planted = "C:\\Windows\\System32\\bash.exe"

    def open_key(hive, subkey):
        return planted

    assert helper.locate_git_bash(open_key=open_key, which=lambda name: None,
                                  expandvars=lambda value: planted,
                                  isfile=lambda p: True) is None
    # a PATH git.exe whose siblings are planted System32 paths is refused too

    def which(name):
        return planted

    assert helper.locate_git_bash(open_key=lambda h, k: None, which=which,
                                  expandvars=lambda value: planted,
                                  isfile=lambda p: True) is None


def test_the_real_git_bash_guard_refuses_a_wsl_exe_leaf():
    """가드 3번째 조건(`wsl.exe` leaf 배제)을 직접 고정한다.

    후보 생성식이 모두 ``\\bin\\bash.exe`` 접미사를 강제하므로 상위 탐색
    흐름에서는 도달 불가한 이중 안전장치다(아르곤 #7302 (c)-5). 향후 리팩터링이
    이 조건을 지우지 않도록 가드 함수 자체의 계약을 한 줄로 못박는다.
    """
    assert helper._is_real_git_bash(r"C:\Temp\wsl.exe", lambda p: True) is False
