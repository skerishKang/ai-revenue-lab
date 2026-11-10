# provision_qa_smoke_account.ps1 — one-shot, masked provisioning of the
# deploy-smoke QA account (the B66_CGI_ALPHA_* pair the AI answer gate reads,
# .github/scripts/post_deploy_real_chat_smoke.py:105-110).
#
#   .\provision_qa_smoke_account.ps1
#       Asks for the email and the password in a masked input (the password is
#       a SecureString and is never echoed), creates the account on
#       chat.padiem.net via /api/auth/password/register when it does not exist
#       yet, verifies the exact pair against /api/auth/password/login (the
#       endpoint the smoke gate uses), and writes
#       /etc/padiem/qa-smoke.env on COM2 (root-only 0600) over ssh stdin.
#
#   .\provision_qa_smoke_account.ps1 -UpdateGithubSecret
#       Additionally sets the grade-smoke environment secrets to the same
#       pair so the GitHub-side check uses the same account (the value goes
#       to gh over stdin, never argv). Optional.
#
#   .\provision_qa_smoke_account.ps1 -SelfTestEscape
#       Runs the env-file escaping self-test and exits. No network, no input.
#
# Secret hygiene, by construction:
#   - the password exists only as a SecureString in memory; it is converted
#     to plaintext only inside the two HTTPS bodies and the env-file content
#     piped straight into the ssh process's stdin,
#   - nothing about the pair is ever echoed, written to disk, or logged; the
#     email is printed masked (***@domain) only,
#   - every line of output is KEY=VALUE without credential material.
# The id/password are NEVER to be pasted into chat, PRs or logs; the human
# types them once here and this script does the rest.

[CmdletBinding()]
param(
    # Chat origin to provision on. Default is the public production host.
    [string]$BaseUrl = "https://chat.padiem.net",
    # COM2 ssh target, same shape as release_chat.ps1 uses.
    [string]$Com2SshTarget = "user@192.168.0.101",
    [string]$Com2SshKey = "C:\Users\limone\.ssh\id_rsa",
    # Root-only env file on COM2 the deploy script sources.
    [string]$Com2EnvPath = "/etc/padiem/qa-smoke.env",
    # Also set the grade-smoke environment secrets to the same pair.
    [switch]$UpdateGithubSecret,
    # Run the env-escaping self-test and exit (used by the contract test).
    [switch]$SelfTestEscape
)

$ErrorActionPreference = 'Stop'
# PowerShell 5.1: make HTTPS negotiate TLS 1.2.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.ServicePointManager]::Tls12

$Script:UsernameEnv = 'B66_CGI_ALPHA_USERNAME'
$Script:PasswordEnv = 'B66_CGI_ALPHA_PASSWORD'
$Script:GithubEnv = 'grade-smoke'

function Out-Line([string]$Key, [string]$Value) {
    Write-Output ("{0}={1}" -f $Key, $Value)
}

function ConvertTo-EnvSingleQuoted([string]$Value) {
    # POSIX single-quote escaping so sourcing /etc/padiem/qa-smoke.env with
    # `set -a; . file; set +a` is safe for any character the password rules
    # allow (8..128 chars, no control characters — quotes included).
    return "'" + $Value.Replace("'", "'\''") + "'"
}

function Get-SecureStringPlainText([System.Security.SecureString]$Secure) {
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Invoke-AuthPost([string]$Path, [string]$Json) {
    # UTF-8 bytes on purpose: a password may hold any non-control character
    # and PS 5.1 would otherwise re-encode the body as ISO-8859-1.
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)
    try {
        $response = Invoke-WebRequest -Uri ($BaseUrl + $Path) -Method Post `
            -ContentType 'application/json; charset=utf-8' `
            -Body $bytes -UseBasicParsing -TimeoutSec 30
        return @{ status = [int]$response.StatusCode; body = [string]$response.Content }
    }
    catch {
        $http = $_.Exception.Response
        if ($null -ne $http) {
            $body = ''
            try {
                $reader = New-Object System.IO.StreamReader($http.GetResponseStream(), [System.Text.Encoding]::UTF8)
                $body = $reader.ReadToEnd()
            }
            catch {
                $body = ''
            }
            return @{ status = [int]$http.StatusCode; body = $body }
        }
        return @{ status = 0; body = '' }
    }
}

function Get-ServerErrorCode([string]$Body) {
    if ($Body -match '"code"\s*:\s*"([a-z0-9_]+)"') { return $Matches[1] }
    return 'no_json_body'
}

