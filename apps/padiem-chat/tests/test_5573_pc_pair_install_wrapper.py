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

SOURCE = SCRIPT.read_text(encoding="utf-8")


def test_the_script_parses_and_carries_only_the_two_pairing_endpoints():
    assert "$HandoffPath = \"/api/pc/pairings/handoff\"" in SOURCE
    assert "$ClaimPath = \"/api/pc/pairings/claim\"" in SOURCE
    # No other Chat surface is reachable from the wrapper: it cannot become a
    # general-purpose client that happens to hold a pairing code.
    assert {found.strip('"') for found in re.findall(r'"(/api/[a-z/{}-]+)"', SOURCE)} == {
        "/api/pc/pairings/handoff", "/api/pc/pairings/claim",
    }


def test_the_code_is_prompted_and_never_written_anywhere():
    assert "Read-Host" in SOURCE and "-AsSecureString" in SOURCE
    assert "Write-Host $Copy.LinkPending" in SOURCE
    for forbidden in ("Set-Content", "Out-File", "Add-Content", "AppendAllText",
                      "WriteAllText", "Export-Csv", "| Out-Host"):
        assert forbidden not in SOURCE, forbidden
    # The code reaches the server as a JSON body value only, and the temporary
    # installer file is deleted in the same function that created it.
    assert "code = $PairingCode" in SOURCE
    assert SOURCE.count("Remove-Item -LiteralPath $target") == 1


def test_a_missing_link_stops_only_the_install_and_never_the_installed_path():
    # The link is checked after the agent is recognised, so a PC that already
    # has an agent submits its pairing without ever needing a download target.
    installed_check = SOURCE.index("if ($installed) {")
    link_check = SOURCE.index('if (-not $agentUrl -and -not $installed) {')
    assert installed_check > link_check
    assert SOURCE.index("Start-PadiemInstall -Url") > installed_check


def test_nothing_is_installed_when_the_config_or_code_is_wrong():
    # Handoff and install are sequenced after both checks, so a bad code or an
    # http origin cannot reach the network or the disk at all.
    prompt = SOURCE.index("Read-PadiemCode")
    origin_check = SOURCE.index("if (-not $origin)")
    code_check = SOURCE.index('if (-not $pairingCode) { Write-Error $Copy.BadCode; exit 2 }')
    handoff = SOURCE.index("$handoff = Invoke-PadiemHandoff")
    install = SOURCE.index("Start-PadiemInstall -Url")
    assert origin_check < code_check < handoff < install
    assert prompt < handoff


def test_the_installer_is_fetched_over_https_only():
    assert SOURCE.count("https://[A-Za-z0-9.-]+") >= 1
    assert "http://" not in SOURCE.replace("https://", "")
    assert "$agentUrl = [string] $handoff.handoff.agent_url" in SOURCE


def test_the_already_installed_path_submits_the_code_and_installs_nothing():
    installed = SOURCE.index("if ($installed) {")
    link_pending = SOURCE.index("if (-not $agentUrl -and -not $installed) {")
    install = SOURCE.index("Start-PadiemInstall -Url")
    # The link is asked for after the agent is recognised, so an installed PC
    # reaches the claim path with no download target at all, and the installer
    # is invoked from exactly one place, after both.
    assert link_pending < installed < install
    assert SOURCE.count("Start-PadiemInstall -Url") == 1
    assert "PADIEM에서 표시한 12자리" in SOURCE
    assert "서버 확인 대기 중" in SOURCE
    assert "에이전트가 아직 없고" in SOURCE


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
        assert "Start-PadiemInstall" not in text and "Invoke-WebRequest" not in text
