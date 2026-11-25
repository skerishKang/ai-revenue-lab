"""Fixed SYSTEM helper updater script and offline Mesh registration command."""
from __future__ import annotations

import base64
import gzip

_UPDATE_SCRIPT = r'''param([switch]$Register, [switch]$Unregister, [switch]$LibraryOnly, [string]$SourceText)
$ErrorActionPreference = 'Stop'
$script:UpdateTask = 'PadiemUserHelperUpdater'
$script:HelperTask = 'PadiemUserSessionHelper'
$script:TaskFolder = '\Padiem\'
$script:Manifest = 'https://chat.padiem.net/api/pc/helper-version'
$script:ProgramData = [Environment]::GetFolderPath('CommonApplicationData')
$script:Root = Join-Path $script:ProgramData 'PadiemHelperUpdater'
$script:Exe = Join-Path $script:ProgramData 'Padiem\padiem-user-helper.exe'
$script:Status = Join-Path $script:ProgramData 'Padiem\helper-status.json'
$script:ScriptFile = Join-Path $script:Root 'update.ps1'
$script:Journal = Join-Path $script:Root 'pending.json'
$script:Backup = Join-Path $script:Root 'previous.exe'
$script:Candidate = Join-Path $script:Root 'candidate.exe'
$script:Trusted = @('S-1-5-18','S-1-5-32-544')
$script:DrainName = 'Global\PadiemHelperUpdateDrain'
$script:ReadyName = 'Global\PadiemHelperUpdateReady'

function Get-UpdateNow { [DateTime]::UtcNow }
function Wait-UpdateTick { Start-Sleep -Seconds 2 }
function Get-UpdateDigest($path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Get-OwnerSid($acl) { $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value }
function Get-UpdateAcl($path) {
    $acl = Get-Acl -LiteralPath $path
    $acl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]'Owner,Group,Access')
}
function Get-AclFacts($acl) {
    $sid = [Security.Principal.SecurityIdentifier]
    $rules = @($acl.GetAccessRules($true,$true,$sid) | ForEach-Object {
        "$($_.IdentityReference.Value)|$($_.AccessControlType)|$([int64]$_.FileSystemRights)|$($_.InheritanceFlags)|$($_.PropagationFlags)|$($_.IsInherited)"
    } | Sort-Object)
    return (@((Get-OwnerSid $acl),$acl.GetGroup($sid).Value,[string]$acl.AreAccessRulesProtected) + $rules) -join ';'
}
function Test-UpdateAcl($path,$sddl) {
    $expected = New-Object Security.AccessControl.FileSecurity
    $expected.SetSecurityDescriptorSddlForm($sddl,[Security.AccessControl.AccessControlSections]'Owner,Group,Access')
    return ((Get-AclFacts (Get-Acl -LiteralPath $path)) -eq (Get-AclFacts $expected))
}
function Assert-Locked($path, [switch]$Private) {
    $item = Get-Item -LiteralPath $path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'reparse_point' }
    $acl = Get-Acl -LiteralPath $path
    if (-not $acl.AreAccessRulesProtected -or $script:Trusted -notcontains (Get-OwnerSid $acl)) { throw 'unsafe_owner_or_inheritance' }
    foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -ne 'Allow') { continue }
        if ($script:Trusted -contains $rule.IdentityReference.Value) { continue }
        # Only read/execute/synchronize can be granted to an interactive user.
        if ($Private -or ([int64]$rule.FileSystemRights -band (-bnot 0x1200a9))) { throw 'unsafe_write_access' }
    }
}
function New-PrivateRoot {
    if (-not (Test-Path -LiteralPath $script:Root)) {
        $security = New-Object Security.AccessControl.DirectorySecurity
        $security.SetSecurityDescriptorSddlForm('O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)')
        [void][IO.Directory]::CreateDirectory($script:Root,$security)
    }
    Assert-Locked $script:Root -Private
}
function Set-UpdateAcl($path,$sddl) {
    $security = New-Object Security.AccessControl.FileSecurity
    $security.SetSecurityDescriptorSddlForm($sddl,[Security.AccessControl.AccessControlSections]'Owner,Group,Access')
    Set-Acl -LiteralPath $path -AclObject $security
}
function Move-Atomic($source,$target,$expectedHash) {
    # #8359 후속3: [IO.File]::Replace는 대상 옆에 백업 파일을 만들어야 하고
    # 대상·백업 경로가 잠기거나 읽기 전용이면 MethodInvocationException으로
    # 실패한다. 대상과 같은 폴더에 임시 파일을 쓰고 ACL을 물려받고 해시를
    # 확인한 뒤 같은 볼륨에서 Move-Item으로 덮어쓴다. 임시 파일은 finally에서
    # 정리하고, 검증 전에는 원본을 건드리지 않는다. Test-UpdateAcl은 그대로
    # 교체 뒤에 실행한다.
    $acl = Get-UpdateAcl $target
    $staged = "$target.stage"
    if (Test-Path -LiteralPath $staged) { throw 'unexpected_staging_file' }
    try {
        Copy-Item -LiteralPath $source -Destination $staged -Force
        Set-UpdateAcl $staged $acl
        $digest = Get-UpdateDigest $staged
        if ($digest -ne $expectedHash -or $digest -ne (Get-UpdateDigest $source)) {
            throw 'staged_digest_mismatch'
        }
        Move-Item -LiteralPath $staged -Destination $target -Force
        if (-not (Test-UpdateAcl $target $acl)) { throw 'replacement_acl_changed' }
    } finally {
        if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Force }
    }
}
function Replace-WithoutBackup($source,$target) {
    Move-Atomic $source $target (Get-UpdateDigest $source)
    # .NET Replace는 원본을 소비한다. Move-Item은 복사본만 옮기므로 남은
    # 스테이징 원본을 여기서 지워야 다음 쓰기가 같은 이름으로 막히지 않는다.
    if (Test-Path -LiteralPath $source) { Remove-Item -LiteralPath $source -Force }
}
function Write-AtomicJson($path,$value) {
    $tmp = "$path.new"
    if (Test-Path -LiteralPath $tmp) { throw 'unexpected_staging_file' }
    $payload = ($value | ConvertTo-Json -Compress -Depth 8)
    [IO.File]::WriteAllText($tmp,$payload,[Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $path) {
        Replace-WithoutBackup $tmp $path
    } else { [IO.File]::Move($tmp,$path) }
}
function Read-UpdateStatus([switch]$Recover) {
    Assert-Locked (Split-Path $script:Exe)
    Assert-Locked $script:Exe
    Assert-Locked $script:Status
    $s = Get-Content -LiteralPath $script:Status -Raw | ConvertFrom-Json
    if ($s.status -ne 'installed' -or $s.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or
        $s.device_id -notmatch '^[A-Za-z0-9_.$:@+\-]{1,256}$') { throw 'invalid_install_record' }
    if (-not $Recover -and (Get-UpdateDigest $script:Exe) -ne $s.sha256) { throw 'installed_digest_mismatch' }
    return $s
}
function Set-Result($status,$result) {
    $status | Add-Member -NotePropertyName update_result -NotePropertyValue $result -Force
    # A running updater supersedes an earlier registration failure.
    $status.PSObject.Properties.Remove('update_registration_error')
    if ($status.PSObject.Properties['reason']) {
        $reason = ([string]$status.reason) -replace '(^|;)update_registration_failed:[a-z_]+$', ''
        if ($reason) { $status.reason = $reason }
        else { $status.PSObject.Properties.Remove('reason') }
    }
    $oldAcl = Get-UpdateAcl $script:Status
    Write-AtomicJson $script:Status $status
    if (-not (Test-UpdateAcl $script:Status $oldAcl)) { throw 'status_acl_changed' }
}
function Test-AllowedUri($uri,$hostName) {
    $u = $null
    if (-not [Uri]::TryCreate([string]$uri,[UriKind]::Absolute,[ref]$u)) { return $false }
    return ($u.Scheme -eq 'https' -and $u.IdnHost -eq $hostName -and $u.Port -eq 443 -and
        -not $u.UserInfo -and -not $u.Fragment -and -not $u.Query)
}
function New-UpdateRequest($url) { [Net.HttpWebRequest]::Create([Uri]$url) }
function Get-CheckedResponse($url,$hostName,$deviceId) {
    if (-not (Test-AllowedUri $url $hostName)) { throw 'invalid_update_url' }
    $request = New-UpdateRequest $url
    # The device identifier goes only to the fixed manifest origin, never to
    # the artifact download host or to a redirected request.
    if ($url -ceq $script:Manifest -and $deviceId -match '^[A-Za-z0-9_.$:@+\-]{1,256}$') {
        $request.Headers['X-Padiem-Device-Id'] = $deviceId
    }
    $request.AllowAutoRedirect = $false
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 30000
    $response = $request.GetResponse()
    if ([int]$response.StatusCode -ne 200 -or -not (Test-AllowedUri $response.ResponseUri.AbsoluteUri $hostName)) {
        $response.Dispose()
        throw 'update_redirect_or_response'
    }
    return $response
}
function Receive-UpdateFile($url,$hostName,$path,$maxBytes,$deviceId) {
    $response = Get-CheckedResponse $url $hostName $deviceId
    try {
        $stream = $response.GetResponseStream()
        $file = [IO.File]::Open($path,'CreateNew','Write','None')
        try {
            $buffer = New-Object byte[] 65536
            $total = 0L
            $deadline = (Get-UpdateNow).AddMinutes(5)
            while (($n = $stream.Read($buffer,0,$buffer.Length)) -gt 0) {
                $total += $n
                if ((Get-UpdateNow) -gt $deadline) { throw 'update_download_timeout' }
                if ($total -gt $maxBytes) { throw 'update_too_large' }
                $file.Write($buffer,0,$n)
            }
        } finally { $file.Dispose(); $stream.Dispose() }
    } finally { $response.Dispose() }
}
function Get-Manifest($deviceId) {
    $path = Join-Path $script:Root 'manifest.json'
    try {
        Receive-UpdateFile $script:Manifest 'chat.padiem.net' $path 16384 $deviceId
        $m = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($m.sha256 -notmatch '^[0-9a-f]{64}$' -or -not (Test-AllowedUri $m.download_url 'downloads.padiem.net') -or
            -not (Get-VersionParts $m.version) -or -not (Get-VersionParts $m.min_supported_version)) { throw 'invalid_manifest' }
        if ((Compare-Version $m.version $m.min_supported_version) -lt 0) { throw 'inconsistent_minimum' }
        if (([Uri]$m.download_url).AbsolutePath -ne "/pc-helper/$($m.version)/padiem-user-helper.exe") { throw 'invalid_manifest_path' }
        return $m
    } finally { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force } }
}
function Get-VersionParts($value) {
    if ([string]$value -notmatch '^([0-9]{1,5})\.([0-9]{1,5})\.([0-9]{1,5})(?:-rc([0-9]{1,5}))?$') { return $null }
    $rank = if ($Matches[4]) { [int]$Matches[4] } else { 100000 }
    return @([int]$Matches[1],[int]$Matches[2],[int]$Matches[3],$rank)
}
function Compare-Version($left,$right) {
    $a = Get-VersionParts $left; $b = Get-VersionParts $right
    if (-not $a -or -not $b) { throw 'unknown_version' }
    for ($i=0;$i -lt 4;$i++) {
        if ($a[$i] -lt $b[$i]) { return -1 }
        if ($a[$i] -gt $b[$i]) { return 1 }
    }
    return 0
}
function Get-HelperTask {
    $task = Get-ScheduledTask -TaskName $script:HelperTask -TaskPath $script:TaskFolder
    if (@($task.Actions).Count -ne 1 -or $task.Actions[0].Execute -ne $script:Exe -or
        [string]$task.Principal.RunLevel -ne 'Limited' -or [string]$task.Principal.LogonType -ne 'Interactive') { throw 'unexpected_helper_task' }
    return $task
}
function Get-HelperProcesses {
    $all = @(Get-CimInstance Win32_Process -Filter "Name='padiem-user-helper.exe'")
    foreach ($p in $all) {
        if (-not $p.ExecutablePath) { throw 'process_path_unknown' }
        if ($p.ExecutablePath -eq $script:Exe) { $p }
    }
}
function Test-HelperPipe($status) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($status.device_id))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
    $pipe = "\\.\pipe\padiem-user-helper-dev_$($hash.Substring(0,32))"
    return (@([IO.Directory]::GetFiles('\\.\pipe\')) -contains $pipe)
}
function Test-HelperReady($status) {
    return ((Get-HelperTask).State -eq 'Running' -and (Test-HelperPipe $status))
}
function New-UpdateEvent($name,$userSid,[switch]$SignalByUser) {
    $rights = if ($SignalByUser) { 'Modify,Synchronize' } else { 'Synchronize' }
    $security = New-Object Security.AccessControl.EventWaitHandleSecurity
    $security.SetAccessRuleProtection($true,$false)
    foreach ($sid in $script:Trusted) {
        $security.AddAccessRule([Security.AccessControl.EventWaitHandleAccessRule]::new(
            [Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))
    }
    $security.AddAccessRule([Security.AccessControl.EventWaitHandleAccessRule]::new($userSid,$rights,'Allow'))
    $created = $false
    $handle = [Threading.EventWaitHandle]::new($false,'ManualReset',$name,[ref]$created,$security)
    if (-not $created) { $handle.Dispose(); throw 'event_already_exists' }
    return $handle
}
function Get-TaskSid($task) {
    $id = [string]$task.Principal.UserId
    if ($id -match '^S-1-') { return [Security.Principal.SecurityIdentifier]::new($id) }
    return ([Security.Principal.NTAccount]::new($id)).Translate([Security.Principal.SecurityIdentifier])
}
function Wait-HelperIdle($drain,$deadline) {
    [void]$drain.Set()
    do {
        if (@(Get-HelperProcesses).Count -eq 0 -and (Get-HelperTask).State -ne 'Running') { return $true }
        if ((Get-UpdateNow) -ge $deadline) { return $false }
        Wait-UpdateTick
    } while ($true)
}
function Wait-HelperReady($status,$ready,$deadline) {
    do {
        if ($ready.WaitOne(0) -and (Test-HelperReady $status)) { return $true }
        if ((Get-UpdateNow) -ge $deadline) { return $false }
        Wait-UpdateTick
    } while ($true)
}
function Start-OriginalHelper { Start-ScheduledTask -TaskName $script:HelperTask -TaskPath $script:TaskFolder }
function Disable-OriginalHelper { Disable-ScheduledTask -TaskName $script:HelperTask -TaskPath $script:TaskFolder | Out-Null }
function Enable-OriginalHelper { Enable-ScheduledTask -TaskName $script:HelperTask -TaskPath $script:TaskFolder | Out-Null }
function Restore-Previous($journal) {
    if (-not (Test-Path -LiteralPath $script:Backup)) { throw 'rollback_backup_missing' }
    if ((Get-UpdateDigest $script:Backup) -ne $journal.old.sha256) { throw 'rollback_digest_mismatch' }
    Set-UpdateAcl $script:Exe $journal.acl
    Replace-WithoutBackup $script:Backup $script:Exe
    if (-not (Test-UpdateAcl $script:Exe $journal.acl)) { throw 'rollback_acl_changed' }
    Set-Result $journal.old 'rollback'
    Remove-Item -LiteralPath $script:Journal -Force
}
function Complete-PendingUpdate($journal,$drain,$ready) {
    if (Wait-HelperReady $journal.next $ready ((Get-UpdateNow).AddMinutes(2))) {
        Set-Result $journal.next 'success'
        Remove-Item -LiteralPath $script:Journal -Force
        Remove-Item -LiteralPath $script:Backup -Force
        return
    }
    Disable-OriginalHelper
    try {
        if (-not (Wait-HelperIdle $drain ((Get-UpdateNow).AddMinutes(2)))) {
            # With the drain asserted a compatible helper cannot start new
            # requests. If it never announced ready, it may be stuck at boot.
            if (-not $ready.WaitOne(0) -and -not (Test-HelperPipe $journal.next)) {
                Stop-ScheduledTask -TaskName $script:HelperTask -TaskPath $script:TaskFolder
                if (-not (Wait-HelperIdle $drain ((Get-UpdateNow).AddSeconds(30)))) { throw 'rollback_waiting' }
            } else { throw 'rollback_waiting' }
        }
        Restore-Previous $journal
    } finally {
        [void]$drain.Reset()
        Enable-OriginalHelper
        if ((Get-HelperTask).State -ne 'Running') { Start-OriginalHelper }
    }
}
function Read-UpdatePreference($sid) {
    # The user can select only a boolean and a version label. This does not
    # authorize any path, command, URL or task argument. Cache only the boolean
    # in the SYSTEM-owned directory, so logoff does not reset an opt-out.
    $file = Join-Path $script:Root 'policy.json'
    $auto = $true
    if (Test-Path -LiteralPath $file) {
        Assert-Locked $file -Private
        $saved = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
        if ($saved.auto -is [bool]) { $auto = $saved.auto }
    }
    $manual = $null
    $key = 'Registry::HKEY_USERS\' + $sid.Value + '\Software\PADIEM\PCConnect'
    $choice = $null
    try { $choice = Get-ItemProperty -LiteralPath $key -ErrorAction Stop } catch { }
    if ($choice -and $choice.AutoUpdate -is [int] -and $choice.AutoUpdate -in @(0,1)) {
        $auto = $choice.AutoUpdate -eq 1
        $exists = Test-Path -LiteralPath $file
        Write-AtomicJson $file ([PSCustomObject]@{auto=$auto})
        if (-not $exists) { Set-UpdateAcl $file 'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)' }
        Assert-Locked $file -Private
    }
    if ($choice -and (Get-VersionParts $choice.ManualVersion)) { $manual = [string]$choice.ManualVersion }
    [PSCustomObject]@{auto=$auto;manual=$manual}
}
function Update-Permitted($choice,$version) { return ($choice.auto -eq $true -or $choice.manual -ceq $version) }
function Get-UpdateTaskSddl($sid) {
    # Only the actual helper's console account may read/run the fixed task.
    # No task write, delete, DACL or owner rights; SYSTEM/admin retain full access.
    return ('D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FRFX;;;' + $sid.Value + ')')
}
function Grant-UpdateTaskRun($sid) {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder($script:TaskFolder.TrimEnd('\'))
    $task = $folder.GetTask($script:UpdateTask)
    $sddl = Get-UpdateTaskSddl $sid
    $task.SetSecurityDescriptor($sddl, 16)
    $wanted = [Security.AccessControl.RawSecurityDescriptor]::new($sddl)
    $actual = [Security.AccessControl.RawSecurityDescriptor]::new($task.GetSecurityDescriptor(4))
    $w = @($wanted.DiscretionaryAcl | ForEach-Object { $_.SecurityIdentifier.Value + ':' + $_.AccessMask + ':' + $_.AceType + ':' + $_.AceFlags } | Sort-Object)
    $a = @($actual.DiscretionaryAcl | ForEach-Object { $_.SecurityIdentifier.Value + ':' + $_.AccessMask + ':' + $_.AceType + ':' + $_.AceFlags } | Sort-Object)
    if (($w -join ',') -ne ($a -join ',') -or -not ($actual.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)) { throw 'task_registration_failed' }
}
function Invoke-HelperUpdate {
    $task = Get-HelperTask
    $status = Read-UpdateStatus -Recover:(Test-Path -LiteralPath $script:Journal)
    $sid = Get-TaskSid $task
    $drain = New-UpdateEvent $script:DrainName $sid
    $ready = $null
    try {
        $ready = New-UpdateEvent $script:ReadyName $sid -SignalByUser
        if (Test-Path -LiteralPath $script:Journal) {
            $j = Get-Content -LiteralPath $script:Journal -Raw | ConvertFrom-Json
            $actual = Get-UpdateDigest $script:Exe
            if ($actual -eq $j.old.sha256 -and -not (Test-Path -LiteralPath $script:Backup)) {
                # The old bytes survived or a rollback finished before its receipt.
                if ($status.sha256 -ne $j.old.sha256) { Set-Result $j.old 'rollback' }
                Remove-Item -LiteralPath $script:Journal -Force
                Enable-OriginalHelper
                if ((Get-CimInstance Win32_ComputerSystem).UserName) { Start-OriginalHelper }
                return
            }
            if ($actual -ne $j.next.sha256 -or -not (Test-UpdateAcl $script:Exe $j.acl)) {
                throw 'unverified_transaction'
            }
            Set-Result $j.next 'pending'
            Enable-OriginalHelper
            if ((Get-CimInstance Win32_ComputerSystem).UserName) {
                if ((Get-HelperTask).State -ne 'Running') { Start-OriginalHelper }
                Complete-PendingUpdate $j $drain $ready
            }
            return
        }
        try { $m = Get-Manifest $status.device_id } catch { Set-Result $status 'manifest_rejected'; return }
        $choice = Read-UpdatePreference $sid
        $status | Add-Member -NotePropertyName auto_update -NotePropertyValue $choice.auto -Force
        if ($status.sha256 -eq $m.sha256) {
            if ($status.version -ne $m.version) { $status | Add-Member -NotePropertyName version -NotePropertyValue $m.version -Force }
            $status.PSObject.Properties.Remove('update_available_version')
            # Retain a failed candidate receipt while that release is held or paused.
            $result = if ($status.update_target_sha256 -ne $m.sha256 -and
                $status.update_result -in @('hash_mismatch','signature_mismatch','download_failed','rollback')) { $status.update_result } else { 'current' }
            Set-Result $status $result
            return
        }
        # Existing installs acquire a release label when their exact digest
        # matches the manifest. Never infer an upgrade from an unknown digest.
        if (-not $status.version) { Set-Result $status 'deferred'; return }
        if ((Compare-Version $m.version $status.version) -le 0) {
            if ($status.PSObject.Properties['update_available_version']) {
                $status.PSObject.Properties.Remove('update_available_version')
                Set-Result $status 'current'
            }
            return
        }
        if ((Compare-Version $m.version $m.min_supported_version) -lt 0) { Set-Result $status 'manifest_rejected'; return }
        if (-not (Update-Permitted $choice $m.version)) {
            $status | Add-Member -NotePropertyName update_available_version -NotePropertyValue $m.version -Force
            Set-Result $status 'available'
            return
        }
        $status.PSObject.Properties.Remove('update_available_version')
        if ($status.update_target_sha256 -eq $m.sha256 -and $status.update_result -in @('hash_mismatch','signature_mismatch','rollback')) { return }
        $status | Add-Member -NotePropertyName update_target_sha256 -NotePropertyValue $m.sha256 -Force
        try {
            try { Receive-UpdateFile $m.download_url 'downloads.padiem.net' $script:Candidate 268435456 }
            catch { Set-Result $status 'download_failed'; return }
            if ((Get-UpdateDigest $script:Candidate) -ne $m.sha256) { Set-Result $status 'hash_mismatch'; return }
            # When the current helper has a valid signer, the candidate must
            # also be valid and carry exactly the same certificate.
            $oldSignature = Get-AuthenticodeSignature -LiteralPath $script:Exe
            $newSignature = Get-AuthenticodeSignature -LiteralPath $script:Candidate
            if ($oldSignature.Status -ne 'NotSigned' -and
                ($oldSignature.Status -ne 'Valid' -or $newSignature.Status -ne 'Valid' -or
                 $oldSignature.SignerCertificate.Thumbprint -ne $newSignature.SignerCertificate.Thumbprint)) {
                Set-Result $status 'signature_mismatch'; return
            }
            # Old binaries do not understand the event. Wait for logoff/boot
            # rather than forcing termination. An idle PC may stage an update
            # offline; the logon trigger verifies the pending transaction.
            $waitMinutes = if ((Compare-Version $status.version $m.min_supported_version) -lt 0) { 345 } else { 10 }
            if (-not (Wait-HelperIdle $drain ((Get-UpdateNow).AddMinutes($waitMinutes)))) { Set-Result $status 'deferred'; return }
            # A pause or changed cohort while waiting for idle must prevent
            # a previously downloaded candidate from being installed.
            try { $fresh = Get-Manifest $status.device_id } catch { Set-Result $status 'deferred'; return }
            if ($fresh.sha256 -ne $m.sha256 -or $fresh.version -ne $m.version) {
                $status.PSObject.Properties.Remove('update_available_version')
                Set-Result $status 'deferred'
                return
            }
            Disable-OriginalHelper
            try {
                if (@(Get-HelperProcesses).Count -ne 0) { Set-Result $status 'deferred'; return }
                $choice = Read-UpdatePreference $sid
                $status | Add-Member -NotePropertyName auto_update -NotePropertyValue $choice.auto -Force
                if (-not (Update-Permitted $choice $m.version)) {
                    $status | Add-Member -NotePropertyName update_available_version -NotePropertyValue $m.version -Force
                    Set-Result $status 'available'
                    return
                }
                $acl = Get-UpdateAcl $script:Exe
                $next = $status | ConvertTo-Json -Depth 8 | ConvertFrom-Json
                $next.sha256 = $m.sha256
                $next | Add-Member -NotePropertyName version -NotePropertyValue $m.version -Force
                $journal = [PSCustomObject]@{old=$status;next=$next;acl=$acl}
                Write-AtomicJson $script:Journal $journal
                Set-UpdateAcl $script:Candidate $acl
                # #8359 후속3: .NET Replace 대신 같은 폴더 임시 파일 + Move-Item.
                 # 롤백용 이전 실행 파일은 임시 파일을 복사해 먼저 보존한다.
                 if ((Get-UpdateDigest $script:Candidate) -ne $m.sha256) { throw 'candidate_digest_mismatch' }
                 if (Test-Path -LiteralPath $script:Backup) { throw 'unexpected_backup' }
                 Copy-Item -LiteralPath $script:Exe -Destination $script:Backup -Force
                 Set-UpdateAcl $script:Backup $acl
                 if ((Get-UpdateDigest $script:Backup) -ne (Get-UpdateDigest $script:Exe)) { throw 'backup_copy_mismatch' }
                 Move-Atomic $script:Candidate $script:Exe $m.sha256
                if (-not (Test-UpdateAcl $script:Exe $acl) -or (Get-UpdateDigest $script:Exe) -ne $m.sha256) {
                    Restore-Previous $journal
                    throw 'replacement_unverified'
                }
                Set-Result $next 'pending'
                [void]$drain.Reset()
                Enable-OriginalHelper
                if ((Get-CimInstance Win32_ComputerSystem).UserName) {
                    Start-OriginalHelper
                    Complete-PendingUpdate $journal $drain $ready
                }
            } finally {
                [void]$drain.Reset()
                Enable-OriginalHelper
                if ((Get-HelperTask).State -ne 'Running' -and (Get-CimInstance Win32_ComputerSystem).UserName) { Start-OriginalHelper }
            }
        } finally {
            if (Test-Path -LiteralPath $script:Candidate) { Remove-Item -LiteralPath $script:Candidate -Force }
        }
    } finally {
        $drain.Dispose()
        if ($ready) { $ready.Dispose() }
    }
}

function Register-HelperUpdater($text) {
    $existing = Get-ScheduledTask -TaskPath $script:TaskFolder -TaskName $script:UpdateTask -ErrorAction SilentlyContinue
    if ($existing -and $existing.State -eq 'Running') { throw 'updater_running' }
    [void](Get-HelperTask); [void](Read-UpdateStatus)
    New-PrivateRoot
    if (-not $text) { throw 'missing_fixed_source' }
    if (Test-Path -LiteralPath $script:ScriptFile) { Assert-Locked $script:ScriptFile -Private }
    $tmp = Join-Path $script:Root 'update.new'
    [IO.File]::WriteAllText($tmp,$text,[Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $script:ScriptFile) { Replace-WithoutBackup $tmp $script:ScriptFile }
    else { [IO.File]::Move($tmp,$script:ScriptFile) }
    # Inherited private DACL is already effective; no user may write the script.
    $acl = Get-Acl -LiteralPath $script:ScriptFile
    $acl.SetAccessRuleProtection($true,$true)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    Set-Acl -LiteralPath $script:ScriptFile -AclObject $acl
    Assert-Locked $script:ScriptFile -Private
    $ps = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell\v1.0\powershell.exe'
    $action = New-ScheduledTaskAction -Execute $ps -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $script:ScriptFile + '"')
    $boot = New-ScheduledTaskTrigger -AtStartup
    $login = New-ScheduledTaskTrigger -AtLogOn
    $interval = New-ScheduledTaskTrigger -Once -At (Get-UpdateNow).ToLocalTime().AddMinutes(1) -RepetitionInterval ([TimeSpan]::FromHours(6))
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::FromHours(6))
    Register-ScheduledTask -TaskPath $script:TaskFolder -TaskName $script:UpdateTask -Action $action -Trigger @($boot,$login,$interval) -Principal $principal -Settings $settings -Force | Out-Null
    Grant-UpdateTaskRun (Get-TaskSid (Get-HelperTask))
}
function Unregister-HelperUpdater {
    if (Test-Path -LiteralPath $script:Root) {
        Assert-Locked $script:Root -Private
        if (Test-Path -LiteralPath $script:Journal) { throw 'pending_rollback' }
    }
    $task = Get-ScheduledTask -TaskPath $script:TaskFolder -TaskName $script:UpdateTask -ErrorAction SilentlyContinue
    if ($task -and $task.State -eq 'Running') { throw 'updater_running' }
    if ($task) { Unregister-ScheduledTask -TaskPath $script:TaskFolder -TaskName $script:UpdateTask -Confirm:$false }
    if (Test-Path -LiteralPath $script:ScriptFile) { Assert-Locked $script:ScriptFile -Private; Remove-Item -LiteralPath $script:ScriptFile -Force }
    foreach ($name in @('manifest-cache.json','manifest.json','candidate.exe','previous.exe','policy.json')) {
        $file = Join-Path $script:Root $name
        if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    }
}
if (-not $LibraryOnly) {
    if ($Register) { Register-HelperUpdater $SourceText }
    elseif ($Unregister) { Unregister-HelperUpdater }
    else { Assert-Locked $script:Root -Private; Invoke-HelperUpdate }
}
'''


def helper_update_script() -> str:
    return _UPDATE_SCRIPT


def render_helper_updater_command(*, unregister: bool = False) -> str:
    """A fixed, offline PowerShell payload; never accepts a remote script or path."""
    payload = base64.b64encode(gzip.compress(_UPDATE_SCRIPT.encode("utf-8"), mtime=0)).decode("ascii")
    action = "-Unregister" if unregister else "-Register -SourceText $source"
    return (
        "$b=[Convert]::FromBase64String('" + payload + "');"
        "$ms=[IO.MemoryStream]::new($b);"
        "$gz=[IO.Compression.GZipStream]::new($ms,[IO.Compression.CompressionMode]::Decompress);"
        "$reader=[IO.StreamReader]::new($gz);$source=$reader.ReadToEnd();$reader.Dispose();"
        "& ([scriptblock]::Create($source)) " + action
    )


def render_helper_updater_installer_block() -> str:
    return "function Register-PadiemHelperUpdater {\n  " + render_helper_updater_command() + "\n}\n"


def mesh_helper_updater_command(*, unregister: bool = False) -> str:
    command = render_helper_updater_command(unregister=unregister)
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    return "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded
