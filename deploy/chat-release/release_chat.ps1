# release_chat.ps1 — one command releases chat.padiem.net end to end.
#
# Topology reference: docs/operations/CHAT_PADIEM_NET_REQUEST_TOPOLOGY_20261108.md
#   static/screen changes deploy ONLY through this script (the front Worker's
#   [assets] + the pages mirror); COM2's deploy_from_main.sh never ships them.
#
# Steps:
#   1. origin/main == -Sha (a release is always exactly reviewed main).
#   2. COM2: ssh -> systemd-run deploy_from_main.sh <sha> --apply --ops-checkout
#      /opt/padiem/com2-deploy/ops ; poll the journal for COM2_DEPLOY_SUMMARY
#      and require chat:PASS. Any other summary aborts the release.
#   3. front Worker (padiem-chat-front): node --test, record the previous
#      Version ID (rollback point), npx wrangler deploy --keep-vars.
#   4. pages mirror (padiem-chat.pages.dev): node build.mjs, wrangler pages
#      deploy dist --project-name padiem-chat --branch main.
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
# The first real run belongs to the CTO; -DryRun prints this plan and runs
# only read-only pre-checks.

[CmdletBinding()]
param(
    # The commit to release. Empty defaults to the repo's main ref
    # (origin/main, else main, else HEAD); step 1 enforces the equality.
    [string]$Sha = "",
    # Print the plan and run read-only pre-checks only. Never deploys.
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
# PowerShell 5.1: make HTTPS negotiate TLS 1.2 (github.com, api.cloudflare.com).
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.ServicePointManager]::Tls12

$Script:Com2SshTarget = "user@192.168.0.101"
$Script:Com2SshKey = "C:\Users\limone\.ssh\id_rsa"
$Script:Com2DeployScript = "/mnt/d/work/ai-revenue-lab-ops/deploy/host-com2/deploy_from_main.sh"
$Script:Com2OpsCheckout = "/opt/padiem/com2-deploy/ops"
$Script:CloudflareAccountId = "9be14bb7b8974e65d0afba647ab16932"
$Script:FrontWorker = "padiem-chat-front"
$Script:PagesProject = "padiem-chat"
$Script:PagesHost = "https://padiem-chat.pages.dev"
$Script:PublicHost = "https://chat.padiem.net"
$Script:PollMaxRounds = 60
$Script:PollSeconds = 15

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
    & ssh -i $Script:Com2SshKey -o BatchMode=yes -o ConnectTimeout=10 $Script:Com2SshTarget $RemoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "COM2 command failed (exit $LASTEXITCODE): $RemoteCommand"
    }
}

function Get-Com2Journal([string]$UnitName) {
    $out = & ssh -i $Script:Com2SshKey -o BatchMode=yes -o ConnectTimeout=10 $Script:Com2SshTarget "wsl journalctl -u $UnitName -o cat -n 400" 2>$null
    return ($out -join "`n")
}

function Get-HttpBytes([string]$Url) {
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
    Push-Location (Join-Path $RepoRoot "apps/padiem-chat-front")
    try {
        $out = (& npx wrangler deployments list 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) { return @() }
        return ([regex]::Matches($out, "Version ID:\s*([0-9a-fA-F-]{32})") | ForEach-Object { $_.Groups[1].Value })
    }
    finally { Pop-Location }
}

function Invoke-FrontRollbackIfNeeded {
    # Step 6: any failure after the front deploy puts the previous Version
    # back; the summary records it.
    if ($Script:FrontDeployed -and $Script:PrevFrontVersion) {
        Write-Info "rolling the front back to $($Script:PrevFrontVersion)"
        Push-Location (Join-Path $RepoRoot "apps/padiem-chat-front")
        try { & npx wrangler rollback $Script:PrevFrontVersion } finally { Pop-Location }
        Add-Summary "FRONT_ROLLED_BACK_TO=$($Script:PrevFrontVersion)"
    }
}

# ── step 1 ───────────────────────────────────────────────────────────────────
Write-Step "1/6 resolve and pin the release commit"
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
Write-Step "2/6 COM2 deploy (deploy_from_main.sh --apply via systemd-run)"
$unitName = "padiem-chat-release-{0}" -f (Get-Date -Format "yyyyMMddHHmmss")
$remoteStart = "wsl systemd-run --collect --unit=$unitName bash $Script:Com2DeployScript $shaCommit --apply --ops-checkout $Script:Com2OpsCheckout"

