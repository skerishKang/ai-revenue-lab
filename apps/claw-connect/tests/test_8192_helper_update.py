"""#8192: exercise the real updater with only temporary files and fake ports."""
from __future__ import annotations

import base64
import gzip
import os
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from claw_connect.user_helper_service import serve_pipe

ROOT = Path(__file__).resolve().parents[3]
UPDATER = runpy.run_path(str(ROOT / "apps/padiem-chat/app/pc_helper_update.py"))


def test_mesh_commands_contain_only_the_fixed_payload():
    for unregister in (False, True):
        command = UPDATER["mesh_helper_updater_command"](unregister=unregister)
        assert len(command) < 32767
        decoded = base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16-le")
        payload = re.search(r"FromBase64String\('([^']+)'\)", decoded)[1]
        assert gzip.decompress(base64.b64decode(payload)).decode() == UPDATER["helper_update_script"]()
        assert decoded.endswith("-Unregister" if unregister else "-Register -SourceText $source")


def test_installer_wrapper_uses_the_same_reviewed_updater():
    wrapper = (ROOT / "scripts/pc_pairing/install-padiem-pc.ps1").read_text(encoding="utf-8-sig")
    block = wrapper.split("function Register-PadiemHelperUpdater {", 1)[1].split("\n}", 1)[0]
    payload = re.search(r"FromBase64String\('([^']+)'\)", block)[1]
    assert gzip.decompress(base64.b64decode(payload)).decode() == UPDATER["helper_update_script"]()


def test_helper_drain_defers_until_live_session_ends():
    class Sessions:
        def __init__(self):
            self.calls = 0

        def has_live_sessions(self):
            self.calls += 1
            return self.calls == 1

    class Listener:
        def __init__(self):
            self.accepts = 0

        def accept(self, timeout):
            self.accepts += 1
            return None

    listener = Listener()
    ready = []
    result = serve_pipe(device_id="test", secret=b"fixture", listener=listener,
                        sessions=Sessions(), update_requested=lambda: True,
                        announce_ready=lambda: ready.append(True))
    assert result.served == 0
    assert listener.accepts == 1
    assert ready == [True]


def test_helper_drain_does_not_end_an_inflight_command(monkeypatch):
    import threading

    from claw_connect import user_helper_service

    entered = threading.Event()
    release = threading.Event()
    workers = []

    def execute(*args, **kwargs):
        workers.append(threading.current_thread())
        entered.set()
        assert release.wait(2)
        return "served"

    class Sessions:
        def has_live_sessions(self):
            return False

    class Listener:
        accepts = 0

        def accept(self, timeout):
            self.accepts += 1
            if self.accepts == 1:
                return object()
            assert entered.wait(2)
            assert workers[0].is_alive()
            release.set()
            workers[0].join(2)
            assert not workers[0].is_alive()
            return None

    monkeypatch.setattr(user_helper_service, "handle_connection", execute)
    listener = Listener()
    result = serve_pipe(device_id="test", secret=b"fixture", listener=listener,
                        sessions=Sessions(), update_requested=lambda: listener.accepts > 0)
    assert listener.accepts == 2
    assert result.served == 1


