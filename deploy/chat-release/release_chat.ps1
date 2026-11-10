# release_chat.ps1 — one command releases chat.padiem.net end to end.
#
# Topology reference: docs/operations/CHAT_PADIEM_NET_REQUEST_TOPOLOGY_20261108.md
#   static/screen changes deploy ONLY through this script (the front Worker's
#   [assets] + the pages mirror); COM2's deploy_from_main.sh never ships them.
#
# Steps:
#   1. fresh `git fetch origin` (COM1's origin/main goes stale between releases),
#      then -Sha (or the repo's main ref) resolves and equals main. The COM1
#      work folder may sit on any branch: everything below releases the pinned
#      SHA out of git objects, never out of the work folder. The pinned SHA is
#      then compared against COM2's fetched origin/main before any deploy step.
#   2. COM2 (the dep17.sh shape): ssh uploads a small generated sh, which
#      fetches origin inside the OPS checkout, verifies the SHA exists there,
#      then systemd-run --unit=<ts> --collect --quiet -p
#      "WorkingDirectory=$OPS" /bin/bash -c "bash
#      $OPS/deploy/host-com2/deploy_from_main.sh <sha> --apply
#      --ops-checkout $OPS". Poll the journal for COM2_DEPLOY_SUMMARY and
#      require chat:PASS or chat:SKIP (no chat change) and no :FAIL.
#   3. front Worker (padiem-chat-front): node --test, record the previous
#      Version ID (rollback point), npx wrangler deploy --keep-vars — all
#      from the SHA-extracted folder, never from the work folder. The front
#      has no package.json, so nothing is installed: tests run on node
#      builtins and wrangler comes from the npx cache.
#   4. pages mirror (padiem-chat.pages.dev): node build.mjs + wrangler pages
#      deploy, also from the SHA-extracted folder (same no-install rule).
#   5. verify: /health + /privacy 200 on chat.padiem.net, sha256 of
#      chat-transport.js and index.html equal the -Sha static blobs,
#      workers/domains chat.padiem.net -> padiem-chat-front, and the same
#      checks against padiem-chat.pages.dev.
#   6. any failure after the front deploy rolls the front back to the
#      recorded Version and prints the summary.
#
# Secrets: this script never prints credential values. CLOUDFLARE_API_TOKEN is
# read from the environment for the read-only domains check; wrangler uses its
# own stored login. COM2 access is key-based (BatchMode, no passwords).
#
# Audit log (#7350): the script writes its own release_<n>.log in the user
# profile directory and owns the number — highest existing release_*.log
# number (.dryrun.log and .failed.log included) + 1; an existing file is
# never overwritten. A dry-run writes release_<n>.dryrun.log (shared number
# sequence) and never trips the 10-minute guard — only release_<n>.log and
# release_<n>.failed.log count there, so the standard “dry-run first, then
# the real deploy” flow never needs -Force. -LogPath overrides and is
# refused when the file already exists. A release log written in the last
# 10 minutes stops a real run unless -Force (a dry-run only warns). The
# Cloudflare account is resolved at start, before any wrangler
# deployments-list call.
#
# The first real run belongs to the CTO; -DryRun prints this plan and runs
# only read-only pre-checks.

[CmdletBinding()]
param(
    # The commit to release. Empty defaults to the repo's main ref
    # (origin/main, else main, else HEAD); step 1 enforces the equality.
    [string]$Sha = "",
    # Print the plan and run read-only pre-checks only. Never deploys.
    [switch]$DryRun,
    # Audit log path. Empty: the script picks the user-profile
    # release_<n>.log itself — highest existing release_*.log number
    # (.failed.log included) + 1; an existing file is never overwritten.
    # Given: refused when the file already exists.
    [string]$LogPath = "",
    # Release anyway when a release log was written in the last 10 minutes
    # (another release may be in progress). A dry-run only warns.
    [switch]$Force
)

$ErrorActionPreference = "Stop"
# PowerShell 5.1: make HTTPS negotiate TLS 1.2 (github.com, api.cloudflare.com).
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.ServicePointManager]::Tls12

$Script:Com2SshTarget = "user@192.168.0.101"
$Script:Com2SshKey = "C:\Users\limone\.ssh\id_rsa"
$Script:Com2OpsCheckout = "/opt/padiem/com2-deploy/ops"
$Script:CloudflareAccountId = "9be14bb7b8974e65d0afba647ab16932"
$Script:FrontWorker = "padiem-chat-front"
$Script:PagesProject = "padiem-chat"
$Script:PagesHost = "https://padiem-chat.pages.dev"
$Script:PublicHost = "https://chat.padiem.net"
$Script:PollMaxRounds = 60
$Script:PollSeconds = 15

