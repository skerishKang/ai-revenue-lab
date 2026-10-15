# Cloudflare Credential Operations

## Current credential status

| Field | Value |
|-------|-------|
| GitHub secret | `CLOUDFLARE_API_TOKEN` (GitHub production environment) |
| Cloudflare token name | `ai-revenue-lab-pages` |
| Type | Wrangler OAuth access token (temporary) |
| Last verified | Run `30581067392` (2026-07-30) |
| Status | Temporary recovery credential |
| D1 scope | Added Account > D1 > Edit 2026-09-06 (needed by `b54-engine-d1-provision-gate.yml`) |

## Risk

- The current token is a Wrangler OAuth access token copied from local credential storage
- It cannot auto-renew in GitHub Actions
- Token expiry is unknown
- A dedicated Cloudflare CI API token with `pages:write` scope is recommended
- Scope limits (verified 2026-09-06): the token as originally provisioned had no D1 permission — `wrangler d1 list` failed with `Authentication error [code: 10000]` on `/accounts/{account}/d1/database`. Account > D1 > Edit was added. DNS write, Secrets Store, subdomain toggling, and D1 were all outside the original scope.

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

## 2026-10-15 B66 운영 D1: 검증된 GitHub Actions 접근

COM1 로컬 Wrangler의 D1 API `10000 Authentication error`는 GitHub Actions 보호된 자격증명의 권한과 별개입니다. 이미 041/042/044가 운영 D1에 적용되어 있음이 [읽기 전용 run 38693899424](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38693899424)에서 확인됐습니다. 검증된 성공 사례, 재사용 명령, 배포 순서는 [B66_D1_ACCESS_AND_PRODUCTION_RELEASE_20261015.md](B66_D1_ACCESS_AND_PRODUCTION_RELEASE_20261015.md)를 참고하세요. 위 2026-07/09 자격증명 표는 당시 기록으로, 현 운영 토큰 종류·교체 여부의 실시간 증명이 아닙니다.
