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
| | Authorized domains: production + stable branch preview + localhost |

## Verification Results

### 1. Neon PostgreSQL

- [x] Project created: `ai-revenue-living-travel`
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

- [x] Project exists: `ai-revenue-living-travel`
- [x] Stable branch preview deployed
- [x] CSP headers correct (connect-src includes Modal origin)
- [x] Staging page loads with correct Firebase config

### 4. Firebase

- [x] Web app created: `living-travel-staging`
- [x] Public config configured
- [x] Authorized domains: production + stable branch preview

### 5. Browser Firebase Verification

- [x] Firebase SDK loads from pinned gstatic version
- [x] Google sign-in popup succeeds (operator account)
- [x] Google sign-in popup succeeds (traveler account)
- [x] No authorized-domain errors
- [x] No CSP errors in browser console
- [x] ID token not written to custom localStorage/sessionStorage

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

- [x] 432 passed, 19 skipped
- [x] Preview tests pass
- [x] Packaging OK
- [x] Secret scan clean

## Code Changes

1. **modal_app.py**: Fix image build order (`.env()` before `add_local_dir`)
2. **config.js**: Real Firebase public web config + actual Modal API_BASE
3. **_headers**: CSP connect-src updated to actual Modal origin

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
| 11 | Authorized domains configured | ✓ |
| 12 | Operator bootstrap | ✓ |
| 13 | Browser Google sign-in verified | ✓ |
| 14 | Invitation replay rejected | ✓ |
| 15 | Authorization boundary enforced | ✓ |
| 16 | Publication terminal transitions (409) | ✓ |
| 17 | Cold-start persistence verified | ✓ |
| 18 | Local tests pass | ✓ |
| 19 | Secret scan clean | ✓ |
| 20 | Draft PR created | ✓ |

**All completion criteria met.**