# Every npx call is npx.cmd on purpose: npm ships an npx.ps1 that runs
# Set-StrictMode and re-parses $MyInvocation.Line, re-evaluating the ORIGINAL
# command text in its own scope — any call argument carrying a
# $Script:-qualified variable dies there with "cannot be retrieved"
# (2026-11-10: the pages step and then the rollback both died that way, and a
# bare "npx" on PATH prefers npx.ps1 in pwsh). Pin the npx.cmd APPLICATION by
# full path on Windows; plain npx stays for the Linux CI runner's pwsh.
$Script:Npx = if ($env:OS -eq "Windows_NT" -or $IsWindows) {
    $npxCmd = Get-Command npx.cmd -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty Source
    if ($npxCmd) { $npxCmd } else { "npx.cmd" }
} else { "npx" }

# The asset stamper (deploy/chat-release/stamp_index_html.mjs) versions the
# deploy COPY of index.html; the repository file is never modified here.
$Script:Stamper = Join-Path $PSScriptRoot "stamp_index_html.mjs"
$Script:RepoRoot = (Resolve-Path (Join-Path (Join-Path $PSScriptRoot "..") "..")).Path

$Script:Summary = New-Object System.Collections.Generic.List[string]

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "STEP $Text"
}

function Write-Info([string]$Text) {
    Write-Host "  $Text"
}

function Add-Summary([string]$Text) {
    $Script:Summary.Add($Text) | Out-Null
}

function Show-Summary {
    Write-Host ""
    Write-Host "RELEASE SUMMARY"
    foreach ($line in $Script:Summary) { Write-Host "  $line" }
}

function Get-FileSha256Hex([string]$Path) {
    # .NET SHA256 on purpose: the built-in hash cmdlet is banned in this lane.
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Invoke-Com2([string]$RemoteCommand) {
    # The SSH session lands in cmd.exe on COM2; every remote command here is a
    # single quote-free line so cmd passes it to wsl untouched.
    & ssh -i $Script:Com2SshKey -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=10 $Script:Com2SshTarget $RemoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "COM2 command failed (exit $LASTEXITCODE): $RemoteCommand"
    }
}

function Get-Com2Journal([string]$UnitName) {
    $out = & ssh -i $Script:Com2SshKey -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=10 $Script:Com2SshTarget "wsl journalctl -u $UnitName -o cat -n 400" 2>$null
    return ($out -join "`n")
}

function Get-Com2OriginMain {
    # Read-only COM2-side freshness probe (the step-2 pin guard): fetch origin
    # in the OPS checkout, then read origin/main. Same cmd.exe->wsl rule as
    # Invoke-Com2 (quote-free lines only). Output is a single 40-char SHA;
    # never secrets (git refs only).
    $fetch = & ssh -i $Script:Com2SshKey -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=30 $Script:Com2SshTarget "wsl git -C $Script:Com2OpsCheckout fetch -q origin" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "COM2 origin fetch failed (exit $LASTEXITCODE)"
    }
    $out = & ssh -i $Script:Com2SshKey -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=10 $Script:Com2SshTarget "wsl git -C $Script:Com2OpsCheckout rev-parse origin/main" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "COM2 origin/main read failed (exit $LASTEXITCODE)"
    }
    return ((($out -join "`n") -replace "`r","") -replace '\s','').Trim()
}

