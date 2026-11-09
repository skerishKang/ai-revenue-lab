"""#7188 R4 ② — one shell-selection table, both lanes, behavior unchanged.

경로별 선택 결과 표(변경 전 = 변경 후)를 값까지 고정한다. 변경 전의 선택은
세 곳에 흩어져 있었다: 채팅 화이트리스트(PC_SHELL_SHELLS), SYSTEM 디스패처
스크립트 안의 ``$env:PADIEM_MCP_SHELL`` 분기, 사용자 material의 bash→wsl
수동 매핑. 변경 후에는 전부 ``padiem_ai_core.pc_shell_selection`` 한 표를
거치고, 각 경로가 고르는 결과는 아래 표와 같다. R4 ④(#7188 후속)에서 사용자
bash는 wsl 번역 없이 그대로 전달되고, 헬퍼가 같은 후보 순서로 Git Bash를
찾아 실행한다(대표 결정: 컴1에서 WSL 금지, bash는 Git Bash만).

| 경로                    | 변경 전 선택(흩어진 코드)                              | 변경 후 선택(resolve_shell)                            |
|-------------------------|--------------------------------------------------------|--------------------------------------------------------|
| SYSTEM × powershell     | 디스패처 분기: powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand(b64 UTF-16LE) | 동일(SystemShellLaunch)                                |
| SYSTEM × cmd            | cmd.exe /d /s /c <c>                                   | 동일                                                    |
| SYSTEM × bash           | bash.exe -lc <c>(PATH 탐색 → System32 WSL bash가 잡힘) | Git Bash 표준 설치 경로 후보 순서 탐색, 없으면 shell_unavailable(127) |
| SYSTEM × 셸 생략         | powershell 기본                                        | 동일(PC_SHELL_DEFAULT_NAME)                             |
| SYSTEM × 미지원 이름     | 채팅 화이트리스트가 도구 오류로 거부(실행기 도달 불가)   | 동일 + 공통 UnknownShellName 예외                       |
| USER × powershell / cmd | material shell 그대로 통과                              | 동일                                                    |
| USER × bash             | material shell 'wsl'(R4 ④에서 제거)                     | material shell 'bash' — 헬퍼가 Git Bash를 직접 실행      |
| USER × whoami 명령       | material shell 'whoami'(명령 우선)                      | 동일                                                    |
| USER × 셸 생략           | powershell 기본                                        | 동일                                                    |
| USER × 미지원 이름       | 채팅 거부(도달 불가), 헬퍼가 최종 거절 유지              | 동일                                                    |

저널 문자열(R4 ① 위상 상수)은 이 변경이 닿지 않는다. 헬퍼(PC 측 단일 파일
빌드)는 최종 허용 기관으로 그대로 둔다 — 이름 집합과 거절이 바뀌지 않는다.
"""
from __future__ import annotations

import base64
import shutil
import subprocess

import pytest

from padiem_ai_core.pc_shell_selection import (
    GIT_BASH_CANDIDATES,
    PC_SHELL_DEFAULT_NAME,
    SystemShellLaunch,
    UnknownShellName,
    resolve_shell,
    resolve_user_helper_shell,
    system_launch_env_lines,
)

from app import mcp_gateway_shell as shell


def _script_of(command_text: str) -> str:
    return base64.b64decode(
        command_text.rsplit("-EncodedCommand ", 1)[1]
    ).decode("utf-16-le")


def test_system_lane_launch_table_is_pinned():
    """SYSTEM × {powershell, cmd, bash}: 변경 전 디스패처 분기와 같은 값."""
    assert resolve_shell("powershell", lane="system") == SystemShellLaunch(
        file="powershell.exe",
        prefix_args=("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-OutputFormat", "Text", "-EncodedCommand"),
        encode_command=True,
    )
    assert resolve_shell("cmd", lane="system") == SystemShellLaunch(
        file="cmd.exe", prefix_args=("/d", "/s", "/c"), encode_command=False,
    )
    assert resolve_shell("bash", lane="system") == SystemShellLaunch(
        file="bash.exe", prefix_args=("-lc",), encode_command=False,
        candidates=GIT_BASH_CANDIDATES,
    )


def test_user_lane_helper_names_are_pinned():
    """USER × {powershell, cmd, bash, whoami 명령}: 변경 전 material 매핑과 같은 값."""
    assert resolve_shell("powershell", lane="user") == "powershell"
    assert resolve_shell("cmd", lane="user") == "cmd"
    assert resolve_shell("bash", lane="user") == "bash"
    # whoami 명령은 셸 이름보다 우선한다 — 변경 전 build_pc_shell_user_material과
    # 같은 순서, 같은 strip 규칙.
    for name in ("powershell", "cmd", "bash"):
        assert resolve_user_helper_shell(name, command="whoami") == "whoami"
        assert resolve_user_helper_shell(name, command="  whoami  ") == "whoami"
        assert resolve_user_helper_shell(name, command="whoami.exe") != "whoami"


