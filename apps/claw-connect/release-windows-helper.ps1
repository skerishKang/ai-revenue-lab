# PADIEM user-session helper — one-command release (#7117 PR-4).
#
# Builds the no-Python helper EXE, uploads it to the dedicated public R2
# bucket at an immutable versioned key, verifies the served bytes, and
# dispatches the existing B62 production gate with explicit set_var values for
# the Chat Worker. It never writes a secret and never commits a binary.
#
# The R2 bucket and its custom domain are one-time infrastructure. See
# docs/operations/PC_USER_HELPER_RELEASE_20261107.md for the exact prerequisite
# and the rollback procedure.
[CmdletBinding()]
param(
    [string]$Python = (Get-Command python -ErrorAction SilentlyContinue).Source,
    [string]$OutRoot = "",
    [string]$Bucket = "padiem-pc-helper-releases",
    [string]$PublicBaseUrl = "https://downloads.padiem.net",
    [string]$KeyPrefix = "pc-helper",
    [string]$TargetSha = "",
    [string]$ArtifactPath = "",
    [string]$Version = "",
    [switch]$DryRun,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $Here "..\..")).Path
$Builder = Join-Path $Here "build-windows-helper.ps1"
$Workflow = "b62-production-code-deploy-gate.yml"
$Confirmation = "DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN"

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
    if (-not (Test-Path -LiteralPath $Builder -PathType Leaf)) {
        throw "helper builder is missing: $Builder"
    }
    $builderArgs = @{}
    if ($Python) { $builderArgs.Python = $Python }
    if ($OutRoot) { $builderArgs.OutRoot = $OutRoot }
    $buildLines = @(& $Builder @builderArgs)
    if ($buildLines.Count -eq 0) { throw "helper builder produced no receipt" }
    $build = [string]$buildLines[$buildLines.Count - 1] | ConvertFrom-Json
    if (-not $build.ok) { throw "helper builder did not report ok" }
    $Exe = [string]$build.exe
    $Version = [string]$build.version
    $SourceSha = [string]$build.source_sha
} else {
    if (-not $Version) { throw "-Version is required with -ArtifactPath" }
    $Exe = (Resolve-Path -LiteralPath $ArtifactPath).Path
    $SourceSha = (& git -C $RepoRoot rev-parse HEAD).Trim()
}

if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "helper EXE is missing: $Exe" }
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$') {
    throw "helper version is not a safe path segment: $Version"
}
if ($PublicBaseUrl -notmatch '^https://[^/]+') {
    throw "PublicBaseUrl must be an https origin: $PublicBaseUrl"
}

$File = Get-Item -LiteralPath $Exe
$Sha = Get-Sha256Hex -Path $Exe
$Bytes = [int64]$File.Length
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
Write-Output "HELPER_RELEASE_VAR_TARGET=padiem-chat Worker (apps/padiem-chat/wrangler.toml:207-208)"