function Get-LiveAssetSha256([string]$Url, [string]$Asset) {
    # Cloudflare Web Analytics (zone setting) injects its beacon <script> into
    # served HTML at the edge, so the live index.html never equals the bytes we
    # uploaded. Strip exactly that injected tag before hashing; every other
    # byte must still match. Non-HTML assets are hashed as served.
    $bytes = Get-HttpBytes $Url
    if ($Asset -like "*.html") {
        $html = (New-Object System.Text.UTF8Encoding $false).GetString($bytes)
        $html = [regex]::Replace($html, '\r?\n?<script[^>]*static\.cloudflareinsights\.com/beacon\.min\.js[^>]*>\s*</script>', '')
        $bytes = (New-Object System.Text.UTF8Encoding $false).GetBytes($html)
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Use-WranglerLoginForReadOnlyApi {
    # The domains check needs a bearer token. When none is in the environment,
    # reuse wrangler's own stored login (the account that just deployed) for
    # this process only. The value is never printed.
    if ($env:CLOUDFLARE_API_TOKEN) { return }
    $cfg = Join-Path $env:USERPROFILE ".wrangler\config\default.toml"
    if (-not (Test-Path -LiteralPath $cfg)) { return }
    foreach ($line in [IO.File]::ReadAllLines($cfg)) {
        if ($line -match '^\s*oauth_token\s*=\s*"([^"]+)"') { $env:CLOUDFLARE_API_TOKEN = $Matches[1]; return }
    }
}

function Get-HttpBytes([string]$Url) {
    # Static hosts answer /index.html with a 308 to "/" and PS 5.1's
    # Invoke-WebRequest does not follow 308, so fetch the root directly.
    if ($Url.EndsWith("/index.html")) { $Url = $Url.Substring(0, $Url.Length - "index.html".Length) }
    $tmp = New-TemporaryFile
    try {
        Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -TimeoutSec 40
        return [System.IO.File]::ReadAllBytes($tmp)
    }
    finally {
        Remove-Item -Force $tmp -ErrorAction SilentlyContinue
    }
}

function Get-HttpStatus([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 40
        return [int]$response.StatusCode
    }
    catch {
        $response = $_.Exception.Response
        if ($null -ne $response) { return [int]$response.StatusCode }
        return 0
    }
}

function Get-FrontVersionIds {
    Push-Location $shaFrontDir
    try {
        # wrangler's text output has no "Version ID:" label and lists the oldest
        # deployment first, so read --json and take the newest deployment's
        # versions (highest traffic share first). Full 36-char UUIDs.
        $out = (& $Script:Npx wrangler deployments list --json 2>$null | Out-String)
        if ($LASTEXITCODE -ne 0) { return @() }
        try { $deps = @($out | ConvertFrom-Json | ForEach-Object { $_ }) } catch { return @() }
        if ($deps.Count -eq 0) { return @() }
        $latest = $deps | Sort-Object { [datetime]$_.created_on } -Descending | Select-Object -First 1
        return @($latest.versions | Sort-Object { [double]$_.percentage } -Descending | ForEach-Object { [string]$_.version_id })
    }
    finally { Pop-Location }
}

function Invoke-FrontRollbackIfNeeded {
    # Step 6: any failure after the front deploy puts the previous Version
    # back; the summary records it. The recorded version can be missing when
    # the failure lands before step 3 stored it — re-read the deployments list
    # once instead of silently skipping the rollback. The version travels in a
    # LOCAL variable: no call argument may carry a $Script:-qualified variable
    # (the npx.ps1 re-parse trap, see $Script:Npx above).
    if (-not $Script:FrontDeployed) { return }
    $rollbackVersion = $Script:PrevFrontVersion
    if (-not $rollbackVersion) {
        $rollbackVersion = @(Get-FrontVersionIds)[0]
    }
    if (-not $rollbackVersion) {
        Write-Info "FRONT_ROLLBACK_SKIPPED: no previous Version ID resolvable"
        Add-Summary "FRONT_ROLLBACK_SKIPPED=no_version_id"
        return
    }
    Write-Info "rolling the front back to $rollbackVersion"
    Push-Location $shaFrontDir
    try { & $Script:Npx wrangler rollback $rollbackVersion } finally { Pop-Location }
    Add-Summary "FRONT_ROLLED_BACK_TO=$rollbackVersion"
}

# -- release audit log: the script owns the number (#7350) -------------------
# The runner used to pick the release_NN.log number by hand and two
# same-numbered writes on 2026-11-10 destroyed existing audit logs.
function Get-ReleaseLogMaxNumber([string]$Dir) {
    # The number sequence is shared by all three log kinds: the next release
    # takes max(existing .log, .dryrun.log, .failed.log) + 1.
    $max = 0
    Get-ChildItem -Path (Join-Path $Dir "release_*.log") -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^release_(\d+)(\.dryrun|\.failed)?\.log$' } |
        ForEach-Object { $n = [int]$Matches[1]; if ($n -gt $max) { $max = $n } }
    return $max
}

function Resolve-ReleaseLogPath([string]$Given, [string]$Dir, [switch]$DryRun) {
    if ($Given) {
        if (Test-Path -LiteralPath $Given) {
            throw "RELEASE_LOG_FAIL: -LogPath '$Given' already exists; a release log is never overwritten (pick another name or omit -LogPath)"
        }
        $parent = Split-Path -Parent $Given
        if (-not (Test-Path -LiteralPath $parent)) {
            throw "RELEASE_LOG_FAIL: -LogPath directory does not exist: $parent"
        }
        return $Given
    }
    # A dry-run transcript carries the .dryrun marker so the 10-minute guard
    # can tell it apart from a real release attempt (see Get-RecentReleaseLogs).
    $suffix = ""
    if ($DryRun) { $suffix = ".dryrun" }
    $n = (Get-ReleaseLogMaxNumber $Dir) + 1
    $candidate = Join-Path $Dir ("release_{0}{1}.log" -f $n, $suffix)
    while (Test-Path -LiteralPath $candidate) {
        $n = $n + 1
        $candidate = Join-Path $Dir ("release_{0}{1}.log" -f $n, $suffix)
    }
    return $candidate
}

function Get-RecentReleaseLogs([string]$Dir) {
    # Only real-run logs (.log) and failed real runs (.failed.log) count:
    # a dry-run writes release_<n>.dryrun.log and must never block the real
    # deploy that immediately follows it (#7350 follow-up — otherwise every
    # lane learns to pass -Force and the guard is disarmed).
    $cutoff = (Get-Date).AddMinutes(-10)
    return @(Get-ChildItem -Path (Join-Path $Dir "release_*.log") -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $cutoff -and $_.Name -match '^release_\d+(\.failed)?\.log$' })
}

$Script:LogDir = $env:USERPROFILE
if (-not $Script:LogDir) { $Script:LogDir = $env:HOME }
if (-not $Script:LogDir) {
    throw "RELEASE_LOG_FAIL: no user profile directory (USERPROFILE/HOME) to hold the release audit log"
}
$recentLogs = Get-RecentReleaseLogs $Script:LogDir
if ($recentLogs.Count -gt 0) {
    $recentNames = ($recentLogs | ForEach-Object { $_.Name }) -join ', '
    if ($DryRun) {
        Write-Info "WARNING: release log(s) written in the last 10 minutes ($recentNames) — another release may be in progress; a real run stops here unless -Force (a dry-run only warns)"
    }
    elseif (-not $Force) {
        throw "RELEASE_LOG_FAIL: release log(s) written in the last 10 minutes ($recentNames) — another release may be in progress. Pass -Force to release anyway."
    }
    else {
        Write-Info "release log(s) written in the last 10 minutes ($recentNames) — continuing on -Force"
    }
}
$Script:ReleaseLogPath = Resolve-ReleaseLogPath $LogPath $Script:LogDir -DryRun:$DryRun
$null = Start-Transcript -Path $Script:ReleaseLogPath
Write-Info "release log = $Script:ReleaseLogPath (the script owns the number; existing files are never overwritten)"

# (가): resolve the Cloudflare account BEFORE any wrangler deployments-list
# call. Get-FrontVersionIds runs in step 3; with more than one account in the
# stored wrangler login a bare call fails there and the release stops without
# a rollback point (release_32, 2026-11-10). The value stays local to this
# process and is never printed.
$env:CLOUDFLARE_ACCOUNT_ID = $Script:CloudflareAccountId

# -- pre-flight freshness (SHA-staleness guard) -----------------------------
# 2026-11-09: release_49 pinned a stale COM1 origin/main (d4c7316) while COM2's
# freshly fetched origin/main had already advanced past it; deploy_from_main
# refused with SHA_NOT_ORIGIN_MAIN deep inside the systemd unit, and the
# release paid its whole 60x15s poll window before failing. Freshness is now
# enforced here, before any unit exists: (a) refresh COM1's own origin/main so
# the pin is taken from fresh refs; (b) compare the pinned SHA against the
# COM2-side origin/main (which the launcher would fetch anyway) and abort in
# seconds with an actionable message if COM2 has already moved past us.
function Fetch-OriginFresh {
    & git -C $RepoRoot fetch -q origin 2>$null
    if ($LASTEXITCODE -ne 0) {
        if ($DryRun) {
            # No deploy risk in dry-run: pin from the refs we have.
            Write-Info "[DRYRUN] git fetch origin failed; pinning from the local refs (the COM2 origin/main check still guards every real run)."
        }
        else {
            throw "STEP1_FAIL: git fetch origin failed; refusing to pin from stale refs. Check network/origin, then rerun."
        }
    }
    else {
        Write-Info "git fetch origin ok (origin/main refreshed)"
    }
}

# ── step 1 ───────────────────────────────────────────────────────────────────
Write-Step "1/6 resolve and pin the release commit"
Fetch-OriginFresh
function Resolve-CommitRef([string]$Ref) {
    # CI checkouts (actions/checkout, depth 1) carry no origin/main ref: fall
    # back main -> HEAD so the dry-run contract runs anywhere.
    foreach ($candidate in @($Ref, "origin/main", "main", "HEAD")) {
        if (-not $candidate) { continue }
        $resolved = & git -C $RepoRoot rev-parse --verify --quiet "$candidate^{commit}" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) { return ("$resolved").Trim() }
    }
    throw "STEP1_FAIL: could not resolve a commit for '$Ref'"
}
$mainCommit = Resolve-CommitRef "origin/main"
$shaCommit = Resolve-CommitRef $Sha
if ($shaCommit -ne $mainCommit) {
    throw "STEP1_FAIL: $Sha ($shaCommit) is not main ($mainCommit). Merge or pass the merged main."
}
Write-Info "release SHA = $shaCommit (== main)"
Add-Summary "SHA=$shaCommit"

