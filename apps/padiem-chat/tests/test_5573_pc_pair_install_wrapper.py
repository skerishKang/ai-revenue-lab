"""#5573 PR-4b: the Windows wrapper cannot leak the proof it was handed.

The wrapper runs on a customer PC, so the properties that matter are about the
code: it is prompted, never persisted, and never accepted from anywhere but the
person standing at the machine. These checks read the shipped script, and the
refusal paths are executed on a Windows host where PowerShell is present.
"""
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/pc_pairing/install-padiem-pc.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")

SOURCE = SCRIPT.read_text(encoding="utf-8-sig")


def test_the_script_parses_and_carries_only_the_two_pairing_endpoints():
    assert "$HandoffPath = \"/api/pc/pairings/handoff\"" in SOURCE
    assert "$ClaimPath = \"/api/pc/pairings/claim\"" in SOURCE
    # No other Chat surface is reachable from the wrapper: it cannot become a
    # general-purpose client that happens to hold a pairing code.
    assert {found.strip('"') for found in re.findall(r'"(/api/[a-z/{}-]+)"', SOURCE)} == {
        "/api/pc/pairings/handoff", "/api/pc/pairings/claim",
    }


def test_the_wrapper_is_utf8_with_a_bom():
    # Windows PowerShell 5.1 reads a BOM-less file in the machine's own code
    # page, which is how the Korean sentences this script says turn into
    # unreadable bytes on the customer's PC. The server-rendered lane has
    # carried the byte-order mark from the start; the wrapper must too.
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_the_code_is_prompted_and_never_written_anywhere():
    assert "Read-Host" in SOURCE and "-AsSecureString" in SOURCE
    assert "Write-Host $Copy.LinkPending" in SOURCE
    for forbidden in ("Set-Content", "Out-File", "Add-Content", "AppendAllText",
                      "WriteAllText", "Export-Csv", "| Out-Host"):
        assert forbidden not in SOURCE, forbidden
    # The code reaches the server as a JSON body value only, and the temporary
    # installer file is deleted in the same function that created it.
    assert "code = $PairingCode" in SOURCE
    assert SOURCE.count("Remove-Item -LiteralPath $installer") == 1


def test_a_missing_link_stops_only_the_install_and_never_the_installed_path():
    # The link is checked after the agent is recognised, so a PC that already
    # has an agent submits its pairing without ever needing a download target.
    installed_check = SOURCE.index("if ($installed) {")
    link_check = SOURCE.index('if (-not $agentUrl -and -not $installed) {')
    assert installed_check > link_check
    download = SOURCE.index("Save-PadiemInstaller -Url")
    install = SOURCE.index("Install-PadiemAgentService -SourceExe")
    assert installed_check < download < install


def test_nothing_is_installed_when_the_config_or_code_is_wrong():
    # Handoff and install are sequenced after both checks, so a bad code or an
    # http origin cannot reach the network or the disk at all.
    prompt = SOURCE.index("Read-PadiemCode")
    origin_check = SOURCE.index("if (-not $origin)")
    code_check = SOURCE.index("if (-not $pairingCode) { Write-Error $Copy.BadCode; exit 2 }")
    handoff = SOURCE.index("$handoff = Invoke-PadiemHandoff")
    install = SOURCE.index("Install-PadiemAgentService -SourceExe")
    assert origin_check < code_check < handoff < install
    assert prompt < handoff


def test_the_installer_is_fetched_over_https_only():
    assert SOURCE.count("https://[A-Za-z0-9.-]+") >= 1
    assert "http://" not in SOURCE.replace("https://", "")
    assert "$agentUrl = [string] $handoff.handoff.agent_url" in SOURCE


def test_the_installed_agent_is_told_the_name_that_carries_the_pairing():
    """The tag only claims a PC once the server can see it in the agent's name.

    So the install step has to hand the name over, and hand it over as one
    argument: the drive list this script reports sits after the tag inside the
    same quoted value, spaces and all - and the shared install block passes it
    exactly the way the double-click program does, as ``--agentName="..."``.
    """
    assert "$agentName = Format-PadiemAgentName -Tag $tag" in SOURCE
    assert "Get-PadiemDriveRoots" in SOURCE
    assert "-AgentName $agentName" in SOURCE
    assert """('--agentName="' + $AgentName + '"')""" in SOURCE
    assert "$Arguments -split" not in SOURCE
    # The switch is the measured one: -install from the durable folder. The
    # -fullinstall switch that exited 0 and registered nothing appears nowhere
    # as a command - only in the comment that records why it is gone.
    assert '"-fullinstall"' not in SOURCE
    assert "-install" in SOURCE