if ($DryRun) {
    Write-Info "[DRYRUN] would run: ssh -i $Script:Com2SshKey -o BatchMode=yes $Script:Com2SshTarget `"$remoteStart`""
    Write-Info "[DRYRUN] then poll: wsl journalctl -u $unitName -o cat -n 400 (max $($Script:PollMaxRounds)x$($Script:PollSeconds)s) for COM2_DEPLOY_SUMMARY=... chat:PASS"
}
else {
    Invoke-Com2 $remoteStart
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
    if ($summaryLine -notmatch "chat:PASS") {
        throw "STEP2_FAIL: COM2 deploy did not end chat:PASS ($summaryLine)"
    }
}

# ── step 3 ───────────────────────────────────────────────────────────────────
Write-Step "3/6 front Worker (padiem-chat-front) test, version pin, deploy"
$frontDir = Join-Path $RepoRoot "apps/padiem-chat-front"
$staticDir = Join-Path $RepoRoot "apps/padiem-chat/static"

# Static blobs for the step 5 comparison come from the pinned SHA, not the
# working tree: git archive extracts them read-only. Zip + Expand-Archive on
# purpose — PATH-resolved tar is not the same binary on every machine.
$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("chat-release-" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmpRoot | Out-Null
$archiveZip = Join-Path $tmpRoot "release.zip"
& git -C $RepoRoot archive --format=zip -o $archiveZip $shaCommit -- apps/padiem-chat-front apps/padiem-chat/static
if ($LASTEXITCODE -ne 0) { throw "STEP3_FAIL: git archive failed" }
Expand-Archive -Path $archiveZip -DestinationPath $tmpRoot -Force
$shaFrontDir = Join-Path $tmpRoot "apps\padiem-chat-front"
$shaStaticDir = Join-Path $tmpRoot "apps/padiem-chat/static"

Push-Location $frontDir
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
        Write-Info "[DRYRUN] would run: npx wrangler deploy --keep-vars (account $($Script:CloudflareAccountId))"
    }
    else {
        $env:CLOUDFLARE_ACCOUNT_ID = $Script:CloudflareAccountId
        & npx wrangler deploy --keep-vars
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
# Pages mirror then surface verification; a failure in either rolls the front
# back (step 6) because a half-released screen is worse than the previous one.
try {
    Write-Step "4/6 pages mirror (padiem-chat.pages.dev)"
    $pagesDir = Join-Path $RepoRoot "apps/padiem-chat-pages"
    if ($DryRun) {
        Write-Info "[DRYRUN] would run: node build.mjs ; npx wrangler pages deploy dist --project-name $Script:PagesProject --branch main"
    }
    else {
        Push-Location $pagesDir
        try {
            & node build.mjs
            if ($LASTEXITCODE -ne 0) { throw "STEP4_FAIL: pages build failed" }
            & npx wrangler pages deploy dist --project-name $Script:PagesProject --branch main
            if ($LASTEXITCODE -ne 0) { throw "STEP4_FAIL: wrangler pages deploy failed" }
        }
        finally { Pop-Location }
    }

    Write-Step "5/6 verify the release surfaces"
    $verify = New-Object System.Collections.Generic.List[string]

    if ($DryRun) {
        Write-Info "[DRYRUN] would verify: $Script:PublicHost/health + /privacy 200; sha256(chat-transport.js, /) == Sha static; workers/domains chat.padiem.net -> $Script:FrontWorker; $Script:PagesHost same"
    }
    else {
        foreach ($pair in @(
                @("chat.padiem.net /health", "$Script:PublicHost/health"),
                @("chat.padiem.net /privacy", "$Script:PublicHost/privacy"),
                @("padiem-chat.pages.dev /privacy", "$Script:PagesHost/privacy")
            )) {
            $status = Get-HttpStatus $pair[1]
            $verify.Add("$($pair[0])=$status") | Out-Null
            if ($status -ne 200) { throw "STEP5_FAIL: $($pair[0]) returned $status" }
        }

        foreach ($pair in @(
                @("chat.padiem.net", "$Script:PublicHost"),
                @("padiem-chat.pages.dev", $Script:PagesHost)
            )) {
            foreach ($asset in @("chat-transport.js", "index.html")) {
                $live = Get-HttpBytes ($pair[1] + "/" + $asset)
                $liveHash = ([System.BitConverter]::ToString(
                        [System.Security.Cryptography.SHA256]::Create().ComputeHash($live)
                    )).Replace("-", "").ToLowerInvariant()
                $pinned = Get-FileSha256Hex (Join-Path $shaStaticDir $asset)
                $ok = $liveHash -eq $pinned
                $verify.Add("$($pair[0])/$asset sha256=$(if ($ok) { 'match' } else { 'MISMATCH' })") | Out-Null
                if (-not $ok) {
                    throw "STEP5_FAIL: $($pair[0])/$asset sha256 mismatch (live $liveHash vs sha $pinned)"
                }
            }
        }

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
    }
}
catch {
    Invoke-FrontRollbackIfNeeded
    throw
}

foreach ($line in $verify) { Write-Info $line; Add-Summary "VERIFY $line" }

# ── step 6 ───────────────────────────────────────────────────────────────────
Write-Step "6/6 report"
Write-Info "release complete; the summary below is the deploy record"
Show-Summary
if ($DryRun) {
    Write-Host "DRYRUN: nothing was deployed."
}
