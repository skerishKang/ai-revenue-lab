# Living Travel External Staging Evidence (Issue #74)

**Date**: 2026-07-24  
**PR**: #88  
**Branch**: `ops/living-travel-external-staging-74`  
**Deployment source**: PR #88 current head, verified through the Living Travel Cloudflare deployment status.

## Infrastructure

| Component | Verified staging resource |
|---|---|
| Neon | `ai-revenue-living-travel`, `aws-ap-southeast-1`, PostgreSQL 17.10 |
| Modal | `ai-revenue-living-travel-staging` |
| Modal endpoint | `https://padiemipu--ai-revenue-living-travel-staging-web.modal.run` |
| Cloudflare Pages | `ai-revenue-living-travel` |
| Production origin | `https://ai-revenue-living-travel.pages.dev` |
| Stable branch preview | `https://ops-living-travel-external-s.ai-revenue-living-travel.pages.dev` |
| Firebase project | `ai-revenue-lab-identity` |
| Firebase Web App | `living-travel-staging` |

The pooled runtime and direct migration endpoints were verified independently. Connection strings, hostnames, passwords, service-account details, account emails, Firebase UIDs, invitation codes, and internal entity IDs are not recorded here.

## External staging verification

### Database and API

- [x] Dedicated Neon project and database operational
- [x] PostgreSQL 17.10 confirmed
- [x] Pooled runtime endpoint verified
- [x] Direct migration endpoint verified
- [x] Modal Secret configured with the required eight keys
- [x] Modal application deployed
- [x] `/health` returns `200 {"status":"ok"}`
- [x] Startup migrations complete successfully
- [x] No SQLite persistent volume is used by Modal

### CORS and CSP

- [x] Production Pages origin allowed by CORS
- [x] Stable branch preview origin allowed by CORS
- [x] Unauthorized origin receives no `Access-Control-Allow-Origin`
- [x] No wildcard CORS origin
- [x] Staging CSP contains the exact Modal and Firebase origins
- [x] No `unsafe-eval` or wildcard script origin

### Firebase browser authentication

- [x] Firebase public Web config connected
- [x] Email/Password provider enabled
- [x] Dedicated synthetic operator account created
- [x] Dedicated synthetic traveler account created
- [x] Email input uses `type="email"` and `autocomplete="username"`
- [x] Password input uses `type="password"` and `autocomplete="current-password"`
- [x] No sign-up, password-reset, or role-selection UI
- [x] Authentication failures render only generic messages
- [x] Operator Email/Password sign-in resolves to `role=operator`
- [x] Traveler sign-in resolves to `role=none` before claim and `role=traveler` after claim
- [x] Google sign-in remains available as an optional live smoke path
- [x] Application scripts do not store credentials or ID tokens in custom Web Storage
- [x] Credentials are not written to DOM output, console output, logs, or evidence

Synthetic staging credentials are held in a user-controlled secret store outside the repository. The repository contains no account emails, passwords, Firebase UIDs, or credential file paths.

### Invitation replay and authorization

| Scenario | Result |
|---|---|
| First invitation claim | 200 |
| Same-identity replay | 400 `invitation_claim_failed` |
| Foreign-identity replay | 400 `invitation_claim_failed` |
| Raw invitation code stored in DB | No; digest-only contract verified |
| Final non-revoked identity mapping | Exactly one |
| Traveler own preferences and editions | 200 |
| Traveler access to operator endpoint | 403 |
| Unmapped identity access to traveler endpoint | 401 |
| Unmapped `/me` | `role=none` |
| Deactivated traveler API access | 401 |
| Deactivated `/me` | `role=none` |
| Reactivated `/me` | `role=traveler` |

### Feedback and publication state machine

| Scenario | Result |
|---|---|
| First generation | 200, `pending_review` |
| Publish first edition | 200, `published` |
| Traveler feedback with direction choices | 200 |
| Second generation | 200 |
| Reject second edition | 200, `rejected` |
| Duplicate publish | 409 |
| Reject after publish | 409 |
| Duplicate reject | 409 |
| Publish after reject | 409 |
| Traveler edition visibility | Published visible; rejected hidden |

### Cold-start persistence

- [x] Modal scale-to-zero window confirmed at 60 seconds
- [x] New-container cold start observed at approximately eight seconds
- [x] Post-cold-start `/health` returns 200
- [x] Migrations re-run idempotently
- [x] Operator and traveler mappings persist
- [x] Consumed invitation remains unusable
- [x] Traveler active status persists
- [x] Publication state persists
- [x] Feedback-to-edition relationship persists
- [x] Neon rows persist
- [x] Modal logs contain no secret, database URL, or token exposure

## Local verification reported for final cleanup head

- [x] Unit tests: **119 passed**
- [x] Staging contract tests: **50 passed**
  - Existing contract coverage plus **14 Email/Password authentication contract tests**
- [x] Pages preview tests: **54 passed**
- [x] Packaging: source distribution and wheel built successfully
- [x] Modal import: `modal import ok`
- [x] `git diff --check`: clean
- [x] Secret and identifier scan: clean

GitHub Actions was not used as acceptance evidence under the repository's private-CI cost policy. The acceptance evidence is the reported local test execution, inspected source contracts, successful Living Travel Cloudflare deployment, and external synthetic staging verification.

## Repository changes

1. `modal_app.py`: correct Modal image build ordering
2. `config.js`: apply the real public Firebase Web config and actual Modal API origin
3. `_headers`: pin CSP to the actual Modal and Firebase origins
4. `firebase.js`: add `signInWithEmailAndPassword` through a narrow wrapper
5. `index.html`: add the staging Email/Password sign-in form while retaining Google sign-in
6. `app-index.js`: add generic-error Email/Password handling without credential logging
7. `test_staging_contract.py`: pin the actual API origin and add 14 Email/Password security-contract tests
8. This report: retain sanitized staging evidence only

## Completion criteria

- [x] Dedicated Neon PostgreSQL operational
- [x] Pooled and direct endpoints separated and verified
- [x] Modal staging API healthy
- [x] Firebase Web App and Email/Password provider operational
- [x] Exact authorized domains, CORS origins, and CSP origins configured
- [x] Cloudflare Living Travel stable branch preview operational
- [x] Operator and traveler browser authentication verified
- [x] Invitation replay rejected
- [x] Authorization boundaries enforced
- [x] Publication terminal transitions enforced
- [x] Cold-start persistence verified
- [x] No secret or synthetic account identifier committed
- [x] Final local and preview suites pass

**Living Travel external staging completion criteria are satisfied.**
