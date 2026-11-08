# PADIEM user-session helper - one-command release (#7117 PR-4).
#
# Builds the no-Python helper EXE, uploads it to the dedicated public R2
# bucket at an immutable versioned key, verifies the served bytes, then writes
# the URL and SHA-256 into the COM2 Chat host's EnvironmentFile, restarts the
# service, and verifies the running process picked both values up. COM2 is the
# operating pairing authority while chat.padiem.net is served by
# padiem-chat-front; the Python Worker fallback is deliberately not touched.
#
# The R2 bucket and its custom domain are one-time infrastructure. See
# docs/operations/PC_USER_HELPER_RELEASE_20261107.md for the exact prerequisite,
# the owner-session pairing check and the rollback procedure.
[CmdletBinding()]
param(
    [string]$Python = (Get-Command python -ErrorAction SilentlyContinue).Source,
    [string]$OutRoot = "",
    [string]$Bucket = "padiem-pc-helper-releases",
    [string]$PublicBaseUrl = "https://downloads.padiem.net",
    [string]$KeyPrefix = "pc-helper",
    [string]$ArtifactPath = "",
    [string]$Version = "",
    [string]$SshKey = "C:\Users\limone\.ssh\id_rsa",
    [string]$SshTarget = "user@192.168.0.101",
    [string]$WslDistro = "Ubuntu",
    [string]$RemoteWindowsHome = "C:/Users/user",
    [string]$Com2EnvFile = "/opt/padiem/chat-com2/.env",
    [string]$Com2Service = "padiem-chat-com2.service",
    [string]$Com2HealthUrl = "http://127.0.0.1:8798/health",
    [string]$CloudflareAccountId = "9be14bb7b8974e65d0afba647ab16932",
    [string]$SourceSha = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $Here "..\..")).Path
$Builder = Join-Path $Here "build-windows-helper.ps1"

# A snapshot extracted with `git archive` has no .git, so the default discovery
# below finds nothing. The release evidence still needs the source revision:
# accept it explicitly and keep the builder/git lookups as fallbacks.
if ($SourceSha) {
    if ($SourceSha -notmatch '^[0-9a-fA-F]{40}$') {
        throw "-SourceSha must be an exact 40-hex commit SHA: $SourceSha"
    }
    $SourceSha = $SourceSha.ToLowerInvariant()
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash($stream)
        return (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
}

function ConvertTo-WslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)
    $normalized = $WindowsPath.Replace('\', '/')
    if ($normalized -notmatch '^([A-Za-z]):/(.*)$') {
        throw "RemoteWindowsHome must be a drive-qualified path: $WindowsPath"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $tail = $Matches[2].TrimStart('/')
    return "/mnt/$drive/$tail"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$What
    )
    & $FilePath @Arguments
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "$What failed (exit $code)" }
}

if (-not $ArtifactPath) {
    $builderAvailable = Test-Path -LiteralPath $Builder -PathType Leaf
    if (-not $builderAvailable -and -not $DryRun) {
        # A real run needs the builder (or an explicit -ArtifactPath): this
        # work folder sits on another branch without apps/claw-connect.
        throw "helper builder is missing: $Builder (run from a checkout that has apps/claw-connect, or pass -ArtifactPath + -Version)"
    }
    if ($builderAvailable) {
        $builderArgs = @{}
        if ($Python) { $builderArgs.Python = $Python }
        if ($OutRoot) { $builderArgs.OutRoot = $OutRoot }
        $buildLines = @(& $Builder @builderArgs)
        if ($buildLines.Count -eq 0) { throw "helper builder produced no receipt" }
        $build = [string]$buildLines[$buildLines.Count - 1] | ConvertFrom-Json
        if (-not $build.ok) { throw "helper builder did not report ok" }
        $Exe = [string]$build.exe
        $Version = [string]$build.version
        if (-not $SourceSha) { $SourceSha = [string]$build.source_sha }
    }
    else {
        # DryRun in a foreign work folder: print the topology plan without
        # building. The release-time values are filled in by the builder at
        # the real run.
        if (-not $Version) { $Version = "0.3.0-rc1-dryrun" }
        $Exe = ""
        if (-not $SourceSha) { $SourceSha = "<pinned-release-sha>" }
        Write-Output "PLAN_BUILD=SKIPPED_BUILDER_ABSENT_IN_THIS_WORK_FOLDER (run build-windows-helper.ps1 from a branch checkout, or pass -ArtifactPath + -Version)"
    }
} else {
    if (-not $Version) { throw "-Version is required with -ArtifactPath" }
    $Exe = (Resolve-Path -LiteralPath $ArtifactPath).Path
    if (-not $SourceSha) {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($git) {
            # Under $ErrorActionPreference = "Stop", Windows PowerShell 5.1
            # turns a native stderr line through 2>$null into a terminating
            # NativeCommandError. A git-archive folder must reach the UNKNOWN
            # fallback, not die on the probe.
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            try {
                $SourceSha = ([string](& $git.Source -C $RepoRoot rev-parse HEAD 2>$null)).Trim()
            }
            catch {
                $SourceSha = ""
            }
            finally {
                $ErrorActionPreference = $previousPreference
            }
        }
    }
}
if (-not $SourceSha) { $SourceSha = "UNKNOWN" }

