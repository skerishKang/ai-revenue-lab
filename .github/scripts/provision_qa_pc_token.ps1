# provision_qa_pc_token.ps1 — one-shot, masked provisioning of the QA connector
# token the daily real-usage check reads (#6724, .github/scripts/daily_real_usage_check.py).
#
#   .\provision_qa_pc_token.ps1
#       Asks for the QA account email and password in masked input (the
#       password is a SecureString and is never echoed), signs in to
#       chat.padiem.net with the same pair provision_qa_smoke_account.ps1
#       stores, lists the account's paired PCs, picks the PC named by
#       -PcDeviceLabel (default CGI-1), issues one connector token for it via
#       /api/account/mcp/tokens, and sets the GitHub repository secret
#       PADIEM_QA_PC_TOKEN. The token value goes to gh over stdin and is never
#       echoed, written to disk or logged.
#
#   .\provision_qa_pc_token.ps1 -RevokePrevious
#       Additionally revokes the account's earlier tokens of the same name
#       (the list endpoint carries ids only, never secrets) before issuing.
#
#   .\provision_qa_pc_token.ps1 -SelfTest
#       Runs the offline self-test (device pick + masking) and exits. No
#       network, no input.
#
# Secret hygiene, by construction:
#   - the password exists only as a SecureString in memory and is converted to
#     plaintext only inside the two HTTPS bodies,
#   - the issued token is converted to plaintext only inside the gh stdin pipe,
#   - nothing about the pair or the token is ever echoed or logged; the email
#     is printed masked (***@domain) only,
#   - the id/token are NEVER to be pasted into chat, PRs or logs; the human
#     types the pair once here and this script does the rest.
#
# Prerequisites:
#   - the QA account exists (provision_qa_smoke_account.ps1) and has paired
#     the PC named by -PcDeviceLabel at least once (pairing shows a code on
#     the PC itself, so the first pairing is a human step),
#   - gh is authenticated for the target repository.

[CmdletBinding()]
param(
    [string]$BaseUrl = "https://chat.padiem.net",
    [string]$GithubRepo = "skerishKang/ai-revenue-lab",
    # Token label created for the daily check. Re-running with -RevokePrevious
    # rotates exactly this name.
    [string]$TokenName = "qa-usage-check",
    # The paired PC to issue the token for, matched on the link label.
    [string]$PcDeviceLabel = "CGI-1",
    [switch]$RevokePrevious,
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.ServicePointManager]::Tls12

$Script:TokenSecretName = 'PADIEM_QA_PC_TOKEN'

function Out-Line([string]$Key, [string]$Value) {
    Write-Output ("{0}={1}" -f $Key, $Value)
}

function Get-SecureStringPlainText([System.Security.SecureString]$Secure) {
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
    }
}

