"""#8213: resolve a real interactive account without querying the test PC."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from app.pc_pairing_connect_exe_asset import connect_exe_bytes

REPO = Path(__file__).resolve().parents[3]


def test_8213_console_lookup_is_shared_and_queries_the_computer_system() -> None:
    import textwrap

    from app.pc_pairing_agent_install import render_user_helper_install_block

    source = (REPO / "scripts/pc_pairing/connect-exe/PadiemPcConnect.cs").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert 'new ManagementObjectSearcher(\n                "SELECT UserName FROM Win32_ComputerSystem")' in source
    assert "Win32_ComputerSystem.Name='.'" not in source
    native = source.split("    public static class PadiemSessionLookup", 1)[1]
    native = native.split("\n    internal static class PadiemPcConnect", 1)[0]
    shared = "public static class PadiemSessionLookup" + textwrap.dedent(native).rstrip()
    block = render_user_helper_install_block()
    assert shared in block
    wrapper = (REPO / "scripts/pc_pairing/install-padiem-pc.ps1").read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    assert shared in wrapper


@pytest.mark.skipif(sys.platform != "win32", reason="tests the compiled Windows installer")
def test_8213_compiled_session_lookup_falls_back_and_records_failures(tmp_path: Path) -> None:
    import subprocess

    target = tmp_path / "connect.exe"
    target.write_bytes(connect_exe_bytes())
    harness = tmp_path / "lookup.ps1"
    harness.write_text(r"""
param([string] $Target)
$ErrorActionPreference = 'Stop'
[void][Reflection.Assembly]::LoadFile($Target)
$t = [Padiem.Connect.PadiemSessionLookup]
$reason = ""
$never = [Func[string]] { throw "unexpected lookup" }
foreach ($user in @('CGI-1\sji', 'MicrosoftAccount\example@example.com')) {
    $result = $t::Resolve([Func[string]] { $user }, $never, $never, [ref]$reason)
    if ($result -ne $user -or $reason -ne "") { throw "WMI account rejected" }
}
$failWmi = [Func[string]] { throw [InvalidOperationException]::new("private detail") }
$empty = [Func[string]] { return $null }
$rdp = [Func[string]] { 'PC\remote' }
$result = $t::Resolve($failWmi, [Func[string]] { 'PC\console' }, $never, [ref]$reason)
if ($result -ne 'PC\console' -or $reason -notmatch '^wmi_failed:\w+$') { throw "console fallback: $reason" }
$result = $t::Resolve($failWmi, $empty, $rdp, [ref]$reason)
if ($result -ne 'PC\remote' -or $reason -notmatch '^wmi_failed:\w+;wts_console_no_user$') { throw "RDP fallback: $reason" }
$result = $t::Resolve($failWmi, $empty, $empty, [ref]$reason)
if ($result -or $reason -notmatch '^wmi_failed:\w+;wts_console_no_user;wts_rdp_no_user$') { throw "failure reason: $reason" }
if ($t::SingleRdpSession([uint32[]]@()) -ne $null) { throw "empty RDP" }
if ($t::SingleRdpSession([uint32[]]@(7)) -ne 7) { throw "single RDP" }
$rejected = $false
try { [void]$t::SingleRdpSession([uint32[]]@(7,8)) } catch { $rejected = $true }
if (-not $rejected) { throw "ambiguous RDP accepted" }
Write-Output LOOKUP_OK
""", encoding="utf-8")
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(harness), str(target)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "LOOKUP_OK" in done.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="executes the PowerShell install lookup")
def test_8213_powershell_session_lookup_with_simulated_wts(tmp_path: Path) -> None:
    import re
    import subprocess

    from app.pc_pairing_agent_install import render_user_helper_install_block

    block = render_user_helper_install_block()
    function = block.split("function Get-PadiemConsoleUser {", 1)[1]
    function = "function Get-PadiemConsoleUser {" + function.split("function Get-PadiemAccountSid", 1)[0]
    native = function.split("@'\n", 1)[1].split("\n'@", 1)[0]
    # Substitute only the two OS calls; keep the production validation and
    # resolver, and compile the actual WTS declarations in the same process.
    mock = re.sub(
        r"public static string ConsoleUser\(\)\n    \{.*?\n    \}",
        'public static string ConsoleUser() { return ConsoleFixture; }\n'
        '    public static string ConsoleFixture;',
        native, flags=re.S,
    )
    mock = re.sub(
        r"public static string RdpUser\(\)\n    \{.*?\n    \}",
        'public static string RdpUser() { return RdpFixture; }\n'
        '    public static string RdpFixture;',
        mock, flags=re.S,
    )
    assert mock != native
    harness = tmp_path / "lookup.ps1"
    harness.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "Add-Type -TypeDefinition @'\n" + native.replace("PadiemSessionLookup", "NativeCompileCheck") + "\n'@\n"
        "Add-Type -TypeDefinition @'\n" + mock + "\n'@\n" + function + r"""
$script:wmi = 'CGI-1\sji'
function Get-CimInstance {
    if ($script:wmi) { return [pscustomobject]@{ UserName = $script:wmi } }
    throw [InvalidOperationException]::new("fixture")
}
$reason = ""
if ((Get-PadiemConsoleUser -Reason ([ref]$reason)) -ne $script:wmi -or $reason) { throw "WMI" }
$script:wmi = ""
[PadiemSessionLookup]::ConsoleFixture = 'PC\console'
if ((Get-PadiemConsoleUser -Reason ([ref]$reason)) -ne 'PC\console' -or $reason -notmatch '^wmi_failed:\w+$') { throw "console: $reason" }
[PadiemSessionLookup]::ConsoleFixture = $null
[PadiemSessionLookup]::RdpFixture = 'PC\remote'
if ((Get-PadiemConsoleUser -Reason ([ref]$reason)) -ne 'PC\remote' -or $reason -notmatch ';wts_console_no_user$') { throw "RDP: $reason" }
[PadiemSessionLookup]::RdpFixture = $null
if ((Get-PadiemConsoleUser -Reason ([ref]$reason)) -or $reason -notmatch ';wts_console_no_user;wts_rdp_no_user$') { throw "failure: $reason" }
Write-Output LOOKUP_OK
""", encoding="utf-8")
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "LOOKUP_OK" in done.stdout