if ($Exe -and -not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "helper EXE is missing: $Exe" }
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$') {
    throw "helper version is not a safe path segment: $Version"
}
if ($PublicBaseUrl -notmatch '^https://[^/]+') {
    throw "PublicBaseUrl must be an https origin: $PublicBaseUrl"
}
if ($Com2EnvFile -notmatch '^/[^ ]+$') { throw "Com2EnvFile must be an absolute path" }
if ($Com2Service -notmatch '^[A-Za-z0-9_.@-]+$') { throw "Com2Service is not a safe unit name" }
if ($Com2HealthUrl -notmatch '^http://(127\.0\.0\.1|localhost):[0-9]+/health$') {
    throw "Com2HealthUrl must be a loopback /health URL"
}
if ($SshTarget -notmatch '^[^@\s]+@[^@\s]+$') { throw "SshTarget must be user@host" }
if ($WslDistro -notmatch '^[A-Za-z0-9._-]+$') { throw "WslDistro is not a safe distro name" }
if ($RemoteWindowsHome -match '\s') { throw "RemoteWindowsHome must not contain spaces" }

if ($Exe) {
    $File = Get-Item -LiteralPath $Exe
    $Sha = Get-Sha256Hex -Path $Exe
    $Bytes = [int64]$File.Length
}
else {
    # DryRun without a built artifact: the builder computes these at the real
    # run; the plan prints the topology with placeholders.
    $Sha = "<sha256-computed-at-release>"
    $Bytes = 0
}
$Key = ($KeyPrefix.Trim('/') + '/' + $Version + '/padiem-user-helper.exe')
$Url = $PublicBaseUrl.TrimEnd('/') + '/' + $Key
$ShaKey = $Key + '.sha256'
$ShaUrl = $PublicBaseUrl.TrimEnd('/') + '/' + $ShaKey

Write-Output "HELPER_RELEASE_VERSION=$Version"
Write-Output "HELPER_RELEASE_SOURCE_SHA=$SourceSha"
Write-Output "HELPER_RELEASE_BYTES=$Bytes"
Write-Output "HELPER_RELEASE_SHA256=$Sha"
Write-Output "HELPER_RELEASE_KEY=$Key"
Write-Output "HELPER_RELEASE_URL=$Url"
Write-Output "HELPER_RELEASE_SHA256_URL=$ShaUrl"
Write-Output "PC_USER_HELPER_INSTALL_URL=$Url"
Write-Output "PC_USER_HELPER_SHA256=$Sha"
Write-Output "HELPER_RELEASE_VAR_TARGET=COM2 $Com2EnvFile (EnvironmentFile of $Com2Service)"

$remoteScriptText = @'
#!/usr/bin/env bash
set -euo pipefail
umask 077
trap 'rm -f -- "$0"' EXIT

env_file="${1:?env file required}"
service="${2:?service required}"
health_url="${3:?health url required}"
helper_url="${4:?helper url required}"
helper_sha="${5:?helper sha required}"

