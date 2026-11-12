"""#7188 R4 ③ — bash 후보는 Git Bash 표준 설치 경로뿐이다.

#7266 수동 확인에서 측정된 결함: SYSTEM × bash가 ``bash.exe`` PATH 탐색으로
``C:\\Windows\\System32\\bash.exe``(WSL)를 집어 기동에 실패했다(exit 1, 출력
없음). 고객 PC에서 같은 이름은 WSL bash이므로 PATH에 두면 어느 쪽이든 틀린
프로그램을 고른다. 이 PR부터 bash는 Git for Windows의 표준 설치 경로 후보를
순서대로 탐색하고, 없으면 변경 전과 같은 ``shell_unavailable`` exit 127로
명확히 실패한다. System32\\bash.exe는 후보가 아니며, 후보 탐색에는 PATH
fallback이 없다.

아르곤 검토(#7287 답변) 반영:

- (b) B-1 — 32비트(WOW64) PowerShell은 ``%ProgramFiles%``를 x86 트리로
  리다이렉트하므로 64비트 표준 설치는 ``%ProgramW6432%``로만 닿는다. 첫
  후보로 둔다(64비트에서는 앞 두 후보가 같은 경로로 확장되어 무해한 재탐색).
- (d) — 후보 부재 시험 2건은 호스트의 실제 ``%ProgramFiles%`` 계열을 그대로
  확장해 Git이 설치된 PC·Windows CI에서 즉시 실패했다. 네 변수를 tmp_path
  아래 빈 폴더로 격리해 어느 기계에서도 결정론적으로 127이 나게 고쳤다.
- (d) — 첫 후보 실행 시험은 확장·break 순서·@args 전달을 전혀 검증하지 못하는
  위양성이었다. 후보를 (1) 없는 경로 (2) ``%변수%`` 형태의 가짜 bash
  (받은 인자를 그대로 출력) (3) 또 다른 존재하는 가짜 bash로 구성해 세 가지를
  실제로 검증한다.

경로별 선택 표(#7188 R4 ③ 기준, 변경 0인 행 포함):

| 경로                    | R4 ②까지                                               | R4 ③부터                                               |
|-------------------------|--------------------------------------------------------|--------------------------------------------------------|
| SYSTEM × powershell     | powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand | 변경 0(후보 없음, Get-Command 그대로) |
| SYSTEM × cmd            | cmd.exe /d /s /c <c>                                   | 변경 0(후보 없음, Get-Command 그대로) |
| SYSTEM × bash           | bash.exe -lc <c>(PATH 탐색 → System32 WSL bash)        | %ProgramW6432%\\Git\\bin\\bash.exe → %ProgramFiles%\\Git\\bin\\bash.exe → %ProgramFiles%\\Git\\usr\\bin\\bash.exe → %ProgramFiles(x86)%\\Git\\bin\\bash.exe → %LocalAppData%\\Programs\\Git\\bin\\bash.exe 순서 탐색, 첫 존재 파일 실행; 전부 부재면 shell_unavailable(127) |
| SYSTEM × 셸 생략        | powershell 기본                                        | 변경 0                                                  |
| SYSTEM × 미지원 이름    | UnknownShellName                                       | 변경 0                                                  |
| USER × bash             | material shell 'wsl'(헬퍼 관찰 레인, 읽기 전용 게이트) | R4 ④에서 제거: material shell 'bash' 그대로 전달, 헬퍼가 같은 후보 순서(레지스트리 → PATH git.exe → 고정)로 Git Bash를 직접 실행. wsl 셸은 삭제(대표 결정: 컴1에서 WSL 금지). bash.exe PATH 탐색도 없음 — System32 후보 문제는 두 레인 모두 해당 없음 |

저널 문자열(R4 ① 위상 상수)과 stderr의 ``shell_unavailable`` 바이트는 불변.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from padiem_ai_core.pc_shell_selection import (
    GIT_BASH_CANDIDATES,
    SystemShellLaunch,
    resolve_shell,
    system_launch_env_lines,
)

from app import mcp_gateway_shell as shell

SYSTEM32_BASH = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "bash.exe"

#: 아르곤 (d): 이 네 변수를 격리하지 않으면 Git이 설치된 PC·windows-latest
#: 러너에서 첫 후보가 실제로 존재해 127 시험이 즉시 실패한다.
ISOLATED_ROOT_NAMES = ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LocalAppData")


def _script_of(command_text: str) -> str:
    return base64.b64decode(
        command_text.rsplit("-EncodedCommand ", 1)[1]
    ).decode("utf-16-le")


def _isolated_root_lines(tmp_path: Path) -> str:
    """네 루트 변수를 tmp_path 아래 빈 폴더로 고정하는 PowerShell 대입문."""
    lines = []
    for name in ISOLATED_ROOT_NAMES:
        empty = tmp_path / "empty-roots" / name.replace("(", "_").replace(")", "_")
        empty.mkdir(parents=True, exist_ok=True)
        # 괄호 이름은 ${env:...} 형태만 유효하다.
        lines.append("${env:" + name + "}='" + str(empty) + "';")
    return "".join(lines)


def _run_tail(script: str, env_lines: str, command: bytes, extra_env: str = "",
              stubs: "str | None" = None):
    probe = (
        extra_env
        + env_lines
        + "$env:PADIEM_MCP_COMMAND_B64='" + base64.b64encode(command).decode() + "';"
        "$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("
        "$env:PADIEM_MCP_COMMAND_B64));"
        # R4 ④: bash 가지가 쓰는 _padiem_bash_ok 가드 함수 정의도 함께 넣는다.
        # R4 ④: bash 가지가 쓰는 _padiem_bash_ok 가드 함수 정의도 함께 넣고,
        # 이 기계의 실제 레지스트리·PATH git.exe 단계는 함수 재정의로 격리한다
        # (후보 목록 자체만 검증 대상 — Git 설치 여부와 무관하게 결정론적).
        # 특정 단계를 검증하는 시험은 stubs 인자로 자기 격리를 대체한다.
        + (stubs if stubs is not None
           else "function Get-ItemProperty { $null };"
                "function Get-Command { $null };")
        + script[script.index("function _padiem_bash_ok"):]
    )
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", probe],
        capture_output=True, text=True, timeout=60,
    )


def test_bash_candidates_are_the_git_bash_roots_only():
    """후보 목록: Git Bash 표준 경로만, System32 배제, 순서 고정."""
    assert GIT_BASH_CANDIDATES == (
        r"%ProgramW6432%\Git\bin\bash.exe",
        r"%ProgramFiles%\Git\bin\bash.exe",
        r"%ProgramFiles%\Git\usr\bin\bash.exe",
        r"%ProgramFiles(x86)%\Git\bin\bash.exe",
        r"%LocalAppData%\Programs\Git\bin\bash.exe",
    )
    for cand in GIT_BASH_CANDIDATES:
        assert "system32" not in cand.lower()
        assert cand.lower().endswith("bash.exe")
        assert "git" in cand.lower()


def test_programw6432_candidate_comes_first_for_32bit_powershell():
    """32비트(WOW64) PowerShell 대비: %ProgramW6432%가 %ProgramFiles% 앞.

    32비트 프로세스에서 %ProgramFiles%는 x86 트리로 리다이렉트되므로 64비트
    표준 설치 경로는 %ProgramW6432%로만 닿는다(아르곤 #7287 (b) B-1). 첫
    후보가 아니면 WOW64 환경에서 64비트 Git을 놓치고 x86 설치(또는 127)로
    끝난다.
    """
    assert GIT_BASH_CANDIDATES[0] == r"%ProgramW6432%\Git\bin\bash.exe"
    assert GIT_BASH_CANDIDATES.index(r"%ProgramW6432%\Git\bin\bash.exe") \
        < GIT_BASH_CANDIDATES.index(r"%ProgramFiles%\Git\bin\bash.exe")
    # env 줄에서도 같은 순서가 유지된다.
    bash_lines = system_launch_env_lines(resolve_shell("bash", lane="system"))
    w6432 = bash_lines.index("%ProgramW6432%")
    pf = bash_lines.index("%ProgramFiles%\\")
    assert w6432 < pf


def test_powershell_and_cmd_keep_no_candidates():
    """변경 0 행: powershell·cmd는 후보 없음 — Get-Command 행위 그대로."""
    for name in ("powershell", "cmd"):
        launch = resolve_shell(name, lane="system")
        assert launch.candidates == ()
        lines = system_launch_env_lines(launch)
        assert "PADIEM_MCP_SHELL_CANDIDATES" not in lines
    # bash만 후보 줄을 얻는다.
    bash_lines = system_launch_env_lines(resolve_shell("bash", lane="system"))
    assert "$env:PADIEM_MCP_SHELL_CANDIDATES='" + ";".join(GIT_BASH_CANDIDATES) + "';" \
        in bash_lines


def test_user_lane_bash_passes_through_to_the_helper():
    """USER × bash: material shell 'bash' — R4 ④에서 wsl 번역 제거.

    헬퍼가 최종 허용 기관이고 이제 같은 후보 순서로 Git Bash를 찾아 실행한다.
    wsl은 어휘에서 완전히 제거되어 어느 레인에서도 선택되지 않는다.
    """
    assert resolve_shell("bash", lane="user") == "bash"
    import padiem_ai_core.pc_shell_selection as selection
    assert not hasattr(selection, "SHELL_WSL")


def test_bash_dispatch_carries_the_candidate_line_in_order(tmp_path):
    """bash 디스패처 명령문: 후보 줄이 런처 줄 뒤, 외부 powershell 호출 앞."""
    command = shell.build_pc_shell_command({"command": "echo ok", "shell": "bash"})
    head, _tail = command.split("-EncodedCommand ", 1)
    assert "$env:PADIEM_MCP_SHELL='bash';" in head
    assert system_launch_env_lines(resolve_shell("bash", lane="system")) in head
    assert head.index("PADIEM_MCP_SHELL_FILE") < head.index("PADIEM_MCP_SHELL_CANDIDATES")
    assert head.endswith("powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass ")


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="the candidate probe is Windows PowerShell behavior")
def test_all_candidates_missing_is_shell_unavailable_127(tmp_path):
    """후보 전부 부재 → shell_unavailable, exit 127 — PATH fallback 없음.

    네 루트 변수를 tmp_path 아래 빈 폴더로 격리하므로 Git for Windows가
    설치된 PC·Windows CI 러너에서도 결정론적으로 127이다. 이 기계에
    System32\\bash.exe(WSL)가 있어도 같은 결과여야 한다: 후보에 없는 이름은
    PATH로 잡지 않는 것이 이 변경의 본체다.
    """
    script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": "bash"}))
    env_lines = system_launch_env_lines(resolve_shell("bash", lane="system"))
    done = _run_tail(script, env_lines, b"echo 44",
                     extra_env=_isolated_root_lines(tmp_path))
    assert done.returncode == 127, done.stderr
    assert "shell_unavailable" in done.stderr
    assert "44" not in done.stdout


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="the candidate probe is Windows PowerShell behavior")
def test_the_first_existing_candidate_runs(tmp_path):
    """후보 탐색: (1) 없는 경로 (2) %변수% 가짜 bash (3) 다른 존재 가짜 bash.

    확장(%...%)·첫 후보 선택(break)·인자 전달(@args)을 실제로 검증한다:
    확장된 (2)가 실행되고 (3)은 실행되지 않으며, 출력에 -lc와 전달한 명령이
    그대로 있어야 한다. 아르곤 #7287 (d): 세 메커니즘 중 하나가 망가져도
    통과하던 위양성 구조를 고친 것.
    """
    missing = tmp_path / "missing-first" / "bash.exe"
    git_root = tmp_path / "gitroot"
    first = git_root / "bin" / "bash.cmd"
    first.parent.mkdir(parents=True)
    first.write_text("@echo FIRST_HIT %*\r\n", encoding="ascii")
    second_dir = tmp_path / "second"
    second_dir.mkdir()
    second = second_dir / "bash.cmd"
    second.write_text("@echo SECOND_HIT %*\r\n", encoding="ascii")
    script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": "bash"}))
    env_lines = (
        "$env:PADIEM_MCP_SHELL_FILE='bash.exe';"
        "$env:PADIEM_MCP_SHELL_ARGS='-lc';"
        "$env:PADIEM_MCP_SHELL_ENC='0';"
        "$env:PADIEM_MCP_SHELL_CANDIDATES='"
        + str(missing) + ";"
        + "%PADIEM_TEST_GIT_ROOT%\\bin\\bash.cmd;"
        + str(second) + "';"
    )
    extra_env = "$env:PADIEM_TEST_GIT_ROOT='" + str(git_root) + "';"
    done = _run_tail(script, env_lines, b"echo ok", extra_env=extra_env)
    assert done.returncode == 0, done.stderr
    # 확장된 (2)가 실행됐고 — %변수% 확장 검증.
    assert "FIRST_HIT" in done.stdout
    # (3)은 실행되지 않았고 — break 순서 검증.
    assert "SECOND_HIT" not in done.stdout
    # 받은 인자가 그대로 — prefix_args(-lc)와 명령 전달(@args) 검증.
    assert "-lc" in done.stdout
    assert "echo ok" in done.stdout


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="the candidate probe is Windows PowerShell behavior")
def test_the_table_candidates_never_pick_system32_wsl_bash(tmp_path):
    """표 후보로는 System32 WSL bash가 절대 잡히지 않는다(실측 회귀 방지).

    #7266에서 측정된 결함의 직접 재현 금지. 네 루트 변수를 빈 폴더로 격리해
    표 후보가 전부 부재인 상태를 어느 기계에서나 만들고, 그때 PATH의
    System32\\bash.exe(및 어떤 PATH 항목이든)가 잡히지 않음을 단언한다 —
    Git 설치 여부·WSL 설치 여부와 무관하게 결정론적이다.
    """
    script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": "bash"}))
    env_lines = system_launch_env_lines(resolve_shell("bash", lane="system"))
    done = _run_tail(script, env_lines, b"echo ok",
                     extra_env=_isolated_root_lines(tmp_path))
    assert done.returncode == 127, done.stderr
    assert "shell_unavailable" in done.stderr
    assert "ok" not in done.stdout


def _real_git_bash() -> "Path | None":
    """이 기계의 실제 Git Bash(레지스트리 → 표준 루트). 없으면 None.

    레지스트리·PATH 단계 시험은 실행 가능한 bash.exe가 필요하다 — 가짜로는
    ``& $file``이 실행되지 않는다. 그래서 이 기계의 진짜 Git Bash를 임시
    루트로 복사해 쓴다. Git for Windows가 없는 기계에서는 이 두 시험을
    건너뛴다(고정 후보·가드 시험은 건너뛰지 않고 결정론적으로 돈다).
    """
    try:
        import winreg
    except ImportError:
        return None
    for hive, subkey in (("HKEY_LOCAL_MACHINE", r"SOFTWARE\GitForWindows"),
                         ("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\GitForWindows"),
                         ("HKEY_CURRENT_USER", r"SOFTWARE\GitForWindows")):
        try:
            with winreg.OpenKey(getattr(winreg, hive), subkey) as key:
                install_path, _ = winreg.QueryValueEx(key, "InstallPath")
        except OSError:
            continue
        if isinstance(install_path, str) and install_path.strip():
            # usr\\bin\\bash.exe가 자기 위치 기준 재실행을 하지 않는 실체다
            # (bin\\bash.exe는 복사하면 ..\\usr\\bin을 찾아 실패한다).
            for leaf in ("usr", "bin"):
                candidate = Path(install_path) / leaf / "bin" / "bash.exe"
                if candidate.is_file():
                    return candidate
    for root in (r"%ProgramW6432%\Git",
                 r"%ProgramFiles%\Git",
                 r"%ProgramFiles(x86)%\Git",
                 r"%LocalAppData%\Programs\Git"):
        for leaf in ("usr", "bin"):
            candidate = Path(os.path.expandvars(root)) / leaf / "bin" / "bash.exe"
            if candidate.is_file():
                return candidate
    return None


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="the candidate probe is Windows PowerShell behavior")
@pytest.mark.skipif(_real_git_bash() is None,
                    reason="a runnable bash.exe is needed to prove the registry stage ran")
def test_registry_install_path_candidate_comes_first(tmp_path):
    """R4 ④ (a): 레지스트리 InstallPath 후보가 첫 단계다.

    Get-ItemProperty를 InstallPath만 돌려주는 함수로 대체하고, PATH
    git.exe 단계는 Get-Command 재정의로 끝내고, 고정 후보 루트는 빈 폴더로
    격리한다. 그 상태에서 bash가 실행됐다는 사실 자체가 '레지스트리 단계가
    고정 후보보다 먼저 잡혔다'는 순서의 증거다.
    """
    real_bash = _real_git_bash()
    assert real_bash is not None
    git_root = tmp_path / "regroot"
    bash = git_root / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    shutil.copyfile(real_bash, bash)
    script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": "bash"}))
    env_lines = system_launch_env_lines(resolve_shell("bash", lane="system"))
    stubs = ("function Get-ItemProperty { [pscustomobject]@{InstallPath=$env:PADIEM_TEST_GIT_ROOT} };"
             "function Get-Command { $null };")
    done = _run_tail(script, env_lines, b"echo ok",
                     extra_env="$env:PADIEM_TEST_GIT_ROOT='" + str(git_root) + "';"
                               + _isolated_root_lines(tmp_path),
                     stubs=stubs)
    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="the candidate probe is Windows PowerShell behavior")
@pytest.mark.skipif(_real_git_bash() is None,
                    reason="a runnable bash.exe is needed to prove the PATH stage ran")
def test_path_git_exe_relative_candidate_runs_when_registry_is_silent(tmp_path):
    """R4 ④ (b): PATH git.exe의 상대 위치 후보가 레지스트리 다음 단계다.

    Get-ItemProperty는 $null(레지스트리 없음), Get-Command는 cmd\git.exe
    모양의 Source를 돌려준다 — ..\bin\bash.exe 상대 탐색이 그 설치 루트의
    bin\bash.exe를 집는다. 고정 후보는 격리되어 있으므로 bash가
    실행됐다는 사실이 PATH 단계의 증거다.
    """
    real_bash = _real_git_bash()
    assert real_bash is not None
    git_root = tmp_path / "pathroot"
    (git_root / "cmd").mkdir(parents=True)
    (git_root / "cmd" / "git.exe").write_bytes(b"fake")
    bash = git_root / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    shutil.copyfile(real_bash, bash)
    script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": "bash"}))
    env_lines = system_launch_env_lines(resolve_shell("bash", lane="system"))
    stubs = ("function Get-ItemProperty { $null };"
             "function Get-Command { [pscustomobject]@{Source=$env:PADIEM_TEST_GIT_EXE} };")
    done = _run_tail(script, env_lines, b"echo ok",
                     extra_env="$env:PADIEM_TEST_GIT_EXE='" + str(git_root / "cmd" / "git.exe") + "';"
                               + _isolated_root_lines(tmp_path),
                     stubs=stubs)
    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="the candidate probe is Windows PowerShell behavior")
def test_a_registry_install_path_into_system32_is_refused(tmp_path):
    """R4 ④ 가드: System32 안의 bash.exe(WSL)는 레지스트리가 가리켜도 거부.

    InstallPath를 ...\Windows\System32로 위조하고 그 안에 bash.exe를
    심는다. 가드가 이를 거부해 다음 단계(격리된 빈 고정 후보)로 넘어가
    127이어야 한다 — #7266 결함의 레지스트리 변형 재현 금지. 실제
    C:\Windows\System32 대신 같은 모양의 임시 경로를 쓰므로 WSL 설치
    여부와 무관하게 결정론적이다.
    """
    # InstallPath → <InstallPath>inash.exe 체계를 그대로 따르므로,
    # System32 모양 경로 안에 Git 설치 루트를 심는다.
    fake_root = tmp_path / "Windows" / "System32" / "Git"
    (fake_root / "bin").mkdir(parents=True)
    (fake_root / "bin" / "bash.exe").write_text("not a real executable", encoding="ascii")
    script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": "bash"}))
    env_lines = system_launch_env_lines(resolve_shell("bash", lane="system"))
    stubs = ("function Get-ItemProperty { [pscustomobject]@{InstallPath=$env:PADIEM_TEST_SYSROOT} };"
             "function Get-Command { $null };")
    done = _run_tail(script, env_lines, b"echo ok",
                     extra_env="$env:PADIEM_TEST_SYSROOT='" + str(fake_root) + "';"
                               + _isolated_root_lines(tmp_path),
                     stubs=stubs)
    assert done.returncode == 127, done.stderr
    assert "shell_unavailable" in done.stderr
    assert "ok" not in done.stdout


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="the bash guard is Windows PowerShell behavior")
def test_the_bash_guard_normalizes_forward_slashes_before_the_system32_check():
    r"""가드가 `/`를 `\`로 정규화한 뒤 System32를 검사한다(아르곤 #7302 (b)-3).

    정규화가 없으면 ``C:/Windows/System32/bash.exe``가 substring 검사를
    통과한다 — Test-Path는 슬래시 혼용 경로를 그대로 받아들이므로 가드가
    뚫린다. 후보 문자열은 env/레지스트리에서 오고 슬래시가 섞일 수 있다.
    """
    script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": "bash"}))
    start = script.index("function _padiem_bash_ok")
    guard = script[start:script.index("\n", start)]
    probe = (
        # 존재 검사를 통과시켜 substring 가드만 측정 대상으로 남긴다.
        "function Test-Path { param($LiteralPath,$Path,$PathType) return $true };"
        + guard
        + r"if(_padiem_bash_ok 'C:/Windows/System32/bash.exe'){'SLASH_PICKED'}"
          r"else{'SLASH_REFUSED'};"
          r"if(_padiem_bash_ok 'C:\Windows\System32\bash.exe'){'BS_PICKED'}"
          r"else{'BS_REFUSED'};"
          r"if(_padiem_bash_ok 'C:/Program Files/Git/bin/bash.exe'){'OK_PICKED'}"
          r"else{'OK_REFUSED'};"
    )
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", probe],
        capture_output=True, text=True, timeout=60,
    )
    assert "SLASH_REFUSED" in done.stdout, done.stdout + done.stderr
    assert "BS_REFUSED" in done.stdout, done.stdout + done.stderr
    assert "OK_PICKED" in done.stdout, done.stdout + done.stderr