if ($DryRun) {
    Write-Info "[DRYRUN] step 1 passed; no deployment will happen below."
}

# ── step 2 ───────────────────────────────────────────────────────────────────
Write-Step "2/6 COM2 deploy (deploy_from_main.sh --apply via systemd-run, dep17.sh shape)"
$unitName = "padiem-chat-release-{0}" -f (Get-Date -Format "yyyyMMddHHmmss")
# The launcher is generated as a literal sh file and uploaded base64-encoded:
# systemd-run needs -p "WorkingDirectory=..." plus a nested /bin/bash -c, and
# PS 5.1 -> ssh -> cmd -> wsl quoting cannot carry that reliably. One small
# file on the COM2 side carries the real quoting instead.
$remoteShTemplate = @'
#!/bin/sh
# Generated by release_chat.ps1 - one-shot COM2 release launcher.
set -eu
OPS=/opt/padiem/com2-deploy/ops
SHA="__SHA__"
UNIT="__UNIT__"
git -C "$OPS" fetch -q origin
git -C "$OPS" cat-file -e "$SHA^{commit}"
systemd-run --unit="$UNIT" --collect --quiet -p "WorkingDirectory=$OPS" \
  /bin/bash -c "bash $OPS/deploy/host-com2/deploy_from_main.sh $SHA --apply --ops-checkout $OPS"