function Invoke-SharedLogin([string]$Email, [string]$Password) {
    # #7078: the common login screen owns email login when the switch is ON.
    # Invoke-WebRequest follows the state/PKCE redirects and keeps the cookies
    # in memory; nothing here is echoed.
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    try {
        $start = Invoke-WebRequest -Uri ($BaseUrl + '/auth/shared/start') `
            -UseBasicParsing -WebSession $session -MaximumRedirection 10 -TimeoutSec 30
        $html = [string]$start.Content
        $match = [regex]::Match($html, '<form[^>]+action="([^"]*/login/password\?state=[^"]+)"')
        if (-not $match.Success) { return @{ ok = $false; code = 'shared_login_form_missing' } }
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
        $status = Invoke-WebRequest -Uri ($BaseUrl + '/api/auth/status') `
            -UseBasicParsing -WebSession $session -TimeoutSec 30
        if ([string]$status.Content -match '"authenticated"\s*:\s*true') {
            return @{ ok = $true; code = 'none' }
        }
        return @{ ok = $false; code = 'shared_session_unverified' }
    }
    catch { return @{ ok = $false; code = 'shared_login_unreachable' } }
}

function Mask-Email([string]$Email) {
    $at = $Email.IndexOf('@')
    if ($at -lt 1) { return '***' }
    return '***' + $Email.Substring($at)
}

function Invoke-ProcessWithStdin([string]$FileName, [string]$Arguments, [string]$StdinText, [int]$WaitMs = 60000) {
    # Runs a process with $StdinText on its stdin (UTF-8), capturing stdout
    # and stderr. The stdin text never touches argv, a temp file or the log.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FileName
    $psi.Arguments = $Arguments
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $process = [System.Diagnostics.Process]::Start($psi)
    $encoding = [System.Text.Encoding]::UTF8
    $stdinBytes = $encoding.GetBytes($StdinText)
    $process.StandardInput.BaseStream.Write($stdinBytes, 0, $stdinBytes.Length)
    $process.StandardInput.BaseStream.Flush()
    $process.StandardInput.BaseStream.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if (-not $process.WaitForExit($WaitMs)) { $process.Kill() | Out-Null }
    return @{ exit = $process.ExitCode; stdout = $stdout; stderr = $stderr }
}

# ── self-test mode: fixed escaping vectors, nothing else ────────────────────
if ($SelfTestEscape) {
    $failures = 0
    foreach ($vector in @(
            @{ raw = "a'b"; expect = "'a'\''b'" },
            @{ raw = 'ab$'; expect = "'ab$'" },
            @{ raw = 'plain'; expect = "'plain'" },
            @{ raw = 'x"y'; expect = '''x"y''' },
            @{ raw = ''; expect = "''" }
        )) {
        $got = ConvertTo-EnvSingleQuoted $vector.raw
        if ($got -ne $vector.expect) {
            Out-Line 'ESCAPE_MISMATCH' ("case_{0}" -f $failures)
            $failures += 1
        }
    }
    if ($failures -eq 0) { Out-Line 'ESCAPE_SELFTEST' 'PASS' } else { Out-Line 'ESCAPE_SELFTEST' 'FAIL' }
    exit $(if ($failures -eq 0) { 0 } else { 1 })
}

# ── masked input ─────────────────────────────────────────────────────────────
# Prompts stay ASCII on purpose: PS 5.1 reads this BOM-less file as ANSI and
# would garble Korean in user-facing strings (comments only, like
# release_chat.ps1). Say for the operator: 이메일은 화면에 표시되고 비밀번호는
# 표시되지 않습니다.
$email = (Read-Host 'QA account email (visible on screen)').Trim()
if ($email -notmatch '^[^\s@]+@[^\s@]+\.[^\s@]+$') {
    Out-Line 'INPUT_EMAIL' 'invalid'
    exit 2
}
$securePassword = Read-Host 'QA account password (hidden input)' -AsSecureString
$plainPassword = Get-SecureStringPlainText $securePassword
if ($plainPassword.Length -lt 8 -or $plainPassword.Length -gt 128) {
    Out-Line 'INPUT_PASSWORD' 'invalid_length (8-128 required)'
    exit 2
}
Out-Line 'EMAIL_MASKED' (Mask-Email $email)

# ── signup (an existing pair falls through to the login verify below) ────────
$registerBody = @{ email = $email; password = $plainPassword } | ConvertTo-Json -Compress
$register = Invoke-AuthPost '/api/auth/password/register' $registerBody
if ($register.status -eq 200) {
    Out-Line 'SIGNUP' 'created'
}
elseif ($register.status -eq 409 -and (Get-ServerErrorCode $register.body) -eq 'email_login_moved') {
    # #7078 switch ON: signup moved to the common screen. The smoke account is
    # normally pre-existing; the login verify below proves the shared path.
    Out-Line 'SIGNUP' 'shared_login_required'
}
elseif ($register.status -eq 409) {
    Out-Line 'SIGNUP' ("already_exists code={0}" -f (Get-ServerErrorCode $register.body))
}
else {
    Out-Line 'SIGNUP' ("failed http={0} server_code={1}" -f $register.status, (Get-ServerErrorCode $register.body))
    Out-Line 'RESULT' 'INCOMPLETE'
    exit 2
}