if ($DryRun) {
    $plannedTarget = if ($TargetSha) { $TargetSha } else { "<origin/main>" }
    $plannedSetVar = ([ordered]@{
        PC_USER_HELPER_INSTALL_URL = $Url
        PC_USER_HELPER_SHA256 = $Sha
    } | ConvertTo-Json -Compress)
    $plannedBody = [ordered]@{
        ref = "main"
        inputs = [ordered]@{
            mode = "deploy_production_code"
            target_sha = $plannedTarget
            confirmation = $Confirmation
            set_var = $plannedSetVar
        }
    }
    if ($ArtifactPath) {
        Write-Output "PLAN_BUILD=SKIPPED_ARTIFACT_PATH"
    } else {
        Write-Output "PLAN_BUILD=build-windows-helper.ps1 -OutRoot $OutRoot"
    }
    Write-Output ("PLAN_R2_UPLOAD=wrangler r2 object put `"$Bucket/$Key`" --file `"$Exe`" --content-type application/octet-stream --cache-control `"public, max-age=31536000, immutable`" --remote")
    Write-Output ("PLAN_R2_CHECKSUM=wrangler r2 object put `"$Bucket/$ShaKey`" --file <temporary sha256 file> --content-type text/plain --cache-control `"public, max-age=31536000, immutable`" --remote")
    Write-Output ("PLAN_DEPLOY_BODY=" + ($plannedBody | ConvertTo-Json -Depth 6 -Compress))
    Write-Output "PLAN_VERIFY=GET $Url and compare SHA-256 $Sha"
    Write-Output "PRODUCTION_MUTATION=0"
    return
}

$Wrangler = (Get-Command wrangler -ErrorAction SilentlyContinue).Source
if (-not $Wrangler) { throw "wrangler is not on PATH" }
& gh auth status *> $null
if ($LASTEXITCODE -ne 0) { throw "gh is not authenticated; run gh auth status" }

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

if (-not $TargetSha) {
    Invoke-Checked -FilePath "git" -Arguments @("-C", $RepoRoot, "fetch", "origin", "main", "--quiet") -What "git fetch"
    $TargetSha = (& git -C $RepoRoot rev-parse origin/main).Trim()
}
if ($TargetSha -notmatch '^[0-9a-fA-F]{40}$') {
    throw "TargetSha must be the exact 40-hex main commit"
}

$RepoSlug = $env:GITHUB_REPOSITORY
if (-not $RepoSlug) {
    $RepoSlug = (& gh repo view --json nameWithOwner --jq .nameWithOwner).Trim()
}
if ($RepoSlug -notmatch '^[^/]+/[^/]+$') { throw "could not determine owner/repository" }

$setVar = ([ordered]@{
    PC_USER_HELPER_INSTALL_URL = $Url
    PC_USER_HELPER_SHA256 = $Sha
} | ConvertTo-Json -Compress)
$body = [ordered]@{
    ref = "main"
    inputs = [ordered]@{
        mode = "deploy_production_code"
        target_sha = $TargetSha
        confirmation = $Confirmation
        set_var = $setVar
    }
}
$bodyPath = Join-Path ([System.IO.Path]::GetTempPath()) ("padiem-helper-release-" + [guid]::NewGuid().ToString("N") + ".json")
try {
    [System.IO.File]::WriteAllText(
        $bodyPath,
        ($body | ConvertTo-Json -Depth 6 -Compress),
        (New-Object System.Text.UTF8Encoding($false))
    )
    Invoke-Checked -FilePath "gh" -Arguments @(
        "api", "--method", "POST",
        "repos/$RepoSlug/actions/workflows/$Workflow/dispatches",
        "--input", $bodyPath
    ) -What "B62 production dispatch"
} finally {
    Remove-Item -LiteralPath $bodyPath -Force -ErrorAction SilentlyContinue
}
Write-Output "HELPER_RELEASE_DEPLOY=DISPATCHED"

$runId = $null
$runUrl = $null
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 3
    $runsJson = & gh run list --workflow $Workflow --limit 10 --json databaseId,headSha,url,status 2>$null
    if ($LASTEXITCODE -ne 0) { continue }
    $runs = @($runsJson | ConvertFrom-Json)
    $run = $runs | Where-Object { $_.headSha -eq $TargetSha } | Select-Object -First 1
    if ($run) {
        $runId = $run.databaseId
        $runUrl = $run.url
        break
    }
}
if (-not $runId) {
    throw "B62 dispatch was accepted but no run for $TargetSha appeared; inspect gh run list --workflow $Workflow"
}
Write-Output "HELPER_RELEASE_RUN_ID=$runId"
Write-Output "HELPER_RELEASE_RUN_URL=$runUrl"

if (-not $NoWait) {
    & gh run watch $runId --exit-status
    if ($LASTEXITCODE -ne 0) { throw "B62 production gate failed; inspect $runUrl" }
    Write-Output "HELPER_RELEASE_DEPLOY=PASS"
} else {
    Write-Output "HELPER_RELEASE_DEPLOY=NOT_WAITED"
}