rm -f -- "$0"
'@
$remoteSh = $remoteShTemplate.Replace("__SHA__", $shaCommit).Replace("__UNIT__", $unitName)
# LF only: the template inherits this file's CRLF on Windows checkouts and
# sh would read "set -eu\r". The file goes up with scp (the same path dep17.sh
# uses) because a pipe or ">" inside the ssh command is parsed by cmd.exe on
# COM2, not by wsl. It lands in the COM2 user's home and runs with plain
# "bash <file>", exactly like "ssh ... bash dep17.sh".
$remoteSh = $remoteSh -replace "`r`n", "`n"
$remoteShPath = "padiem-release-$unitName.sh"

if ($DryRun) {
    Write-Info "[DRYRUN] would fetch origin on COM2 and compare COM2-side origin/main with the pinned SHA before launching the unit (aborts if COM2 origin/main has advanced past the pin)"
}
else {
    $com2Main = Get-Com2OriginMain
    Write-Info "COM2 origin/main = $com2Main"
    if ($com2Main -ne $shaCommit) {
        throw "STEP2_FAIL: COM2 origin/main ($com2Main) != pinned release SHA ($shaCommit); the pin is stale or COM2 moved ahead. Rerun release_chat.ps1 to re-fetch and re-pin, or pass -Sha $com2Main"
    }
}