# ── login verify: the exact pair the smoke gate will use ─────────────────────
$loginBody = @{ identifier = $email; password = $plainPassword } | ConvertTo-Json -Compress
$login = Invoke-AuthPost '/api/auth/password/login' $loginBody
$loginOk = ($login.status -eq 200 -and $login.body -match '"ok"\s*:\s*true')
$loginCode = Get-ServerErrorCode $login.body
if ($login.status -eq 409 -and $loginCode -eq 'email_login_moved') {
    $shared = Invoke-SharedLogin $email $plainPassword
    if ($shared.ok) {
        $loginOk = $true
        Out-Line 'LOGIN_PATH' 'shared'
    }
    else {
        Out-Line 'LOGIN_PATH' ('shared_failed code=' + $shared.code)
    }
}
if ($loginOk) {
    Out-Line 'LOGIN_VERIFY' 'PASS'
}
else {
    Out-Line 'LOGIN_VERIFY' ("FAIL http={0} server_code={1}" -f $login.status, $loginCode)
    Out-Line 'RESULT' 'INCOMPLETE'
    exit 2
}

# ── COM2 env file: piped straight into ssh stdin, root-only, never echoed ────
$envContent = ('{0}={1}' -f $Script:UsernameEnv, (ConvertTo-EnvSingleQuoted $email)) + "`n" +
    ('{0}={1}' -f $Script:PasswordEnv, (ConvertTo-EnvSingleQuoted $plainPassword)) + "`n"
# COM2's ssh lands in Windows cmd.exe: no sudo there, and cmd would chew any
# quote, pipe or redirect before wsl.exe ever sees it (the release_chat.ps1
# exit-255 trap). So the remote command is ONE bare argv line — no quotes, no
# pipes, no redirects — that ssh rejoins and cmd passes through to
# wsl.exe -d Ubuntu -u root --exec. install -D creates /etc/padiem and lands
# the file root:root 0600; stdin rides ssh -> cmd -> wsl untouched.
$com2Remote = 'wsl.exe -d Ubuntu -u root --exec install -D -m 600 /dev/stdin {0}' -f $Com2EnvPath
$sshArguments = '-i "{0}" -o BatchMode=yes -o ConnectTimeout=10 {1} {2}' -f $Com2SshKey, $Com2SshTarget, $com2Remote
$ssh = Invoke-ProcessWithStdin 'ssh' $sshArguments $envContent
if ($ssh.exit -eq 0) {
    Out-Line 'COM2_ENV' 'written'
}
else {
    Out-Line 'COM2_ENV' ("failed exit={0} stderr_class=ssh" -f $ssh.exit)
}
if ($ssh.exit -eq 0) {
    # exit 0 from `test -s` is the whole verification — no output parsing.
    $verifyRemote = 'wsl.exe -d Ubuntu -u root --exec test -s {0}' -f $Com2EnvPath
    $verify = Invoke-ProcessWithStdin 'ssh' (
        '-i "{0}" -o BatchMode=yes -o ConnectTimeout=10 {1} {2}' -f $Com2SshKey, $Com2SshTarget, $verifyRemote
    ) ''
    if ($verify.exit -eq 0) {
        Out-Line 'COM2_ENV_VERIFIED' 'true'
    }
    else {
        Out-Line 'COM2_ENV_VERIFIED' 'false'
    }
}

# ── optional: the grade-smoke environment gets the same pair ─────────────────
if ($UpdateGithubSecret) {
    $ghAllOk = $true
    foreach ($pair in @(
            @{ name = $Script:UsernameEnv; value = $email },
            @{ name = $Script:PasswordEnv; value = $plainPassword }
        )) {
        $gh = Invoke-ProcessWithStdin 'gh' (
            'secret set {0} --env {1}' -f $pair.name, $Script:GithubEnv
        ) $pair.value
        if ($gh.exit -eq 0) {
            Out-Line ("GH_SECRET_{0}" -f $pair.name) 'updated'
        }
        else {
            $ghAllOk = $false
            Out-Line ("GH_SECRET_{0}" -f $pair.name) ("failed exit={0}" -f $gh.exit)
        }
    }
    if (-not $ghAllOk) { Out-Line 'GH_SECRET_NOTE' 'gh auth or repo context missing; set them manually later' }
}
else {
    Out-Line 'GH_SECRET' 'skipped (pass -UpdateGithubSecret to reuse the same pair on GitHub)'
}

Out-Line 'RESULT' 'READY'
exit 0
