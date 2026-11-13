#Requires -Version 7.0
# The default PC label holds non-ASCII text; Windows PowerShell 5.1 reads a
# BOM-less script in the ANSI code page and would never match it, so run with pwsh.
# provision_qa_pc_token.ps1 — one-shot, masked provisioning of the QA connector
# token the daily real-usage check reads (#6724, .github/scripts/daily_real_usage_check.py).
#
#   .\provision_qa_pc_token.ps1
#       Asks for the QA account email and password in masked input (the
#       password is a SecureString and is never echoed), signs in to
#       chat.padiem.net with the same pair provision_qa_smoke_account.ps1
#       stores, lists the account's paired PCs, picks the PC named by
#       -PcDeviceLabel (default "K_lipvoice · 컴2"), issues one connector
#       token for it via /api/account/mcp/tokens, and sets the GitHub
#       repository secret PADIEM_QA_PC_TOKEN. The token value goes to gh over
#       stdin and is never echoed, written to disk or logged.
#
#   .\provision_qa_pc_token.ps1 -RevokePrevious
#       Additionally revokes the account's earlier tokens of the same name
#       (the list endpoint carries ids only, never secrets) before issuing.
#
#   .\provision_qa_pc_token.ps1 -SelfTest
#       Runs the offline self-test (device pick + masking) and exits. No
#       network, no input.
#
#   .\provision_qa_pc_token.ps1 -FromCom2Env
#       Non-interactive: reads the QA pair from COM2's root-only
#       /etc/padiem/qa-smoke.env over ssh (the same file
#       provision_qa_smoke_account.ps1 writes), verifies it is root:0600,
#       then signs in and issues the token. No prompt, no credential on the
#       command line, no credential in the output. The file content crosses
#       ssh stdout into memory only; it is never copied, printed or written.
#
# Secret hygiene, by construction:
#   - the password exists only as a SecureString in memory and is converted to
#     plaintext only inside the two HTTPS bodies, or arrives from COM2's env
#     file over ssh stdout into memory,
#   - the issued token is converted to plaintext only inside the gh stdin pipe,
#   - nothing about the pair or the token is ever echoed or logged; the email
#     is not printed,
#   - the id/token are NEVER to be pasted into chat, PRs or logs; the human
#     types the pair once here (or -FromCom2Env reads it from COM2) and this
#     script does the rest.
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
    # The paired PC to issue the token for, matched on the link label. The
    # comparison is exact: the label is the display name (for example
    # "K_lipvoice · 컴2"), and a partial match could silently pick another PC.
    [string]$PcDeviceLabel = "K_lipvoice · 컴2",
    # Read the QA pair from COM2's root-only env file instead of prompting.
    [switch]$FromCom2Env,
    # COM2 ssh target and key, same shape as provision_qa_smoke_account.ps1.
    [string]$Com2SshTarget = "user@192.168.0.101",
    [string]$Com2SshKey = "C:\Users\limone\.ssh\id_rsa",
    # Root-only env file on COM2 the deploy script sources.
    [string]$Com2EnvPath = "/etc/padiem/qa-smoke.env",
    [string]$Com2EnvUsernameKey = "B66_CGI_ALPHA_USERNAME",
    [string]$Com2EnvPasswordKey = "B66_CGI_ALPHA_PASSWORD",
    [switch]$RevokePrevious,
    [switch]$SelfTest,
    [switch]$SelfTestEnv
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

function Get-Com2SshArguments([string]$RemoteCommand) {
    # The remote command and the key path are the only argv text; the pair
    # never reaches argv (it would be visible in the process list).
    return '-i "{0}" -o BatchMode=yes -o ConnectTimeout=10 {1} {2}' -f $Com2SshKey, $Com2SshTarget, $RemoteCommand
}

function Invoke-Com2Capture([string]$RemoteCommand) {
    # COM2's ssh lands in Windows cmd.exe, so the remote command is one bare
    # argv line that runs in COM2's WSL (not COMP1 WSL): install/cat/stat.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'ssh'
    $psi.Arguments = Get-Com2SshArguments $RemoteCommand
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $process = [System.Diagnostics.Process]::Start($psi)
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if (-not $process.WaitForExit(60000)) { $process.Kill() | Out-Null }
    return @{ exit = $process.ExitCode; stdout = $stdout; stderr = $stderr }
}