if ($DryRun) {
    Write-Info "[DRYRUN] launcher sh uploaded to $remoteShPath would be:"
    foreach ($line in ($remoteSh -split "`n")) { Write-Info "    | $line" }
    Write-Info "[DRYRUN] would run: scp -i $Script:Com2SshKey -o BatchMode=yes <local LF copy> $($Script:Com2SshTarget):$remoteShPath"
    Write-Info "[DRYRUN] would run: ssh ... `"bash $remoteShPath`""
    Write-Info "[DRYRUN] then poll: wsl journalctl -u $unitName -o cat -n 400 (max $($Script:PollMaxRounds)x$($Script:PollSeconds)s) for COM2_DEPLOY_SUMMARY=... chat:PASS"
}
else {
    $localSh = Join-Path ([IO.Path]::GetTempPath()) $remoteShPath
    [IO.File]::WriteAllText($localSh, $remoteSh, (New-Object Text.UTF8Encoding $false))
    try {
        & scp -i $Script:Com2SshKey -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=10 $localSh "$($Script:Com2SshTarget):$remoteShPath"
        if ($LASTEXITCODE -ne 0) { throw "COM2 launcher upload failed (scp exit $LASTEXITCODE)" }
    }
    finally { Remove-Item -LiteralPath $localSh -Force -ErrorAction SilentlyContinue }
    Invoke-Com2 "bash $remoteShPath"
    Write-Info "systemd unit $unitName started; polling the journal (max $($Script:PollMaxRounds)x$($Script:PollSeconds)s)"
    $summaryLine = $null
    for ($round = 0; $round -lt $Script:PollMaxRounds; $round++) {
        Start-Sleep -Seconds $Script:PollSeconds
        $journal = Get-Com2Journal $unitName
        $match = [regex]::Match($journal, "COM2_DEPLOY_SUMMARY=(.+)")
        if ($match.Success) { $summaryLine = $match.Groups[1].Value.Trim(); break }
    }
    if (-not $summaryLine) {
        try { $tail = Get-Com2Journal $unitName } catch { $tail = "" }
        Write-Host $tail
        throw "STEP2_FAIL: no COM2_DEPLOY_SUMMARY within the polling window"
    }
    Write-Info "COM2_DEPLOY_SUMMARY=$summaryLine"
    Add-Summary "COM2_DEPLOY_SUMMARY=$summaryLine"
    # chat:SKIP is a valid outcome: deploy_from_main.sh skips the chat unit
    # when the release changes no chat-runtime path (e.g. a pages/build-only
    # release). Any :FAIL, or a chat state other than PASS/SKIP, aborts.
    if ($summaryLine -match ":FAIL" -or $summaryLine -notmatch "chat:(PASS|SKIP)") {
        throw "STEP2_FAIL: COM2 deploy did not end chat:PASS/SKIP without FAIL ($summaryLine)"
    }
}

# ── step 3 ───────────────────────────────────────────────────────────────────
Write-Step "3/6 front Worker (padiem-chat-front) test, version pin, deploy"

# Static blobs for the step 5 comparison come from the pinned SHA, not the
# working tree: git archive extracts them read-only. Zip + Expand-Archive on
# purpose — PATH-resolved tar is not the same binary on every machine. The
# extraction also carries apps/padiem-chat-pages so step 4 builds the mirror
# from the pinned SHA, and it keeps the repo-relative layout, which makes the
# front's [assets] path (../padiem-chat/static) resolve inside the extraction.
$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("chat-release-" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmpRoot | Out-Null
$archiveZip = Join-Path $tmpRoot "release.zip"
& git -C $RepoRoot archive --format=zip -o $archiveZip $shaCommit -- apps/padiem-chat-front apps/padiem-chat/static apps/padiem-chat-pages
if ($LASTEXITCODE -ne 0) { throw "STEP3_FAIL: git archive failed" }
Expand-Archive -Path $archiveZip -DestinationPath $tmpRoot -Force
# The extracted pages build (post-merge) imports the stamper from deploy/;
# the archive pins the SHA's app trees, so the running script ships its own
# stamper copy into the extraction (identical bytes on a clean main checkout).
New-Item -ItemType Directory -Path (Join-Path $tmpRoot "deploy/chat-release") -Force | Out-Null
Copy-Item $Script:Stamper (Join-Path $tmpRoot "deploy/chat-release/stamp_index_html.mjs") -Force
$shaFrontDir = Join-Path $tmpRoot "apps/padiem-chat-front"
$shaPagesDir = Join-Path $tmpRoot "apps/padiem-chat-pages"
$shaStaticDir = Join-Path $tmpRoot "apps/padiem-chat/static"
# The front's wrangler.toml points [assets] at ../padiem-chat/static; that
# relative walk must exist inside the extraction or the deploy would ship a
# stale/empty asset set.
if (-not (Test-Path (Join-Path $shaFrontDir "../padiem-chat/static/index.html"))) {
    throw "STEP3_FAIL: [assets] relative path broken inside the extraction ($shaFrontDir)"
}

# Version-stamp a COPY of the pinned static tree: every local script/link
# reference in the HTML entries gains ?v=<8-char sha> and every JS/CSS
# literal that loads another static file carries the same version, so a
# deploy is a fresh cache key for already-open tabs and mobile browsers.
# The repository files stay untouched; the stamped copy ships via the
# wrangler --assets override below and pins the step 5 comparison. The
# stamper (stamp_index_html.mjs) is archived into the extraction too: the
# extracted pages build imports it. Kept in a separate file so this script
# only orchestrates.
$assetVersion = $shaCommit.Substring(0, 8)
$stampStaticDir = Join-Path $tmpRoot "stamped-static"
Copy-Item $shaStaticDir $stampStaticDir -Recurse
& node $Script:Stamper $stampStaticDir $assetVersion
if ($LASTEXITCODE -ne 0) { throw "STEP3_FAIL: index.html asset stamping failed" }
Write-Info "asset version stamp = $assetVersion"
Add-Summary "ASSET_VERSION=$assetVersion"

Push-Location $shaFrontDir
$Script:FrontDeployed = $false
$Script:PrevFrontVersion = $null
$Script:NewFrontVersion = $null
try {
    & node --test test/worker.test.mjs
    if ($LASTEXITCODE -ne 0) { throw "STEP3_FAIL: node --test test/worker.test.mjs failed" }

    $prevIds = @(Get-FrontVersionIds)
    if ($prevIds.Count -eq 0) {
        if ($DryRun) {
            Write-Info "[DRYRUN] current front Version ID unreadable on this machine (wrangler auth needed); a real run aborts here unless it resolves - no rollback point, no deploy."
        }
        else {
            throw "STEP3_FAIL: could not read the current front Version ID; no rollback point, refusing to deploy"
        }
    }
    else {
        $Script:PrevFrontVersion = $prevIds[0]
        Write-Info "previous front Version ID = $($Script:PrevFrontVersion)"
        Add-Summary "FRONT_VERSION_PREV=$($Script:PrevFrontVersion)"
    }

    if ($DryRun) {
        Write-Info "[DRYRUN] would run: npx wrangler deploy --keep-vars --assets $stampStaticDir (account $($Script:CloudflareAccountId))"
    }
    else {
        $env:CLOUDFLARE_ACCOUNT_ID = $Script:CloudflareAccountId
        # The stamped static copy replaces the wrangler.toml [assets] directory
        # for this deploy: the Worker ships the version-stamped index.html.
        & $Script:Npx wrangler deploy --keep-vars --assets $stampStaticDir
        if ($LASTEXITCODE -ne 0) { throw "STEP3_FAIL: wrangler deploy failed" }
        $Script:FrontDeployed = $true
        $newIds = @(Get-FrontVersionIds)
        if ($newIds.Count -gt 0 -and $newIds[0] -ne $Script:PrevFrontVersion) {
            $Script:NewFrontVersion = $newIds[0]
        }
        Write-Info "front deployed; new Version ID = $(if ($Script:NewFrontVersion) { $Script:NewFrontVersion } else { '(unparsed; see deploy output)' })"
        Add-Summary "FRONT_VERSION_NEW=$($Script:NewFrontVersion)"
    }
}
catch {
    Invoke-FrontRollbackIfNeeded
    Pop-Location
    throw
}
Pop-Location

# ── steps 4 and 5 ────────────────────────────────────────────────────────────
# Pages mirror then surface verification. A FRONT failure (chat.padiem.net
# itself) rolls the front back — a half-released screen is worse than the
# previous one. A PAGES-MIRROR-ONLY failure must not touch the front: the
# mirror is a convenience host, so it is recorded as PAGES_VERIFY_FAIL and the
# release exits 1 with the front still serving.
try {
    Write-Step "4/6 pages mirror (padiem-chat.pages.dev)"
    if ($DryRun) {
        Write-Info "[DRYRUN] would run (in $shaPagesDir): node build.mjs ; npx wrangler pages deploy dist --project-name $Script:PagesProject --branch main"
    }
    else {
        Push-Location $shaPagesDir
        try {
            # build.mjs stamps dist/index.html with the same asset version as
            # the Worker copy, so both surfaces answer identical bytes.
            $env:PADIEM_ASSET_VERSION = $assetVersion
            & node build.mjs
            if ($LASTEXITCODE -ne 0) { throw "STEP4_FAIL: pages build failed" }
            & $Script:Npx wrangler pages deploy dist --project-name $Script:PagesProject --branch main
            if ($LASTEXITCODE -ne 0) { throw "STEP4_FAIL: wrangler pages deploy failed" }
        }
        finally { Pop-Location }
    }

    Write-Step "5/6 verify the release surfaces"
    $verify = New-Object System.Collections.Generic.List[string]
    $Script:PagesVerifyFailed = New-Object System.Collections.Generic.List[string]

    # A single-element pair list must be comma-preserved: @(@("a", "b"))
    # FLATTENS in PowerShell and $pair[1] becomes the second CHARACTER of the
    # host ("h"), which the verify then requests as a bogus host (the 4th
    # deploy's STEP5_FAIL). Two-or-more element lists iterate correctly.
    $frontStatusPairs = @(
        @("chat.padiem.net /health", "$Script:PublicHost/health"),
        @("chat.padiem.net /privacy", "$Script:PublicHost/privacy")
    )
    $frontAssetHosts = @(,@("chat.padiem.net", "$Script:PublicHost"))
    $pagesStatusPairs = @(,@("padiem-chat.pages.dev /privacy", "$Script:PagesHost/privacy"))
    $pagesAssetHosts = @(,@("padiem-chat.pages.dev", $Script:PagesHost))

    if ($DryRun) {
        # Expand the URL list without sending anything: this is what the
        # contract test asserts the shape of.
        Write-Info "[DRYRUN] would verify:"
        foreach ($pair in $frontStatusPairs) { Write-Info "  GET $($pair[1]) (expect 200)" }
        foreach ($pair in $frontAssetHosts) {
            foreach ($asset in @("chat-transport.js", "index.html")) {
                Write-Info "  GET $($pair[1])/$asset (expect sha256 == the pinned SHA static)"
            }
        }
        Write-Info "  check: workers/domains chat.padiem.net -> $Script:FrontWorker"
        foreach ($pair in $pagesStatusPairs) { Write-Info "  GET $($pair[1]) (expect 200)" }
        foreach ($pair in $pagesAssetHosts) {
            foreach ($asset in @("chat-transport.js", "index.html")) {
                Write-Info "  GET $($pair[1])/$asset (expect sha256 == the pinned SHA static)"
            }
        }
    }
    else {
        foreach ($pair in $frontStatusPairs) {
            $status = Get-HttpStatus $pair[1]
            $verify.Add("$($pair[0])=$status") | Out-Null
            if ($status -ne 200) { throw "STEP5_FAIL: $($pair[0]) returned $status" }
        }

        foreach ($pair in $frontAssetHosts) {
            foreach ($asset in @("chat-transport.js", "index.html")) {
                $liveHash = Get-LiveAssetSha256 ($pair[1] + "/" + $asset) $asset
                # index.html is compared against the STAMPED copy (the bytes
                # both surfaces must serve); every other asset in the stamped
                # tree is byte-identical to the pinned SHA blob.
                $pinned = Get-FileSha256Hex (Join-Path $stampStaticDir $asset)
                $ok = $liveHash -eq $pinned
                $verify.Add("$($pair[0])/$asset sha256=$(if ($ok) { 'match' } else { 'MISMATCH' })") | Out-Null
                if (-not $ok) {
                    throw "STEP5_FAIL: $($pair[0])/$asset sha256 mismatch (live $liveHash vs sha $pinned)"
                }
            }
        }

        Use-WranglerLoginForReadOnlyApi
        if (-not $env:CLOUDFLARE_API_TOKEN) {
            throw "STEP5_FAIL: CLOUDFLARE_API_TOKEN missing in the environment (read-only domains check; the value is never printed)"
        }
        $domains = Invoke-RestMethod `
            -Uri "https://api.cloudflare.com/client/v4/accounts/$($Script:CloudflareAccountId)/workers/domains?hostname=chat.padiem.net" `
            -Headers @{ Authorization = "Bearer $env:CLOUDFLARE_API_TOKEN" } `
            -TimeoutSec 40
        $entries = @($domains.result | Where-Object { $_.hostname -eq "chat.padiem.net" })
        if ($entries.Count -ne 1 -or $entries[0].service -ne $Script:FrontWorker) {
            throw "STEP5_FAIL: chat.padiem.net custom domain is not on $Script:FrontWorker"
        }
        $verify.Add("workers/domains chat.padiem.net=$($entries[0].service)") | Out-Null

        # PAGES mirror checks: the mirror is a convenience host (the front
        # Worker owns chat.padiem.net), so a mirror-only failure must NOT roll
        # the front back — it is recorded as PAGES_VERIFY_FAIL and fails the
        # release with exit 1 after the summary.
        foreach ($asset in @("chat-transport.js", "index.html")) {
            # The pages build stamps dist with the same ?v=<sha8>, so the
            # mirror must serve the STAMPED bytes too.
            # A mirror fetch error must stay a mirror failure; it must never
            # escape into the catch below that rolls the front back.
            try { $liveHash = Get-LiveAssetSha256 ($Script:PagesHost + "/" + $asset) $asset }
            catch { $liveHash = "fetch_error:" + $_.Exception.GetType().Name }
            $pinned = Get-FileSha256Hex (Join-Path $stampStaticDir $asset)
            $ok = $liveHash -eq $pinned
            $verify.Add("padiem-chat.pages.dev/$asset sha256=$(if ($ok) { 'match' } else { 'MISMATCH' })") | Out-Null
            if (-not $ok) {
                $Script:PagesVerifyFailed.Add("$asset sha256 mismatch") | Out-Null
            }
        }
        try { $pagesPrivacy = Get-HttpStatus ($Script:PagesHost + "/privacy") } catch { $pagesPrivacy = 0 }
        $verify.Add("padiem-chat.pages.dev/privacy=$pagesPrivacy") | Out-Null
        if ($pagesPrivacy -ne 200) {
            $Script:PagesVerifyFailed.Add("/privacy returned $pagesPrivacy") | Out-Null
        }
    }
}
catch {
    # Store the ORIGINAL failure first, then roll back: a rollback failure must
    # never replace the step failure in the log (2026-11-10: the rollback
    # crash hid the STEP4 pages failure completely and the release ended
    # without any failure reason).
    $releaseFailure = $_
    try { Invoke-FrontRollbackIfNeeded }
    catch {
        Write-Host "FRONT_ROLLBACK_FAILED: $($_.Exception.Message)"
        Add-Summary "FRONT_ROLLBACK_FAILED"
    }
    throw $releaseFailure
}

foreach ($line in $verify) { Write-Info $line; Add-Summary "VERIFY $line" }
if ($Script:PagesVerifyFailed.Count -gt 0) {
    foreach ($line in $Script:PagesVerifyFailed) {
        Write-Info "PAGES_VERIFY_FAIL: $line"
        Add-Summary "PAGES_VERIFY_FAIL $line"
    }
}

# ── step 6 ───────────────────────────────────────────────────────────────────
Write-Step "6/6 report"
if ($Script:PagesVerifyFailed.Count -gt 0) {
    Write-Info "the front is intact; the pages mirror regressed — investigate before the next release"
}
Write-Info "release complete; the summary below is the deploy record"
Show-Summary
if ($DryRun) {
    Write-Host "DRYRUN: nothing was deployed."
}
try { Stop-Transcript | Out-Null } catch { }
if ($Script:PagesVerifyFailed.Count -gt 0) { exit 1 }