def test_default_shell_is_powershell_on_every_path():
    """셸 생략: 모든 경로가 같은 기본값(powershell)을 쓴다."""
    with_default = shell.build_pc_shell_command({"command": "echo ok"})
    explicit = shell.build_pc_shell_command({"command": "echo ok", "shell": "powershell"})
    assert with_default == explicit
    assert shell.normalize_pc_shell_arguments({"command": "x"})["shell"] == "powershell"
    assert shell.normalize_pc_shell_start_arguments({"command": "x"})["shell"] == "powershell"
    assert shell.normalize_pc_shell_arguments({"command": "x"})["shell"] == PC_SHELL_DEFAULT_NAME
    import json
    material = json.loads(shell.build_pc_shell_user_material({"command": "hostname"}))
    assert material["shell"] == "powershell"


def test_dispatcher_script_has_no_shell_branch_left():
    """분기 제거: 스크립트가 $env:PADIEM_MCP_SHELL을 읽지 않는다."""
    for name in ("powershell", "cmd", "bash"):
        script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": name}))
        assert "$env:PADIEM_MCP_SHELL " not in script
        assert "PADIEM_MCP_SHELL -eq" not in script
        assert "$file='" not in script
        # 이름 대신 표가 결정한 런처 데이터를 읽는다.
        assert "$env:PADIEM_MCP_SHELL_FILE" in script
        assert "$env:PADIEM_MCP_SHELL_ARGS.Split(' ')" in script
        assert "$env:PADIEM_MCP_SHELL_ENC -eq '1'" in script


def test_system_launch_lines_are_exact_and_ordered():
    """런처 세 줄: 표 상수 그대로, 이름 줄 뒤 외부 powershell 호출 앞."""
    expected = {
        "powershell":
            "$env:PADIEM_MCP_SHELL_FILE='powershell.exe';"
            "$env:PADIEM_MCP_SHELL_ARGS='-NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand';"
            "$env:PADIEM_MCP_SHELL_ENC='1';",
        "cmd":
            "$env:PADIEM_MCP_SHELL_FILE='cmd.exe';"
            "$env:PADIEM_MCP_SHELL_ARGS='/d /s /c';"
            "$env:PADIEM_MCP_SHELL_ENC='0';",
        "bash":
            "$env:PADIEM_MCP_SHELL_FILE='bash.exe';"
            "$env:PADIEM_MCP_SHELL_ARGS='-lc';"
            "$env:PADIEM_MCP_SHELL_ENC='0';"
            "$env:PADIEM_MCP_SHELL_CANDIDATES='"
            + ";".join(GIT_BASH_CANDIDATES) + "';",
    }
    for name, lines in expected.items():
        assert system_launch_env_lines(resolve_shell(name, lane="system")) == lines
        command = shell.build_pc_shell_command({"command": "echo ok", "shell": name})
        assert lines in command
        head, tail = command.split("-EncodedCommand ", 1)
        assert lines in head
        assert "$env:PADIEM_MCP_SHELL='" + name + "';" in head
        assert head.index("$env:PADIEM_MCP_SHELL='") < head.index("PADIEM_MCP_SHELL_FILE")
        assert head.endswith("powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass ")


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="the generic tail is Windows PowerShell behavior")
def test_generic_tail_runs_each_launcher_like_the_old_branch():
    """제거된 분기와 같은 결과: 인자 배열·종료 코드·미지원 거부를 실제 PS로.

    #7188 R4 ③: 꼬리는 후보 목록 분기가 앞에 붙는다. powershell·cmd는
    후보가 없으므로 else 가지(Get-Command)가 실행되며 그 결과는 변경 전과
    같다 — 이 시험이 그 세 경로를 실제 PowerShell로 다시 증명한다.
    """
    # R4 ④: bash 가지는 레지스트리 → PATH git.exe → 고정 후보 순서가 앞에 붙는다.
    # cmd·powershell은 $cands가 비어 있으므로 else 가지가 그대로 실행된다.
    # R4 ④: bash 가지는 레지스트리 → PATH git.exe → 고정 후보 순서가 앞에 붙는다.
    # cmd·powershell은 $cands가 비어 있으므로 else 가지가 그대로 실행된다.
    tail_start = "try{$cands=$env:PADIEM_MCP_SHELL_CANDIDATES;if($cands){$file=$null;foreach($k in 'HKLM:\\SOFTWARE\\GitForWindows','HKLM:\\SOFTWARE\\WOW6432Node\\GitForWindows','HKCU:\\SOFTWARE\\GitForWindows'){$ip=(Get-ItemProperty -Path $k -ErrorAction SilentlyContinue).InstallPath;if($ip){$p=Join-Path $ip 'bin\\bash.exe';if(_padiem_bash_ok $p){$file=$p;break}}};"
    script = _script_of(shell.build_pc_shell_command({"command": "echo ok", "shell": "cmd"}))
    assert tail_start in script
    # cmd: 인자 배열 뒤 명령 본문이 위치 순서로 붙는다(변경 전 @('/d','/s','/c',$c)).
    probe = (
        "$env:PADIEM_MCP_SHELL_FILE='cmd.exe';"
        "$env:PADIEM_MCP_SHELL_ARGS='/d /s /c';"
        "$env:PADIEM_MCP_SHELL_ENC='0';"
        "$env:PADIEM_MCP_COMMAND_B64='" + base64.b64encode(b"echo 42").decode() + "';"
        "$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PADIEM_MCP_COMMAND_B64));"
        + script[script.index("try{$cands="):]
    )
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", probe],
        capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0
    assert "42" in done.stdout
    # powershell: 인코딩 경로도 같은 argv 모양(-OutputFormat Text -EncodedCommand).
    probe_ps = (
        "$env:PADIEM_MCP_SHELL_FILE='powershell.exe';"
        "$env:PADIEM_MCP_SHELL_ARGS='-NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand';"
        "$env:PADIEM_MCP_SHELL_ENC='1';"
        "$env:PADIEM_MCP_COMMAND_B64='" + base64.b64encode(b"Write-Output 43").decode() + "';"
        "$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PADIEM_MCP_COMMAND_B64));"
        + script[script.index("try{$cands="):]
    )
    done_ps = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", probe_ps],
        capture_output=True, text=True, timeout=60,
    )
    assert done_ps.returncode == 0
    assert "43" in done_ps.stdout
    # 셸 미발견: 변경 전과 같은 stderr 문자열과 exit 127.
    probe_missing = (
        "$env:PADIEM_MCP_SHELL_FILE='padiem-missing-shell-7188.exe';"
        "$env:PADIEM_MCP_SHELL_ARGS='-lc';"
        "$env:PADIEM_MCP_SHELL_ENC='0';"
        "$env:PADIEM_MCP_COMMAND_B64='" + base64.b64encode(b"echo 44").decode() + "';"
        "$c=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PADIEM_MCP_COMMAND_B64));"
        + script[script.index("try{$cands="):]
    )
    done_missing = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", probe_missing],
        capture_output=True, text=True, timeout=60,
    )
    assert done_missing.returncode == 127
    assert "shell_unavailable" in done_missing.stderr