function Assert-Com2EnvPath([string]$Path) {
    if ($Path -notmatch '^/[A-Za-z0-9_./-]+$' -or $Path -match '(^|/)\.\.(/|$)') {
        throw 'NON_INTERACTIVE_ENV_PATH_INVALID'
    }
}

function Assert-EnvFileMetadata([string]$Mode, [string]$Owner, [string]$SizeText) {
    if ($Mode -ne '600') { throw "NON_INTERACTIVE_ENV_MODE mode=$Mode expected=600" }
    if ($Owner -ne 'root') { throw "NON_INTERACTIVE_ENV_OWNER owner=$Owner expected=root" }
    $size = 0
    if (-not [int]::TryParse($SizeText, [ref]$size) -or $size -le 0) { throw 'NON_INTERACTIVE_ENV_SIZE' }
}

function ConvertFrom-EnvFile([string]$Content) {
    # Shell-sourceable KEY='value' lines, parsed as data and never executed:
    # a value is data, never code. Single quotes use the writer's '\'' escape.
    $map = @{}
    foreach ($line in ($Content -split "`r?`n")) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $key = $Matches[1]
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2) {
                $first = $value.Substring(0, 1)
                $last = $value.Substring($value.Length - 1, 1)
                if ($first -eq "'" -and $last -eq "'") {
                    $value = $value.Substring(1, $value.Length - 2).Replace("'\''", "'")
                }
                elseif ($first -eq '"' -and $last -eq '"') {
                    $value = $value.Substring(1, $value.Length - 2).Replace('\"', '"').Replace('\\', '\')
                }
            }
            $map[$key] = $value
        }
    }
    return $map
}

