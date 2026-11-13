"""#7108 PR-2 — the one-click install also provisions the user-session helper.

The helper is optional, and that word is load-bearing: the MeshCentral agent
that came up is the install's success criterion, so every helper failure is
written to ``helper-status.json`` and returns false without unwinding the
connection or asking for a second elevation.

What the contract fixes:

* the helper EXE is downloaded from the deployment's own versioned URL and its
  SHA-256 is checked before anything is placed in ``%ProgramData%\\Padiem``;
* the secret is 32 random bytes, new on every install; SYSTEM and the
  administrators have it in full, the console user (read from
  ``Win32_ComputerSystem.UserName``, not the elevated installer account) may
  read it, and its value never reaches the console or the status (#7564 -
  ``test_7564_helper_install_lockdown.py`` holds the lock-down contract);
* the task is ``\\Padiem\\PadiemUserSessionHelper``, ONLOGON, Interactive,
  Limited, started immediately;
* the same sequence exists in both ``.ps1`` lanes and in the double-click EXE,
  and the ``--device-id`` written into the task is the pairing tag (a PR-3
  executor reads that same argument and derives the pipe from it).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing            # noqa: E402

from app.pc_device_pairing_routes import (                # noqa: E402
    PC_PAIRING_CONNECT_EXE_MARKER,
    PC_PAIRING_HANDOFF_PATH,
    PC_PAIRING_INSTALL_EXE_FILENAME,
    connect_exe_trailer,
    render_install_exe,
    render_install_script,
    user_helper_config,
)
from app.pc_pairing_agent_install import (                # noqa: E402
    render_user_helper_install_block,
)

REPO = Path(__file__).resolve().parents[3]
AGENT_URL = "https://mesh.example.padiem.net/meshagents?id=4&meshid=c9yfFkUpi38"
HELPER_URL = "https://downloads.example.padiem.net/pc-helper/padiem-user-helper-7108.exe"
HELPER_SHA = "0123456789abcdef" * 4
TAG = "pd-1234abcd"


def _script(**overrides):
    values = {
        "install_tag": TAG,
        "agent_url": AGENT_URL,
        "user_helper_url": HELPER_URL,
        "user_helper_sha256": HELPER_SHA.upper(),
    }
    values.update(overrides)
    return render_install_script(**values)


# -- 1. the helper step exists, in the required order ------------------------

def test_the_rendered_file_installs_the_agent_then_the_helper() -> None:
    script = _script()
    assert script is not None

    block = render_user_helper_install_block()
    assert block in script
    assert f"$PadiemUserHelperUrl = '{HELPER_URL}'" in script
    # The digest is normalized to the lowercase shape the deployment pins.
    assert f"$PadiemUserHelperSha256 = '{HELPER_SHA}'" in script

    agent_install = script.index(
        "if (-not (Install-PadiemAgentService -SourceExe $agent -AgentName $reported))"
    )
    helper_call = script.index(
        "if (Install-PadiemUserHelper -Url $PadiemUserHelperUrl"
    )
    final_message = script.index('Write-Host "연결 진행 중')
    assert agent_install < helper_call < final_message

    # Inside the helper (#7564): lock the folder, download, verify, end a
    # running helper, clear what does not belong, place, new secret, read the
    # install back, task, status.
    lock = script.index(
        "$refusal = Protect-PadiemHelperStateDir -Path $PadiemUserHelperStateDir"
    )
    download = script.index("Invoke-WebRequest -Uri $Url -OutFile $temp")
    verify = script.index("$actual = Get-PadiemSha256 -Path $temp")
    mismatch = script.index('$status.reason = "sha256_mismatch"')
    stop = script.index("Stop-PadiemUserHelper -HelperExe $PadiemUserHelperExe")
    clear = script.index(
        "Move-PadiemHelperForeignContent -StateDir $PadiemUserHelperStateDir"
    )
    place = script.index(
        "Copy-PadiemHelperProgram -Source $temp -Target $PadiemUserHelperExe"
    )
    secret = script.index("New-PadiemHelperSecret -Path $PadiemUserHelperSecret")
    read_back = script.index("$fault = Get-PadiemHelperInstallFault -UserSid $userSid")
    task = script.index(
        "Register-PadiemUserHelperTask -HelperExe $PadiemUserHelperExe"
    )
    status = script.index('$status.status = "installed"')
    assert (
        lock < download < verify < mismatch < stop < clear < place < secret
        < read_back < task < status
    )

    # The paths and the task identity are the ones the helper source uses.
    assert 'Join-Path $env:ProgramData "Padiem"' in script
    assert '"helper.secret"' in script
    assert '"helper-status.json"' in script
    assert '$PadiemUserHelperTaskFolder = "\\Padiem\\"' in script
    assert '$PadiemUserHelperTaskName = "PadiemUserSessionHelper"' in script
    assert "New-ScheduledTaskTrigger -AtLogOn -User $ConsoleUser" in script
    assert (
        "New-ScheduledTaskPrincipal -UserId $ConsoleUser -LogonType Interactive "
        "-RunLevel Limited"
    ) in script
    assert "Start-ScheduledTask -TaskName $PadiemUserHelperTaskName" in script


def test_the_task_runs_as_the_console_user_not_the_elevated_installer() -> None:
    script = _script()
    assert script is not None
    assert "Win32_ComputerSystem" in script
    assert "$consoleUser = Get-PadiemConsoleUser" in script
    assert "New-ScheduledTaskPrincipal -UserId $ConsoleUser" in script
    # The process identity is never used as the task principal: that is the
    # elevated administrator token, not the person standing at the PC.
    assert "WindowsIdentity]::GetCurrent().Name" not in script


def test_the_helper_secret_is_32_bytes_and_never_printed() -> None:
    script = _script()
    assert script is not None
    block = render_user_helper_install_block()
    assert "New-Object byte[] 32" in block
    assert "RandomNumberGenerator" in block

    for line in script.splitlines():
        if "Write-Host" in line or "Write-Output" in line:
            assert "PadiemUserHelperSecret" not in line, line
            assert "$hex" not in line, line
            assert "$bytes" not in line, line

    status_writer = block[
        block.index("function Write-PadiemHelperStatus"):
        block.index("function Register-PadiemUserHelperTask")
    ]
    assert "$PadiemUserHelperSecret" not in status_writer
    # The status is local evidence, and its only file writes are the status
    # writer and the secret writer; neither emits the value to the console.
    assert "ConvertTo-Json" in status_writer


def test_a_helper_failure_never_ends_the_agent_install() -> None:
    script = _script()
    assert script is not None
    start = script.index("if (Install-PadiemUserHelper -Url $PadiemUserHelperUrl")
    end = script.index('Write-Host "연결 진행 중')
    call = script[start:end]
    assert "exit" not in call.lower()
    assert "PC 연결은 계속 진행됩니다" in call
    # The agent failure path keeps its own exit, before the helper call.
    assert script.index("에이전트 설치를 마치지 못했습니다") < start


def test_an_unconfigured_helper_omits_the_step_and_keeps_the_agent_install() -> None:
    plain = render_install_script(install_tag=TAG, agent_url=AGENT_URL)
    assert plain is not None
    assert "Install-PadiemUserHelper -Url" not in plain
    assert "$PadiemUserHelperUrl" not in plain
    # The shared definitions stay available to the wrapper; only the call is
    # absent, so an older deployment installs exactly the agent it always did.
    assert "function Install-PadiemUserHelper" in plain
    assert "Install-PadiemAgentService -SourceExe" in plain

    half = render_install_script(
        install_tag=TAG, agent_url=AGENT_URL, user_helper_url=HELPER_URL,
    )
    assert half is not None
    assert "Install-PadiemUserHelper -Url" not in half


# -- 2. the deployment value is a reviewed URL plus a digest ----------------

def test_helper_config_needs_both_a_reviewed_https_url_and_a_digest() -> None:
    assert user_helper_config(HELPER_URL, HELPER_SHA.upper()) == (HELPER_URL, HELPER_SHA)
    for url, sha in (
        (None, HELPER_SHA),
        (HELPER_URL, None),
        ("http://downloads.example.padiem.net/helper.exe", HELPER_SHA),
        ("https://user@downloads.example.padiem.net/helper.exe", HELPER_SHA),
        (HELPER_URL, "0" * 63),
        (HELPER_URL, "g" * 64),
        (HELPER_URL, HELPER_SHA + "0"),
    ):
        assert user_helper_config(url, sha) is None, (url, sha)


def test_the_program_trailer_carries_the_helper_before_the_agent_link() -> None:
    trailer = connect_exe_trailer(
        install_tag=TAG, agent_url=AGENT_URL,
        user_helper_url=HELPER_URL, user_helper_sha256=HELPER_SHA.upper(),
    )
    assert trailer is not None
    assert trailer.decode("ascii") == (
        f"{PC_PAIRING_CONNECT_EXE_MARKER}\r\n"
        f"PADIEMTAG:{TAG}\r\n"
        f"PADIEMHELPERURL:{HELPER_URL}\r\n"
        f"PADIEMHELPERSHA:{HELPER_SHA}\r\n"
        f"PADIEMURL:{AGENT_URL}\r\n"
    )
    # The last line stays the one older programs already read.
    assert trailer.decode("ascii").endswith(f"PADIEMURL:{AGENT_URL}\r\n")

    plain = connect_exe_trailer(install_tag=TAG, agent_url=AGENT_URL)
    assert plain is not None
    assert b"PADIEMHELPER" not in plain


# -- 3. the handoff names the same pair both .ps1 lanes run -----------------

def test_the_handoff_names_the_same_helper_pair() -> None:
    store = pairing.store()
    app = pairing.app_with(store)
    app.state.pc_pairing_install_url = AGENT_URL
    app.state.pc_pairing_user_helper_url = HELPER_URL
    app.state.pc_pairing_user_helper_sha256 = HELPER_SHA
    issued = pairing.run(store.issue_code(user_id=pairing.OWNER, issued_at=pairing._now()))

    async def once():
        async with pairing.client(app) as session:
            return await session.post(
                PC_PAIRING_HANDOFF_PATH, json={"code": issued["code"]},
            )

    response = pairing.run(once())
    assert response.status_code == 200, response.text
    handoff = response.json()["handoff"]
    assert handoff["user_helper_url"] == HELPER_URL
    assert handoff["user_helper_sha256"] == HELPER_SHA


def test_an_unconfigured_deployment_hands_out_no_helper_pair() -> None:
    store = pairing.store()
    app = pairing.app_with(store)
    app.state.pc_pairing_install_url = AGENT_URL
    issued = pairing.run(store.issue_code(user_id=pairing.OWNER, issued_at=pairing._now()))

    async def once():
        async with pairing.client(app) as session:
            return await session.post(
                PC_PAIRING_HANDOFF_PATH, json={"code": issued["code"]},
            )

    response = pairing.run(once())
    assert response.status_code == 200, response.text
    handoff = response.json()["handoff"]
    assert handoff["user_helper_url"] is None
    assert handoff["user_helper_sha256"] is None


# -- 4. both .ps1 lanes and the .exe lane run the same walk -----------------

def test_both_ps1_lanes_carry_the_same_helper_block() -> None:
    block = render_user_helper_install_block()
    wrapper = (REPO / "scripts/pc_pairing/install-padiem-pc.ps1").read_text(
        encoding="utf-8-sig",
    )
    assert block in wrapper
    assert (
        "Invoke-PadiemUserHelperInstall -Url $helperUrl -Sha256 $helperSha -Tag $tag"
    ) in wrapper
    assert "$deviceId = Get-PadiemHelperDeviceId -Tag $Tag" in wrapper

    script = _script()
    assert script is not None
    assert block in script
    # The one-click file uses the tag it already carries as the device id; the
    # wrapper uses the tag it just received from the handoff. PR-3 reads this
    # same --device-id out of the task argument, so both sides derive one pipe.
    assert "Get-PadiemHelperDeviceId -Tag $PairingTag" in script
    assert '--device-id "' in block


def test_the_double_click_program_runs_the_helper_after_the_agent() -> None:
    source = (
        REPO / "scripts" / "pc_pairing" / "connect-exe" / "PadiemPcConnect.cs"
    ).read_text(encoding="utf-8")
    assert 'const string KeyHelperUrl = "PADIEMHELPERURL";' in source
    assert 'const string KeyHelperSha256 = "PADIEMHELPERSHA";' in source
    assert "static bool InstallUserHelper(string tag)" in source
    # One status write for every outcome; each failure is its own fixed reason.
    assert (
        'WriteUserHelperStatus(reason.Length == 0 ? "installed" : "not_installed",'
        in source
    )
    assert 'return "sha256_mismatch";' in source
    assert "Environment.SpecialFolder.CommonApplicationData" in source
    assert "new byte[32]" in source
    assert "Win32_ComputerSystem.Name='.'" in source
    assert "<RunLevel>LeastPrivilege</RunLevel>" in source
    assert "<LogonType>InteractiveToken</LogonType>" in source
    assert 'const string UserHelperTaskFolder = "\\\\Padiem\\\\";' in source
    assert "helper-status.json" in source

    agent_start = source.index('RunQuiet(durable, "-start");')
    helper_call = source.index("if (helperConfigured)")
    uninstaller = source.index("if (!RegisterUninstaller())")
    assert agent_start < helper_call < uninstaller
    call = source[helper_call:uninstaller]
    assert "return Exit" not in call
    assert "PC 연결은 계속 진행됩니다" in call


@pytest.mark.skipif(sys.platform != "win32", reason="the artifact is a Windows program")
def test_the_shipped_program_reports_and_plans_the_helper(tmp_path: Path) -> None:
    """The rebuilt artifact reads the new trailer keys, not just the source."""
    import subprocess

    program = render_install_exe(
        install_tag=TAG, agent_url=AGENT_URL,
        user_helper_url=HELPER_URL, user_helper_sha256=HELPER_SHA,
    )
    assert program is not None
    target = tmp_path / PC_PAIRING_INSTALL_EXE_FILENAME
    target.write_bytes(program)

    checked = subprocess.run(
        [str(target), "--check"], capture_output=True, text=True,
        encoding="utf-8", timeout=120, check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    lines = dict(line.split("=", 1) for line in checked.stdout.splitlines())
    assert lines["CONNECT_EXE_CHECK_HELPER_URL_PRESENT"] == "1", lines
    assert lines["CONNECT_EXE_CHECK_HELPER_SHA_PRESENT"] == "1", lines

    planned = subprocess.run(
        [str(target), "--dry-run"], capture_output=True, text=True,
        encoding="utf-8", timeout=120, check=False,
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    assert "내려받아 SHA-256 검증" in planned.stdout, planned.stdout
