# COM2 Cloudflare auth check helper.
# Purpose: distinguish local process/project/user/system environment API tokens
# from the stored Wrangler OAuth profile without printing any secret value.
# This implements the child-process isolation documented in
# docs/operations/CLOUDFLARE_CREDENTIAL_OPERATIONS.md section 3.

$ErrorActionPreference = "Stop"

$authChildScript = @'
Remove-Item Env:CLOUDFLARE_API_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:CF_API_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:CLOUDFLARE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:CF_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:CLOUDFLARE_EMAIL -ErrorAction SilentlyContinue
Remove-Item Env:CF_EMAIL -ErrorAction SilentlyContinue
npx --no-install wrangler whoami
exit $LASTEXITCODE
'@

Write-Host "AUTH_SOURCE_CHECK=child_process_without_env_tokens"
Write-Host "HOST_CONTEXT=COM2 / Windows user / current working directory"
Write-Host "NOTE=No token values are printed by this script."

& (Get-Process -Id $PID).Path -NoProfile -Command $authChildScript
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "AUTH_CHECK=PASS"
} else {
    Write-Host "AUTH_CHECK=FAIL"
    Write-Host "NEXT=Inspect the Wrangler OAuth profile and refresh_token state; do not create or rotate tokens without owner authorization."
}

exit $exitCode