_PS_TEST = r'''
param([string]$Source,[string]$TestRoot,[string]$Case)
$ErrorActionPreference = 'Stop'
. $Source -LibraryOnly
function Assert($condition,$message) { if (-not $condition) { throw $message } }
$script:Root = $TestRoot
$script:Exe = Join-Path $TestRoot 'helper.exe'
$script:Status = Join-Path $TestRoot 'status.json'
$script:Candidate = Join-Path $TestRoot 'candidate.exe'
$script:Journal = Join-Path $TestRoot 'journal.json'
$script:Backup = Join-Path $TestRoot 'previous.exe'
if ($Case -eq 'urls') {
    $sid = [Security.Principal.SecurityIdentifier]::new('S-1-5-21-100-200-300-1001')
    $sd = [Security.AccessControl.RawSecurityDescriptor]::new((Get-UpdateTaskSddl $sid))
    $userAce = @($sd.DiscretionaryAcl | Where-Object {$_.SecurityIdentifier.Value -eq $sid.Value})
    Assert ($userAce.Count -eq 1 -and $userAce[0].AccessMask -eq 0x1200a9) 'user task permission not read/execute only'
    Assert ($sd.DiscretionaryAcl.Count -eq 3) 'unexpected task access'
    Assert ($sd.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected) 'task inherits access'
    Assert (Test-AllowedUri 'https://downloads.padiem.net/pc-helper/1.2.3/padiem-user-helper.exe' 'downloads.padiem.net') 'valid host refused'
    foreach ($url in @('http://downloads.padiem.net/x','https://downloads.padiem.net.attacker.test/x',
        'https://downloads.padiem.net@attacker.test/x','https://downloads.padiem.net:444/x')) {
        Assert (-not (Test-AllowedUri $url 'downloads.padiem.net')) 'wrong host accepted'
    }
    function New-UpdateRequest($url) {
        $request = [PSCustomObject]@{AllowAutoRedirect=$true;Timeout=0;ReadWriteTimeout=0}
        $request | Add-Member ScriptMethod GetResponse {
            if ($this.AllowAutoRedirect) { throw 'redirect_followed' }
            $response = [PSCustomObject]@{StatusCode=302;ResponseUri=[Uri]'https://attacker.test/x'}
            $response | Add-Member ScriptMethod Dispose {}
            return $response
        }
        return $request
    }
    try { [void](Get-CheckedResponse 'https://downloads.padiem.net/x' 'downloads.padiem.net'); throw 'accepted_redirect' }
    catch { Assert ($_.Exception.Message -eq 'update_redirect_or_response') 'redirect rejection was not checked' }
    exit 0
}
[IO.File]::WriteAllText($script:Exe,'old')
$oldSha = Get-UpdateDigest $script:Exe
$old = @{status='installed';sha256=$oldSha;version='0.3.0-rc1';device_id='fixture'}
[IO.File]::WriteAllText($script:Status,($old | ConvertTo-Json))
$statusAcl = Get-Acl -LiteralPath $script:Status
$statusAcl.SetAccessRuleProtection($true,$true)
Set-Acl -LiteralPath $script:Status -AclObject $statusAcl
$acl = Get-Acl -LiteralPath $script:Exe
$acl.SetAccessRuleProtection($true,$true)
Set-Acl -LiteralPath $script:Exe -AclObject $acl
$beforeAcl = Get-UpdateAcl $script:Exe
$other = Join-Path $TestRoot 'not-the-helper.exe'
[IO.File]::WriteAllText($other,'untouched')
$script:nextFile = Join-Path $TestRoot 'fixture-download'
[IO.File]::WriteAllText($script:nextFile,'new')
$script:nextSha = Get-UpdateDigest $script:nextFile
$script:clock = [DateTime]::Parse('2026-01-01T00:00:00Z').ToUniversalTime()
$script:busy = $Case -in @('busy','minimum')
$script:started = 0
$script:downloads = 0
function Get-UpdateNow { $script:clock }
function Wait-UpdateTick {
    $script:clock = $script:clock.AddMinutes(1)
    if ($Case -eq 'minimum' -and $script:clock.Minute -eq 11) { $script:busy = $false }
}
function Get-HelperTask { [PSCustomObject]@{State='Ready'} }
function Get-TaskSid($task) { [Security.Principal.WindowsIdentity]::GetCurrent().User }
function Read-UpdatePreference($sid) {
    [PSCustomObject]@{auto=($Case -notin @('off','manual'));manual=$(if ($Case -eq 'manual') {'0.3.1'})}
}
function Get-HelperProcesses { if ($script:busy) { [PSCustomObject]@{ExecutablePath=$script:Exe} } }
function Get-CimInstance { [PSCustomObject]@{UserName='fixture'} }
function New-UpdateEvent($name,$userSid,[switch]$SignalByUser) {
    $event = [Threading.EventWaitHandle]::new($false,'ManualReset')
    if ($SignalByUser) { $script:readyEvent = $event }
    return $event
}
function Read-UpdateStatus([switch]$Recover) { Get-Content -LiteralPath $script:Status -Raw | ConvertFrom-Json }
function Get-Manifest {
    [PSCustomObject]@{version='0.3.1';sha256=$script:nextSha;min_supported_version='0.3.1';
        download_url='https://downloads.padiem.net/pc-helper/0.3.1/padiem-user-helper.exe';path=$other;command='not allowed'}
}
function Receive-UpdateFile($url,$hostName,$path,$maxBytes) {
    $script:downloads++
    if ($Case -eq 'hash') { [IO.File]::WriteAllText($path,'wrong') }
    else { [IO.File]::Copy($script:nextFile,$path) }
}
function Get-AuthenticodeSignature { param($LiteralPath) [PSCustomObject]@{Status='NotSigned'} }
function Start-OriginalHelper {
    $script:started++
    if ($Case -in @('success','minimum','manual')) { [void]$script:readyEvent.Set() }
}
function Enable-OriginalHelper {}
function Disable-OriginalHelper {}
function Test-HelperReady($status) { $Case -in @('success','minimum','manual') }
function Test-HelperPipe($status) { $false }
function Stop-ScheduledTask { throw 'never stop a real task' }
Invoke-HelperUpdate
$result = Get-Content -LiteralPath $script:Status -Raw | ConvertFrom-Json
Assert ((Get-UpdateAcl $script:Exe) -eq $beforeAcl) 'ACL changed'
Assert ([IO.File]::ReadAllText($other) -eq 'untouched') 'server path was used'
Assert (-not (Test-Path -LiteralPath $script:Candidate)) 'candidate not removed'
Assert ($script:downloads -eq $(if ($Case -eq 'off') {0} else {1})) 'unexpected download count'
switch ($Case) {
    'off' {
        Assert ($result.update_result -eq 'available') 'availability not recorded'
        Assert ($result.update_available_version -eq '0.3.1') 'available version missing'
        Assert ((Get-UpdateDigest $script:Exe) -eq $oldSha) 'opt-out replaced file'
        Assert ($script:started -eq 0) 'opt-out restarted task'
    }
    'hash' {
        Assert ($result.update_result -eq 'hash_mismatch') 'hash mismatch not recorded'
        Assert ((Get-UpdateDigest $script:Exe) -eq $oldSha) 'hash mismatch replaced file'
        Assert ($script:started -eq 0) 'hash mismatch restarted task'
    }
    'busy' {
        Assert ($result.update_result -eq 'deferred') 'busy not deferred'
        Assert ((Get-UpdateDigest $script:Exe) -eq $oldSha) 'busy helper replaced'
        Assert ($script:started -eq 0) 'busy helper restarted'
    }
    'rollback' {
        Assert ($result.update_result -eq 'rollback') 'rollback not recorded'
        Assert ((Get-UpdateDigest $script:Exe) -eq $oldSha) 'old bytes not restored'
        Assert ($result.version -eq '0.3.0-rc1') 'old version not restored'
        Assert (-not (Test-Path -LiteralPath $script:Journal)) 'transaction not cleared'
    }
    {$_ -in @('success','minimum','manual')} {
        if ($Case -eq 'minimum') { Assert ($script:clock.Minute -ge 11) 'minimum did not wait for idle' }
        Assert ($result.update_result -eq 'success') 'success not recorded'
        Assert ((Get-UpdateDigest $script:Exe) -eq $script:nextSha) 'new bytes not placed'
        Assert ($result.version -eq '0.3.1') 'new version not recorded'
        Assert (-not (Test-Path -LiteralPath $script:Journal)) 'transaction not cleared'
    }
}
'''


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL and PowerShell updater")
@pytest.mark.parametrize("case", ["urls", "hash", "busy", "minimum", "rollback", "success", "off", "manual"])
def test_updater_windows_contract(tmp_path, case):
    source = tmp_path / "update.ps1"
    driver = tmp_path / "driver.ps1"
    source.write_text(UPDATER["helper_update_script"](), encoding="utf-8")
    driver.write_text(_PS_TEST, encoding="utf-8")
    shell = shutil.which("powershell.exe")
    assert shell
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(driver), "-Source", str(source), "-TestRoot", str(tmp_path), "-Case", case],
        # Windows PowerShell needs its own module path when launched from pwsh.
        env={key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