fail() { echo "COM2_ENV_UPDATE=$1" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
[[ -f "$env_file" ]] || fail ENV_MISSING
[[ "$helper_url" =~ ^https://[^/[:space:]]+/pc-helper/[A-Za-z0-9._-]+/padiem-user-helper\.exe$ ]] || fail URL_INVALID
[[ "$helper_sha" =~ ^[0-9a-f]{64}$ ]] || fail SHA_INVALID
[[ "$health_url" =~ ^http://(127\.0\.0\.1|localhost):[0-9]+/health$ ]] || fail HEALTH_URL_INVALID
actual_mode="$(stat -c '%a' "$env_file")"
actual_owner="$(stat -c '%u:%g' "$env_file")"
[[ "$actual_owner" == "0:0" && "$actual_mode" == "600" ]] || fail ENV_PERMISSIONS_UNEXPECTED

backup="${env_file}.bak-$(date -u +%Y%m%dT%H%M%SZ)-$$"
cp -a -- "$env_file" "$backup"
chmod 0600 "$backup"
chown 0:0 "$backup"
cmp -s -- "$env_file" "$backup" || fail BACKUP_MISMATCH
echo "COM2_ENV_BACKUP=$backup"

python3 - "$env_file" "$helper_url" "$helper_sha" <<'PY'
import os
import sys
import tempfile

path, url, sha = sys.argv[1:4]
keys = {"PC_USER_HELPER_INSTALL_URL": url, "PC_USER_HELPER_SHA256": sha}
with open(path, "r", encoding="utf-8") as handle:
    original = handle.readlines()
updated = []
seen = set()
for line in original:
    stripped = line.strip()
    candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
    name = candidate.split("=", 1)[0].strip() if "=" in candidate else ""
    if name in keys:
        if name in seen:
            continue
        updated.append(f"{name}={keys[name]}\n")
        seen.add(name)
        continue
    updated.append(line)
if updated and not updated[-1].endswith("\n"):
    updated[-1] += "\n"
for name, value in keys.items():
    if name not in seen:
        updated.append(f"{name}={value}\n")
fd, temporary = tempfile.mkstemp(prefix=".env.padiem-helper-", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(updated)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.chown(temporary, 0, 0)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

[[ "$(stat -c '%a' "$env_file")" == "600" && "$(stat -c '%u:%g' "$env_file")" == "0:0" ]] || fail ENV_PERMISSIONS_AFTER_REPLACE
python3 - "$env_file" "$helper_url" "$helper_sha" <<'PY'
import sys

path, url, sha = sys.argv[1:4]
values = []
with open(path, "r", encoding="utf-8") as handle:
    for line in handle:
        stripped = line.strip()
        candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        if "=" not in candidate:
            continue
        name, value = candidate.split("=", 1)
        if name.strip() in {"PC_USER_HELPER_INSTALL_URL", "PC_USER_HELPER_SHA256"}:
            values.append((name.strip(), value.strip()))
expected = [("PC_USER_HELPER_INSTALL_URL", url), ("PC_USER_HELPER_SHA256", sha)]
if sorted(values) != sorted(expected):
    raise SystemExit("COM2_ENV_VERIFY=FAIL")
print("COM2_ENV_VALUES=PASS")
PY

systemctl restart "$service"
for _ in $(seq 1 30); do
    if systemctl is-active --quiet "$service"; then break; fi
    sleep 1
done
if ! systemctl is-active --quiet "$service"; then
    systemctl status "$service" --no-pager >&2 || true
    journalctl -u "$service" -n 60 --no-pager >&2 || true
    fail SERVICE_NOT_ACTIVE
fi
echo "COM2_SERVICE_ACTIVE=PASS"

command -v curl >/dev/null 2>&1 || fail CURL_MISSING
# The same readiness ladder as wait_for_health in
# deploy/host-com2/deploy_from_main.sh: a service that has not finished binding
# its loopback port is not an unhealthy release. 2026-11-08 real run: the first
# probe a few seconds after the restart printed CHAT_COM2_HEALTH=FAIL STATUS=0
# while the service was healthy moments later. So the probe now runs
# immediately, retries every 2 s for up to 60 s, and prints its attempt count
# instead of reading one early miss as a failed release.
health_interval=2
health_timeout=60
health_attempt=0
health_deadline=$((SECONDS + health_timeout))
while :; do
    health_attempt=$((health_attempt + 1))
    if health_output="$(runuser -u padiem-chat -- /opt/padiem/chat-com2/venv/bin/python /opt/padiem/chat-com2/health.py --url "$health_url" 2>&1)"; then
        break
    fi
    health_remaining=$((health_deadline - SECONDS))
    (( health_remaining > 0 )) || {
        printf '%s\n' "$health_output" >&2
        echo "COM2_HEALTH_ATTEMPTS=$health_attempt" >&2
        fail HEALTH_FAILED
    }
    health_pause=$health_interval
    (( health_pause > health_remaining )) && health_pause=$health_remaining
    sleep "$health_pause"
done
echo "COM2_HEALTH_ATTEMPTS=$health_attempt"
printf '%s\n' "$health_output"
echo "COM2_HEALTH=PASS"

main_pid="$(systemctl show -p MainPID --value "$service")"
[[ "$main_pid" =~ ^[1-9][0-9]*$ ]] || fail MAINPID_INVALID
process_env="$(tr '\0' '\n' < "/proc/$main_pid/environ")" || fail PROCESS_ENV_UNREADABLE
read_env() {
    printf '%s\n' "$process_env" | sed -n "s/^$1=//p" | head -n 1
}
process_url="$(read_env PC_USER_HELPER_INSTALL_URL)"
process_sha="$(read_env PC_USER_HELPER_SHA256)"
[[ "$process_url" == "$helper_url" && "$process_sha" == "$helper_sha" ]] || fail PROCESS_ENV_MISMATCH
echo "COM2_PROCESS_ENV=PASS"
echo "PC_USER_HELPER_INSTALL_URL=$process_url"
echo "PC_USER_HELPER_SHA256=$process_sha"

loopback_origin="${health_url%/health}"
pairing_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$loopback_origin/api/pc/pairings/install-file" || true)"
[[ "$pairing_status" == "401" ]] || fail "PAIRING_ROUTE_STATUS_${pairing_status}"
echo "COM2_PAIRING_ROUTE=401_UNAUTHENTICATED"
echo "PAIRING_RESPONSE_VERIFY=REQUIRED_SIGNED_IN_OWNER"
echo "COM2_ENV_UPDATE=PASS"
'@

$remoteScriptText = $remoteScriptText.Replace("`r`n", "`n")

if ($DryRun) {
    $planRunId = "<guid>"
    $planRemoteName = "padiem-helper-release-$planRunId.sh"
    $planRemoteWindowsPath = "$($RemoteWindowsHome.TrimEnd('/'))/$planRemoteName"
    $planRemoteWslPath = ConvertTo-WslPath $planRemoteWindowsPath
    $planWsl = 'wsl.exe -d {0} -u root --exec bash {1} {2} {3} {4} {5} {6}' -f $WslDistro, $planRemoteWslPath, $Com2EnvFile, $Com2Service, $Com2HealthUrl, $Url, $Sha
    $planSsh = 'ssh -i "{0}" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new {1} "{2}"' -f $SshKey, $SshTarget, $planWsl
    if ($ArtifactPath) {
        Write-Output "PLAN_BUILD=SKIPPED_ARTIFACT_PATH"
    } else {
        if ($Exe) {
        Write-Output "PLAN_BUILD=build-windows-helper.ps1 -OutRoot $OutRoot"
    }
    }
    Write-Output "PLAN_CLOUDFLARE_ACCOUNT_ID=$CloudflareAccountId"
    $planExe = if ($Exe) { $Exe } else { "<built-exe>" }
    Write-Output ("PLAN_R2_UPLOAD=wrangler r2 object put `"$Bucket/$Key`" --file `"$planExe`" --content-type application/octet-stream --cache-control `"public, max-age=31536000, immutable`" --remote")
    Write-Output ("PLAN_R2_CHECKSUM=wrangler r2 object put `"$Bucket/$ShaKey`" --file <temporary sha256 file> --content-type text/plain --cache-control `"public, max-age=31536000, immutable`" --remote")
    Write-Output "PLAN_COM2_ENV=backup $Com2EnvFile to $Com2EnvFile.bak-<UTC>; replace PC_USER_HELPER_INSTALL_URL and PC_USER_HELPER_SHA256; chmod 0600 root:root"
    Write-Output "PLAN_COM2_TRANSPORT=scp -i $SshKey ... ${SshTarget}:$planRemoteName; $planSsh"
    Write-Output "PLAN_COM2_RESTART=systemctl restart $Com2Service; wait active; GET $Com2HealthUrl (retry every 2s up to 60s, attempt count printed)"
    Write-Output "PLAN_COM2_ENV_READBACK=/proc/<MainPID>/environ exact URL/SHA"
    Write-Output "PLAN_PAIRING_RESPONSE=POST https://chat.padiem.net/api/pc/pairings/install-file with the owner session; assert PADIEMHELPERURL:$Url and PADIEMHELPERSHA:$Sha"
    Write-Output "PLAN_WORKER_FALLBACK=NOT_UPDATED (padiem-chat-front COM2_CANONICAL=writes makes pairing POST 503, not the Python Worker)"
    Write-Output "PLAN_VERIFY=GET $Url and compare SHA-256 $Sha"
    Write-Output "PRODUCTION_MUTATION=0"
    return
}

# npm's .ps1 shims re-parse their arguments through Invoke-Expression, which
# mangles values that contain spaces or quotes (the R2 cache-control header
# and URLs). Prefer the .cmd shim, which passes arguments verbatim.
$Wrangler = $null
foreach ($wranglerCandidate in @("wrangler.cmd", "wrangler.exe", "wrangler")) {
    $found = Get-Command $wranglerCandidate -ErrorAction SilentlyContinue
    if ($found) { $Wrangler = $found.Source; break }
}
if (-not $Wrangler) { throw "wrangler is not on PATH" }
$Ssh = (Get-Command ssh -ErrorAction SilentlyContinue).Source
if (-not $Ssh) { throw "ssh is not on PATH" }
$Scp = (Get-Command scp -ErrorAction SilentlyContinue).Source
if (-not $Scp) { throw "scp is not on PATH" }
if (-not (Test-Path -LiteralPath $SshKey -PathType Leaf)) { throw "SSH key is missing: $SshKey" }
if ($CloudflareAccountId) { $env:CLOUDFLARE_ACCOUNT_ID = $CloudflareAccountId }

Write-Output "HELPER_RELEASE_PRECHECK=R2_BUCKET"
$bucketList = (& $Wrangler r2 bucket list 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw "wrangler r2 bucket list failed" }
if ($bucketList -notmatch [regex]::Escape($Bucket)) {
    throw "R2 bucket '$Bucket' is absent; create it once (see the release procedure) before uploading"
}

Write-Output "HELPER_RELEASE_UPLOAD=START"
Invoke-Checked -FilePath $Wrangler -Arguments @(
    "r2", "object", "put", "$Bucket/$Key", "--file", $Exe,
    "--content-type", "application/octet-stream",
    "--cache-control", "public, max-age=31536000, immutable",
    "--remote"
) -What "helper object upload"

$shaFile = [System.IO.Path]::GetTempFileName()
try {
    [System.IO.File]::WriteAllText(
        $shaFile,
        "$Sha  padiem-user-helper.exe`n",
        (New-Object System.Text.UTF8Encoding($false))
    )
    Invoke-Checked -FilePath $Wrangler -Arguments @(
        "r2", "object", "put", "$Bucket/$ShaKey", "--file", $shaFile,
        "--content-type", "text/plain; charset=utf-8",
        "--cache-control", "public, max-age=31536000, immutable",
        "--remote"
    ) -What "helper checksum upload"
} finally {
    Remove-Item -LiteralPath $shaFile -Force -ErrorAction SilentlyContinue
}

Write-Output "HELPER_RELEASE_VERIFY=START"
$download = [System.IO.Path]::GetTempFileName()
try {
    $response = Invoke-WebRequest -Uri $Url -OutFile $download -UseBasicParsing
    $servedSha = Get-Sha256Hex -Path $download
    if ($servedSha -ne $Sha) { throw "served helper SHA-256 differs from the built artifact" }
    $servedLength = $null
    if ($response -and $response.Headers) { $servedLength = [string]$response.Headers["Content-Length"] }
    if ($servedLength -and [int64]$servedLength -ne $Bytes) {
        throw "served helper length differs from the built artifact"
    }
} finally {
    Remove-Item -LiteralPath $download -Force -ErrorAction SilentlyContinue
}
Write-Output "HELPER_RELEASE_R2_VERIFIED=PASS"

$remoteScriptName = "padiem-helper-release-$([guid]::NewGuid().ToString('N')).sh"
$remoteWindowsPath = "$($RemoteWindowsHome.TrimEnd('/'))/$remoteScriptName"
$remoteWslPath = ConvertTo-WslPath $remoteWindowsPath
$localRemoteScript = Join-Path ([System.IO.Path]::GetTempPath()) $remoteScriptName

try {
    [System.IO.File]::WriteAllText(
        $localRemoteScript,
        $remoteScriptText,
        (New-Object System.Text.UTF8Encoding($false))
    )
    Invoke-Checked -FilePath $Scp -Arguments @(
        "-i", $SshKey,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        $localRemoteScript,
        "${SshTarget}:$remoteScriptName"
    ) -What "COM2 script upload"

    $remoteCommand = 'wsl.exe -d {0} -u root --exec bash {1} {2} {3} {4} {5} {6}' -f $WslDistro, $remoteWslPath, $Com2EnvFile, $Com2Service, $Com2HealthUrl, $Url, $Sha
    Invoke-Checked -FilePath $Ssh -Arguments @(
        "-i", $SshKey,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        $SshTarget,
        $remoteCommand
    ) -What "COM2 env update"

    Write-Output "HELPER_RELEASE_ENV_SET=PASS"
    Write-Output "HELPER_RELEASE_RESTART=PASS"
    Write-Output "HELPER_RELEASE_HEALTH=PASS"
    Write-Output "HELPER_RELEASE_PAIRING_SOURCE=PASS"
    Write-Output "PAIRING_RESPONSE_VERIFY=REQUIRED_SIGNED_IN_OWNER"
} finally {
    Remove-Item -LiteralPath $localRemoteScript -Force -ErrorAction SilentlyContinue
}