def test_the_install_sequence_is_the_measured_walk_in_order():
    """stop through the recorded binary, durable copy, -install, -start, check.

    The order is the double-click program's own (#6066), and the service status
    is read back rather than assumed - a registered-but-stopped service is
    reported, never silently passed off as a connected PC.
    """
    stop = SOURCE.index('Start-Process -FilePath $registered -ArgumentList "-stop"')
    copy = SOURCE.index("Copy-Item -LiteralPath $SourceExe -Destination $PadiemAgentDurableExe")
    install = SOURCE.index('"-install"')
    start = SOURCE.index('"-start"')
    status = SOURCE.index("Get-Service -Name $PadiemAgentServiceName")
    assert stop < copy < install < start < status
    # The durable folder is the product's own, under the real Program Files:
    # -install keeps the folder it ran from in the service record, so a temp
    # folder would become a service that cannot start after cleanup.
    assert 'Join-Path $env:ProgramFiles "PADIEM"' in SOURCE
    assert "MeshAgent.exe" in SOURCE
    # One service name, so a re-run updates in place instead of registering a
    # second service beside the first.
    assert '$PadiemAgentServiceName = "Mesh Agent"' in SOURCE


def test_the_already_installed_path_submits_the_code_and_installs_nothing():
    installed = SOURCE.index("if ($installed) {")
    link_pending = SOURCE.index("if (-not $agentUrl -and -not $installed) {")
    download = SOURCE.index("Save-PadiemInstaller -Url")
    install = SOURCE.index("Install-PadiemAgentService -SourceExe")
    # The link is asked for after the agent is recognised, so an installed PC
    # reaches the claim path with no download target at all, and the installer
    # is downloaded and invoked from exactly one place, after both.
    assert link_pending < installed < download < install
    assert SOURCE.count("Save-PadiemInstaller -Url") == 1
    assert SOURCE.count("Install-PadiemAgentService -SourceExe") == 1
    assert "PADIEM에서 표시한 12자리" in SOURCE
    assert "서버 확인 대기 중" in SOURCE
    assert "에이전트가 아직 없고" in SOURCE


def test_the_elevation_prompt_covers_the_whole_sequence_and_refusal_is_named():
    """One approval, before the first privileged step; a refusal keeps a code."""
    assert "IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)" in SOURCE
    # The run asks once, in the flow, before the download - and the DryRun
    # point-check never needs the token, so it never prompts.
    elevation_run = SOURCE.index("if (-not $DryRun) { Assert-PadiemElevation }")
    download_call = SOURCE.index("Save-PadiemInstaller -Url")
    assert elevation_run < download_call
    assert "catch [System.ComponentModel.Win32Exception]" in SOURCE
    assert SOURCE.count("exit 5") == 1


def test_the_wrapper_parses():
    """A script this PC is asked to run has to at least read as PowerShell."""
    if POWERSHELL is None:
        import pytest
        pytest.skip("PowerShell is not installed on this host")
    command = (
        "$t=$null;$e=$null;"
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        "'" + str(SCRIPT) + "',[ref]$t,[ref]$e);"
        "if($e.Count -gt 0){$e | ForEach-Object {Write-Output $_.Message}; exit 1}"
        "else {Write-Output PARSE_OK; exit 0}"
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", command],
        capture_output=True, timeout=120,
    )
    text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert result.returncode == 0, text[:400]
    assert "PARSE_OK" in result.stdout.decode("utf-8", errors="replace")


def test_the_two_refusal_paths_execute_and_refuse():
    if POWERSHELL is None:
        import pytest
        pytest.skip("PowerShell is not installed on this host")
    for args, needle in (
        (["-ChatOrigin", "http://chat.example.net", "-Code", "K7QM2XTR9F4B"],
         "https"),
        (["-ChatOrigin", "https://chat.example.net", "-Code", "short"], "install-padiem-pc"),
    ):
        # A console codepage this host may not speak is not a reason to lose the
        # check: the refusal is proven by a nonzero exit, by the script naming
        # itself in the error, and by the message being the operator's language
        # rather than an English stack trace.
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(SCRIPT), *args],
            capture_output=True, timeout=120,
        )
        text = (result.stdout + result.stderr).decode("cp949", errors="replace")
        assert result.returncode != 0, (args, text[:400])
        assert "install-padiem-pc.ps1" in text, (args, text[:400])
        assert needle.lower() in text.lower(), (args, text[:400])
        assert "Install-PadiemAgentService" not in text and "Invoke-WebRequest" not in text