def test_unsupported_name_is_refused_the_same_for_both_modes():
    """미지원 이름: 두 모드가 같은 검증 오류로 거부되고, 표는 같은 예외를 던진다."""
    for mode_enabled in (False, True):
        assert not shell.validate_pc_shell_arguments(
            {"command": "x", "shell": "fish"}, user_mode_enabled=mode_enabled)
        assert not shell.validate_pc_shell_start_arguments(
            {"command": "x", "shell": "fish"}, user_mode_enabled=mode_enabled)
    with pytest.raises(ValueError):
        shell.build_pc_shell_command({"command": "x", "shell": "fish"})
    with pytest.raises(ValueError):
        shell.build_pc_shell_user_material({"command": "x", "shell": "fish"})
    with pytest.raises(UnknownShellName):
        resolve_shell("fish", lane="system")
    with pytest.raises(UnknownShellName):
        resolve_shell("fish", lane="user")
    # 헬퍼 전용 이름(whoami/wsl)은 도구 어휘가 아니므로 도구에서도 거부된다.
    assert not shell.validate_pc_shell_arguments({"command": "x", "shell": "wsl"})


def test_user_material_mapping_is_unchanged():
    """사용자 material: 변경 전 build_pc_shell_user_material과 같은 JSON 값."""
    import json
    assert json.loads(shell.build_pc_shell_user_material(
        {"command": "hostname", "shell": "powershell"}))["shell"] == "powershell"
    assert json.loads(shell.build_pc_shell_user_material(
        {"command": "hostname", "shell": "cmd"}))["shell"] == "cmd"
    assert json.loads(shell.build_pc_shell_user_material(
        {"command": "systemctl is-active padiem", "shell": "bash"}))["shell"] == "bash"
    assert json.loads(shell.build_pc_shell_user_material(
        {"command": "whoami", "shell": "bash"}))["shell"] == "whoami"
    # 셸 이름 별칭도 같은 값을 가리킨다(기존 import 보존).
    assert shell.USER_HELPER_SHELL_FOR_BASH == "bash"
    assert shell.USER_HELPER_SHELL_FOR_WHOAMI == "whoami"