function Get-NonInteractiveCredentials {
    Assert-Com2EnvPath $Com2EnvPath
    if (-not (Test-Path -LiteralPath $Com2SshKey)) { throw 'NON_INTERACTIVE_SSH_KEY_MISSING' }

    $exists = Invoke-Com2Capture ('wsl.exe -d Ubuntu -u root --exec test -f {0}' -f $Com2EnvPath)
    if ($exists.exit -eq 255) { throw 'NON_INTERACTIVE_SSH_FAILED exit=255' }
    if ($exists.exit -ne 0) { throw "NON_INTERACTIVE_ENV_MISSING path=$Com2EnvPath" }

    $modeResult = Invoke-Com2Capture ('wsl.exe -d Ubuntu -u root --exec stat -c %a {0}' -f $Com2EnvPath)
    if ($modeResult.exit -ne 0) { throw "NON_INTERACTIVE_REMOTE_FAILED exit=$($modeResult.exit)" }
    $ownerResult = Invoke-Com2Capture ('wsl.exe -d Ubuntu -u root --exec stat -c %U {0}' -f $Com2EnvPath)
    if ($ownerResult.exit -ne 0) { throw "NON_INTERACTIVE_REMOTE_FAILED exit=$($ownerResult.exit)" }
    $sizeResult = Invoke-Com2Capture ('wsl.exe -d Ubuntu -u root --exec stat -c %s {0}' -f $Com2EnvPath)
    if ($sizeResult.exit -ne 0) { throw "NON_INTERACTIVE_REMOTE_FAILED exit=$($sizeResult.exit)" }
    Assert-EnvFileMetadata $modeResult.stdout.Trim() $ownerResult.stdout.Trim() $sizeResult.stdout.Trim()

    $read = Invoke-Com2Capture ('wsl.exe -d Ubuntu -u root --exec cat {0}' -f $Com2EnvPath)
    if ($read.exit -ne 0) { throw "NON_INTERACTIVE_REMOTE_FAILED exit=$($read.exit)" }
    $content = $read.stdout
    $read = $null
    $map = ConvertFrom-EnvFile $content
    $content = $null

    $usernameKey = ''
    $passwordKey = ''
    if ($map.ContainsKey($Com2EnvUsernameKey) -and $map.ContainsKey($Com2EnvPasswordKey)) {
        $usernameKey = $Com2EnvUsernameKey
        $passwordKey = $Com2EnvPasswordKey
    }
    elseif ($map.ContainsKey('QA_DEPLOY_USERNAME') -and $map.ContainsKey('QA_DEPLOY_PASSWORD')) {
        $usernameKey = 'QA_DEPLOY_USERNAME'
        $passwordKey = 'QA_DEPLOY_PASSWORD'
    }
    else {
        throw "NON_INTERACTIVE_ENV_KEY_MISSING expected=$Com2EnvUsernameKey/$Com2EnvPasswordKey or QA_DEPLOY_USERNAME/QA_DEPLOY_PASSWORD"
    }

    $email = ([string]$map[$usernameKey]).Trim()
    $password = [string]$map[$passwordKey]
    $map.Clear()
    $map = $null

    if ($email -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') { throw 'INPUT_EMAIL invalid' }
    if ($password.Length -lt 8 -or $password.Length -gt 128) { throw 'INPUT_PASSWORD invalid_length' }
    return @{ email = $email; password = $password }
}

function Test-EnvSelfTest {
    $username = 'qa@example.test'
    $quoteSample = ([char]112, [char]64, [char]115, [char]115, [char]39, [char]119, [char]111, [char]114, [char]100) -join ''
    $escaped = "'" + $quoteSample.Replace("'", "'\''") + "'"
    $content = "B66_CGI_ALPHA_USERNAME='$username'`nB66_CGI_ALPHA_PASSWORD=$escaped`n"
    $map = ConvertFrom-EnvFile $content
    if ($map['B66_CGI_ALPHA_USERNAME'] -ne $username) { throw 'env self-test: username' }
    if ($map['B66_CGI_ALPHA_PASSWORD'] -ne $quoteSample) { throw 'env self-test: single-quote unescape' }

    $execLine = 'B66_CGI_ALPHA_PASSWORD=' + "'" + '$(touch /tmp/pwn)' + "'" + "`n"
    $execMap = ConvertFrom-EnvFile $execLine
    if ($execMap['B66_CGI_ALPHA_PASSWORD'] -ne '$(touch /tmp/pwn)') { throw 'env self-test: parser executed a value' }

    $missing = ConvertFrom-EnvFile "OTHER='x'`n"
    if ($missing.ContainsKey('B66_CGI_ALPHA_USERNAME')) { throw 'env self-test: missing key' }

    Assert-EnvFileMetadata '600' 'root' '123'
    foreach ($case in @(
            @{ mode = '644'; owner = 'root'; size = '123' },
            @{ mode = '600'; owner = 'nobody'; size = '123' },
            @{ mode = '600'; owner = 'root'; size = '0' }
        )) {
        try {
            Assert-EnvFileMetadata $case.mode $case.owner $case.size
            throw 'env self-test: loose metadata accepted'
        } catch {
            if ("$($_.Exception.Message)" -notlike 'NON_INTERACTIVE_ENV_*') { throw }
        }
    }

    $sshArguments = Get-Com2SshArguments 'wsl.exe -d Ubuntu -u root --exec cat /etc/padiem/qa-smoke.env'
    if ($sshArguments.Contains($username) -or $sshArguments.Contains($quoteSample)) {
        throw 'env self-test: credential reached the ssh arguments'
    }
    Out-Line 'ENV_SELFTEST' 'PASS'
}

function Invoke-Api([string]$Method, [string]$Path, [object]$Body, [Microsoft.PowerShell.Commands.WebRequestSession]$Session, [switch]$AllowHttpError) {
    # UTF-8 bytes on purpose: the password may hold any non-control character.
    # -AllowHttpError returns a non-2xx response instead of throwing, so the
    # caller can read a JSON error body (the login answers 409
    # email_login_moved when the common login owns email login).
    $headers = @{ Origin = $BaseUrl; Referer = ($BaseUrl + "/") }
    $extra = @{}
    if ($AllowHttpError) { $extra['SkipHttpErrorCheck'] = $true }
    if ($null -ne $Body) {
        $headers["Content-Type"] = "application/json; charset=utf-8"
        $json = [System.Text.Encoding]::UTF8.GetBytes((ConvertTo-Json $Body -Compress))
        return Invoke-WebRequest -Uri ($BaseUrl + $Path) -Method $Method -Body $json `
            -Headers $headers -WebSession $Session -UseBasicParsing -TimeoutSec 30 @extra
    }
    return Invoke-WebRequest -Uri ($BaseUrl + $Path) -Method $Method `
        -Headers $headers -WebSession $Session -UseBasicParsing -TimeoutSec 30 @extra
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
    # Only an active, unpaused link can carry a token. The label comparison is
    # exact: the link label is the display name (for example
    # "K_lipvoice · 컴2"), and a partial match could silently pick another PC.
    # Refuse to guess when the match is ambiguous or absent.
    $active = @($Links | Where-Object { $_.state -eq 'active' -and -not $_.paused_at })
    if ($Label) {
        $matched = @($active | Where-Object { $_.label -eq $Label })
        if ($matched.Count -eq 1) { return $matched[0] }
        if ($matched.Count -gt 1) { throw "PC label '$Label' matches $($matched.Count) active links" }
        $available = @($active | ForEach-Object { $_.label } | Where-Object { $_ })
        if ($available.Count -gt 0) {
            throw "no active paired PC labelled '$Label' for this account; active labels: $($available -join ', ') (pair the PC once first or pass -PcDeviceLabel)"
        }
        throw "no active paired PC labelled '$Label' for this account (pair it once first)"
    }
    if ($active.Count -eq 1) { return $active[0] }
    throw "expected exactly one active paired PC, found $($active.Count)"
}

function Test-SelfTest {
    $links = @(
        [pscustomobject]@{ mesh_node_id = 'node/a'; label = 'K_lipvoice · 컴2'; state = 'active'; paused_at = $null },
        [pscustomobject]@{ mesh_node_id = 'node/b'; label = 'PADIEM-COMMAND-'; state = 'active'; paused_at = $null }
    )
    $picked = Select-PcLink -Links $links -Label 'K_lipvoice · 컴2'
    if ($picked.mesh_node_id -ne 'node/a') { throw 'self-test: wrong link picked' }
    try {
        Select-PcLink -Links $links -Label 'NOPE' | Out-Null
        throw 'self-test: missing label should have thrown'
    } catch {
        $message = "$($_.Exception.Message)"
        if ($message -notlike '*no active paired PC*') { throw }
        if ($message -notlike '*K_lipvoice · 컴2*') { throw 'self-test: error should list the active labels' }
    }
    try {
        Select-PcLink -Links $links -Label '컴2' | Out-Null
        throw 'self-test: a partial label must not pick a PC'
    } catch {
        if ("$($_.Exception.Message)" -notlike '*no active paired PC*') { throw }
    }
    Out-Line 'SELF_TEST' 'PASS'
}

if ($SelfTest) {
    Test-SelfTest
    exit 0
}

if ($SelfTestEnv) {
    Test-EnvSelfTest
    exit 0
}

$plain = ''
$credentials = $null
if ($FromCom2Env) {
    $credentials = Get-NonInteractiveCredentials
    $email = $credentials.email
    $plain = $credentials.password
    $credentials.password = $null
    $credentials = $null
    Out-Line 'CREDENTIAL_SOURCE' 'com2_env'
}
else {
    $email = Read-Host -Prompt 'QA account email'
    $securePassword = Read-Host -Prompt 'QA account password' -AsSecureString
    $plain = Get-SecureStringPlainText $securePassword
    $securePassword = $null
}

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try {
    $login = Invoke-Api 'Post' '/api/auth/password/login' `
        -Body @{ identifier = $email; password = $plain } -Session $session -AllowHttpError
    $loginBody = $null
    try { $loginBody = Read-JsonBody $login } catch { throw "login refused status=$([int]$login.StatusCode)" }
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
$email = $null

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
$issuedBody.token = $null
$issuedBody = $null

Out-Line 'GITHUB_SECRET' $Script:TokenSecretName
Out-Line 'PROVISION' 'DONE'
