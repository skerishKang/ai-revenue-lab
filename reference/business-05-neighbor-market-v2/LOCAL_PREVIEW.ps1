param(
    [string]$RepoPath = "G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab",
    [string]$WorktreePath = "G:\Ddrive\BatangD\task\workdiary\ai-revenue-lab-neighbor-market-reference",
    [int]$Port = 4173
)

$ErrorActionPreference = "Stop"
$Branch = "design/business-05-neighbor-market-v2-89"
$RelativeReference = "reference/business-05-neighbor-market-v2"
$PrimaryFile = "index-v3.html"

Write-Host "[1/6] Validate source repository"
if (-not (Test-Path (Join-Path $RepoPath ".git"))) {
    throw "Repository not found: $RepoPath"
}

Set-Location $RepoPath

Write-Host "[2/6] Fetch remote branch without modifying the current checkout"
git fetch origin $Branch
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }

Write-Host "[3/6] Create or refresh a dedicated reference worktree"
if (Test-Path $WorktreePath) {
    $existingGit = Join-Path $WorktreePath ".git"
    if (-not (Test-Path $existingGit)) {
        throw "Worktree target exists but is not a Git worktree: $WorktreePath"
    }

    Set-Location $WorktreePath
    $dirty = git status --short
    if ($dirty) {
        throw "Reference worktree is dirty. Do not reset or clean it automatically.`n$dirty"
    }

    git fetch origin $Branch
    if ($LASTEXITCODE -ne 0) { throw "worktree fetch failed" }
    git switch --detach "origin/$Branch"
    if ($LASTEXITCODE -ne 0) { throw "worktree detach failed" }
} else {
    Set-Location $RepoPath
    git worktree add --detach $WorktreePath "origin/$Branch"
    if ($LASTEXITCODE -ne 0) { throw "git worktree add failed" }
}

$ReferencePath = Join-Path $WorktreePath $RelativeReference
$IndexPath = Join-Path $ReferencePath $PrimaryFile
if (-not (Test-Path $IndexPath)) {
    throw "Reference prototype not found: $IndexPath"
}

Write-Host "[4/6] Verify exact branch head and clean state"
Set-Location $WorktreePath
$LocalSha = git rev-parse HEAD
$RemoteSha = git rev-parse "origin/$Branch"
if ($LocalSha -ne $RemoteSha) {
    throw "Local/remote SHA mismatch: local=$LocalSha remote=$RemoteSha"
}
if (git status --short) {
    throw "Reference worktree is unexpectedly dirty"
}

Write-Host "[5/6] Start a local static server"
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    throw "Python or py launcher is required to serve the reference"
}

Set-Location $ReferencePath
$Url = "http://127.0.0.1:$Port/$PrimaryFile"

$Existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $Existing) {
    Start-Process -FilePath $Python.Source -ArgumentList "-m", "http.server", "$Port", "--bind", "127.0.0.1" -WorkingDirectory $ReferencePath
    Start-Sleep -Seconds 2
}

Write-Host "[6/6] Open the resident-first reference in the default browser"
Start-Process $Url

Write-Host ""
Write-Host "Reference URL: $Url"
Write-Host "Primary file: $PrimaryFile"
Write-Host "Worktree: $WorktreePath"
Write-Host "Branch: $Branch"
Write-Host "SHA: $LocalSha"
Write-Host "Priority: current apartment -> nearby apartment -> neighborhood"
Write-Host ""
Write-Host "This script does not modify, reset, stash or clean the user's existing checkout."
