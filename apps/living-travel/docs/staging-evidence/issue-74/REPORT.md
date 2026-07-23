# Living Travel External Staging Evidence (Issue #74)

**Date**: 2026-07-24
**PR**: #88 (Draft)
**Branch**: `ops/living-travel-external-staging-74`
**Head**: (set at final commit)

## Infrastructure Summary

| Component | Details |
|-----------|---------|
| **Neon** | Project: `ai-revenue-living-travel` |
| | Region: `aws-ap-southeast-1` |
| | PostgreSQL: 17.10 |
| | Pooled endpoint verified |
| | Direct endpoint verified |
| **Modal** | App: `ai-revenue-living-travel-staging` |
| | URL: `https://padiemipu--ai-revenue-living-travel-staging-web.modal.run` |
| | Secret: `ai-revenue-living-travel-staging` (8 keys) |
| **Cloudflare Pages** | Project: `ai-revenue-living-travel` |
| | Production: `https://ai-revenue-living-travel.pages.dev` |
| | Stable branch preview: `https://ops-living-travel-external-s.ai-revenue-living-travel.pages.dev` |
| **Firebase** | Project: `ai-revenue-lab-identity` |
| | Web App: `living-travel-staging` |
| | Email/Password provider: enabled |
| | Authorized domains: production + stable branch preview + localhost |

## Verification Results

### 1. Neon PostgreSQL

- [x] Project created
- [x] PostgreSQL 17.10
- [x] Pooled endpoint verified
- [x] Direct endpoint verified

### 2. Modal Deployment

- [x] Secret created (8 keys)
- [x] App deployed
- [x] `/health` returns `{"status":"ok"}`
- [x] CORS: production origin allowed
- [x] CORS: stable branch preview origin allowed
- [x] CORS: unauthorized origin rejected (no ACAO header)
- [x] CORS: no wildcard

### 3. Cloudflare Pages

- [x] Project exists
- [x] Stable branch preview deployed
- [x] CSP headers correct (connect-src includes Modal + Firebase origins)
- [x] Staging page loads with correct Firebase config

### 4. Firebase

- [x] Web app created
- [x] Public config configured
- [x] Email/Password provider enabled
- [x] Authorized domains: production + stable branch preview + localhost

### 5. Browser Auth — Email/Password

- [x] Firebase Email/Password provider activated via Identity Toolkit API
- [x] Dedicated synthetic operator account created (Admin SDK)
- [x] Dedicated synthetic traveler account created (Admin SDK)
- [x] Credentials stored in `/root/.secrets/lt-staging-e2e-creds.json` (chmod 600, outside repo)
- [x] Staging UI updated: email/password form alongside Google login
- [x] Password input: `type=password`
- [x] No sign-up, password reset, or role selection UI
- [x] Auth errors: generic messages only
- [x] Operator email/password sign-in: `role=operator`
- [x] Traveler email/password sign-in (before claim): `role=none`
- [x] Traveler after invitation claim: `role=traveler`
- [x] Token not stored in custom localStorage/sessionStorage
- [x] Credentials not exposed in logs, DOM, or evidence
- [x] Google login retained for live smoke test (not automated)

### 6. Invitation Replay

| Step | Result |
|------|--------|
| Traveler A first claim | ✓ 200 |
| Same-UID replay | ✓ 400 `invitation_claim_failed` |
| Foreign-UID claim | ✓ 400 `invitation_claim_failed` |
| Raw code DB storage | ✓ not stored |
| Final identity mapping | ✓ exactly 1 non-revoked mapping |

### 7. Authorization Boundary

| Step | Result |
|------|--------|
| Traveler own preferences | ✓ 200 |
| Traveler own editions | ✓ 200 |
| Traveler → operator endpoint | ✓ 403 |
| Unmapped identity → traveler endpoint | ✓ 401 |
| Unmapped identity /me | ✓ role=none |
| Deactivated traveler API | ✓ 401 |
| Deactivated /me | ✓ role=none |
| Reactivated /me | ✓ role=traveler |

### 8. Feedback & Publication Workflow

| Step | Result |
|------|--------|
| Operator generate-first | ✓ 200, state=pending, gen=pending_review |
| Operator publish | ✓ 200, state=published |
| Traveler feedback (with directions) | ✓ 200 |
| Operator generate-second | ✓ 200 |
| Operator reject second | ✓ 200, state=rejected |
| Duplicate publish | ✓ 409 |
| Reject after publish | ✓ 409 |
| Duplicate reject | ✓ 409 |
| Publish after reject | ✓ 409 |
| Traveler sees published only | ✓ count=1, rejected not visible |

### 9. Cold-Start Persistence

- [x] Scale-to-zero confirmed (60s scaledown window)
- [x] New container cold start: ~8s response time
- [x] `/health` 200 after cold start
- [x] Migrations re-run successfully
- [x] Operator mapping persists
- [x] Traveler mapping persists
- [x] Consumed invitation not reusable
- [x] Traveler active status persists
- [x] Edition publication state persists
- [x] Feedback/edition relationship persists
- [x] Neon rows persist
- [x] No SQLite Volume
- [x] Modal logs: no secrets, DB URLs, or tokens exposed

### 10. Local Tests

- [x] Unit tests: 119 passed
- [x] Preview tests: 40 passed
- [x] Packaging OK
- [x] Secret scan: clean (no secrets in evidence or pages-preview)

## Code Changes

1. **modal_app.py**: Fix image build order (`.env()` before `add_local_dir`)
2. **config.js**: Real Firebase public web config + actual Modal API_BASE
3. **_headers**: CSP connect-src with exact Modal + Firebase origins
4. **firebase.js**: Add `signInWithEmailAndPassword` import and `signInWithEmail` export
5. **index.html**: Add Email/Password login form alongside Google login
6. **app-index.js**: Add email/password form handler (generic error messages, no credential logging)
7. **test_staging_contract.py**: Fix `EXPECTED_API_ORIGIN` to match actual Modal URL

## Completion Criteria Status

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Neon project created | ✓ |
| 2 | PostgreSQL 16+ database | ✓ (PG 17.10) |
| 3 | Pooled + direct verified | ✓ |
| 4 | Modal Secret created | ✓ |
| 5 | Modal app deployed | ✓ |
| 6 | /health returns ok | ✓ |
| 7 | CORS configured (exact origins, no wildcard) | ✓ |
| 8 | Cloudflare Pages project | ✓ |
| 9 | Staging frontend deployed (stable branch preview) | ✓ |
| 10 | Firebase web app created | ✓ |
| 11 | Email/Password provider enabled | ✓ |
| 12 | Browser email/password sign-in verified | ✓ |
| 13 | Invitation replay rejected | ✓ |
| 14 | Authorization boundary enforced | ✓ |
| 15 | Publication terminal transitions (409) | ✓ |
| 16 | Cold-start persistence verified | ✓ |
| 17 | Local tests pass | ✓ |
| 18 | Secret scan clean | ✓ |
| 19 | Draft PR created | ✓ |

**All completion criteria met.**