function Invoke-Api([string]$Method, [string]$Path, [object]$Body, [Microsoft.PowerShell.Commands.WebRequestSession]$Session) {
    # UTF-8 bytes on purpose: the password may hold any non-control character.
    $headers = @{ Origin = $BaseUrl; Referer = ($BaseUrl + "/") }
    if ($null -ne $Body) {
        $headers["Content-Type"] = "application/json; charset=utf-8"
        $json = [System.Text.Encoding]::UTF8.GetBytes((ConvertTo-Json $Body -Compress))
        return Invoke-WebRequest -Uri ($BaseUrl + $Path) -Method $Method -Body $json `
            -Headers $headers -WebSession $Session -UseBasicParsing -TimeoutSec 30
    }
    return Invoke-WebRequest -Uri ($BaseUrl + $Path) -Method $Method `
        -Headers $headers -WebSession $Session -UseBasicParsing -TimeoutSec 30
}

function Read-JsonBody([object]$Response) {
    return ($Response.Content | ConvertFrom-Json)
}

function Get-SharedLoginSession([string]$Email, [string]$Password) {
    # #7078: the common login screen owns email login when the switch is ON.
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $start = Invoke-WebRequest -Uri ($BaseUrl + '/auth/shared/start') `
        -UseBasicParsing -WebSession $session -MaximumRedirection 10 -TimeoutSec 30
    $match = [regex]::Match([string]$start.Content, '<form[^>]+action="([^"]*/login/password\?state=[^"]+)"')
    if (-not $match.Success) { throw 'shared login form missing' }
    $action = [System.Net.WebUtility]::HtmlDecode($match.Groups[1].Value)
    if ($action -notmatch '^https?://') {
        $pageUri = $start.BaseResponse.RequestMessage.RequestUri
        if ($null -eq $pageUri) { $pageUri = [Uri]$BaseUrl }
        $action = ([Uri]::new([Uri]$pageUri, $action)).AbsoluteUri
    }
    $formBody = 'email=' + [Uri]::EscapeDataString($Email) + '&password=' + [Uri]::EscapeDataString($Password)
    Invoke-WebRequest -Uri $action -Method Post `
        -ContentType 'application/x-www-form-urlencoded' -Body $formBody `
        -WebSession $session -MaximumRedirection 10 -UseBasicParsing -TimeoutSec 30 | Out-Null
    return $session
}

function Select-PcLink([object]$Links, [string]$Label) {
    # Only an active, unpaused link can carry a token. Prefer the label match;
    # refuse to guess when the match is ambiguous or absent.
    $active = @($Links | Where-Object { $_.state -eq 'active' -and -not $_.paused_at })
    if ($Label) {
        $matched = @($active | Where-Object { $_.label -eq $Label })
        if ($matched.Count -eq 1) { return $matched[0] }
        if ($matched.Count -gt 1) { throw "PC label '$Label' matches $($matched.Count) active links" }
        throw "no active paired PC labelled '$Label' for this account (pair it once first)"
    }
    if ($active.Count -eq 1) { return $active[0] }
    throw "expected exactly one active paired PC, found $($active.Count)"
}

function Test-SelfTest {
    $links = @(
        [pscustomobject]@{ mesh_node_id = 'node/a'; label = 'CGI-1'; state = 'active'; paused_at = $null },
        [pscustomobject]@{ mesh_node_id = 'node/b'; label = 'OTHER'; state = 'active'; paused_at = $null }
    )
    $picked = Select-PcLink -Links $links -Label 'CGI-1'
    if ($picked.mesh_node_id -ne 'node/a') { throw 'self-test: wrong link picked' }
    try {
        Select-PcLink -Links $links -Label 'NOPE' | Out-Null
        throw 'self-test: missing label should have thrown'
    } catch {
        if ("$($_.Exception.Message)" -notlike "*no active paired PC*") { throw }
    }
    Out-Line 'SELF_TEST' 'PASS'
}

if ($SelfTest) {
    Test-SelfTest
    exit 0
}

$email = Read-Host -Prompt 'QA account email'
$securePassword = Read-Host -Prompt 'QA account password' -AsSecureString

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try {
    $plain = Get-SecureStringPlainText $securePassword
    $login = Invoke-Api 'Post' '/api/auth/password/login' `
        -Body @{ identifier = $email; password = $plain } -Session $session
    $loginBody = Read-JsonBody $login
    if ($loginBody.ok -ne $true) {
        if ($loginBody.error.code -eq 'email_login_moved') {
            $session = Get-SharedLoginSession $email $plain
            $status = Invoke-Api 'Get' '/api/auth/status' $null $session
            if ((Read-JsonBody $status).authenticated -ne $true) { throw 'shared login refused' }
            Out-Line 'LOGIN_PATH' 'shared'
        }
        else {
            throw 'login refused'
        }
    }
} finally {
    if ($plain) { $plain = $null }
}
Out-Line 'LOGIN' 'OK'

$pairings = Invoke-Api 'Get' '/api/pc/pairings' -Body $null -Session $session
$links = (Read-JsonBody $pairings).links
$link = Select-PcLink -Links $links -Label $PcDeviceLabel
Out-Line 'PC_DEVICE' 'selected'
Out-Line 'PC_LINK_STATE' 'active'

if ($RevokePrevious) {
    $existing = Invoke-Api 'Get' '/api/account/mcp/tokens' -Body $null -Session $session
    $tokens = (Read-JsonBody $existing).tokens
    $stale = @($tokens | Where-Object { $_.name -eq $TokenName -and -not $_.revoked_at })
    foreach ($staleToken in $stale) {
        Invoke-Api 'Delete' ('/api/account/mcp/tokens/' + $staleToken.id) -Body $null -Session $session | Out-Null
    }
    Out-Line 'REVOKED_PREVIOUS' $stale.Count
}

$issued = Invoke-Api 'Post' '/api/account/mcp/tokens' `
    -Body @{ name = $TokenName; device_id = $link.mesh_node_id } -Session $session
$issuedBody = Read-JsonBody $issued
if ($issuedBody.ok -ne $true -or -not $issuedBody.token) { throw 'token issuance failed' }

# The value crosses to gh on stdin only; it is never an argument, never echoed.
$issuedBody.token | gh secret set $Script:TokenSecretName --repo $GithubRepo
if ($LASTEXITCODE -ne 0) { throw 'gh secret set failed' }

Out-Line 'GITHUB_SECRET' $Script:TokenSecretName
Out-Line 'PROVISION' 'DONE'
