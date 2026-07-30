# Cloudflare Credential Operations

## Current credential status

| Field | Value |
|-------|-------|
| GitHub secret | `CLOUDFLARE_API_TOKEN` |
| Type | Wrangler OAuth access token (temporary) |
| Last verified | Run `30581067392` (2026-07-30) |
| Status | Temporary recovery credential |

## Risk

- The current token is a Wrangler OAuth access token copied from local credential storage
- It cannot auto-renew in GitHub Actions
- Token expiry is unknown
- A dedicated Cloudflare CI API token with `pages:write` scope is recommended

## Weekly audit

The `audit-cloudflare-pages-credentials.yml` workflow runs every Monday (09:00 KST)
and can also be dispatched manually. It performs read-only checks:

- Token existence and Cloudflare verification
- Account ID match
- Pages API accessibility
- Business 37 project existence and Git-connected contract
- Production URL reachability

## Related resources

- Private operations repository: `skerishKang/ai-revenue-operations`
- Incident record: `incidents/2026-07-31-cloudflare-pages-credential-401.md`

## [Security] In-process isolation for Cloudflare token verification

To prevent mock bypasses caused by subprocesses during testing, `urllib.request` has been patched in-process. This ensures that the test runner strictly isolates Cloudflare API token checks and accurately handles simulated network boundaries.

All references to `wrangler pages deploy` have been removed or replaced with `TODO: wait for official deploy` to strictly prevent mutations.
