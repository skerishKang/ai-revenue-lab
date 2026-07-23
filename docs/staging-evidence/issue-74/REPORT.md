# Living Travel External Staging Evidence (Issue #74)

**Date**: 2026-07-24
**PR**: #88 (Draft)
**Branch**: `ops/living-travel-external-staging-74`

## Infrastructure Summary

| Component | Details |
|-----------|---------|
| **Neon** | Project: `ai-revenue-living-travel` (ID: `rapid-wind-02796175`) |
| | Region: `aws-ap-southeast-1` |
| | PostgreSQL: 17.10 |
| | Database: `living_travel` |
| | Pooled: `ep-damp-king-aznd7yar-pooler.c-3.ap-southeast-1.aws.neon.tech` |
| | Direct: `ep-damp-king-aznd7yar.c-3.ap-southeast-1.aws.neon.tech` |
| **Modal** | App: `ai-revenue-living-travel-staging` |
| | URL: `https://padiemipu--ai-revenue-living-travel-staging-web.modal.run` |
| | Secret: `ai-revenue-living-travel-staging` (8 keys) |
| **Cloudflare Pages** | Project: `ai-revenue-living-travel` |
| | Domain: `ai-revenue-living-travel.pages.dev` |
| | Staging preview: `https://5728e0c2.ai-revenue-living-travel.pages.dev` |
| **Firebase** | Project: `ai-revenue-lab-identity` |
| | Web App: `living-travel-staging` (appId: `1:864728700692:web:01dc5a0fffb78bf4801401`) |
| | Authorized domains: `ai-revenue-living-travel.pages.dev`, `5728e0c2.ai-revenue-living-travel.pages.dev`, `localhost` |

## Verification Results

### 1. Neon PostgreSQL

- [x] Project created: `ai-revenue-living-travel`
- [x] Database created: `living_travel`
- [x] Pooled connection verified: `SELECT version(), current_database()` → PostgreSQL 17.10, living_travel
- [x] Direct connection verified: `SELECT version(), current_database()` → PostgreSQL 17.10, living_travel

### 2. Modal Deployment

- [x] Secret created: `ai-revenue-living-travel-staging` (8 keys)
- [x] App deployed: `ai-revenue-living-travel-staging`
- [x] `/health` returns `{"status":"ok"}`
- [x] CORS verified for `https://ai-revenue-living-travel.pages.dev`
- [x] CORS verified for `https://5728e0c2.ai-revenue-living-travel.pages.dev`

### 3. Cloudflare Pages

- [x] Project exists: `ai-revenue-living-travel`
- [x] Staging deployed: `https://5728e0c2.ai-revenue-living-travel.pages.dev`
- [x] CSP headers correct (connect-src includes Modal origin)
- [x] Staging page loads with correct Firebase config

### 4. Firebase

- [x] Web app created: `living-travel-staging`
- [x] Public config retrieved (apiKey, authDomain, projectId, etc.)
- [x] Authorized domains configured

### 5. Synthetic E2E

| Step | Result |
|------|--------|
| Operator sign-in | ✓ `/api/v1/me` → `role: "operator"` |
| List travelers | ✓ `/api/v1/operator/travelers` → `{"travelers":[]}` |
| Create traveler | ✓ `trav_Kz6psGbRjofUQJqV9iwwvg` created |
| Create invitation | ✓ Invitation code generated |
| Traveler sign-in | ✓ Firebase custom token → ID token |
| Claim invitation | ✓ `/api/v1/invitations/claim` → `traveler_id` returned |
| Traveler /me | ✓ `role: "traveler"`, `traveler_id` present |
| Get preferences | ✓ Preferences returned |
| Get editions | ✓ Empty list (no published editions) |
| Generate edition | ✓ `ed_JoqTHSAWv7zOcx8kR39lkw` created (pending_review) |
| Deactivate traveler | ✓ `status: "deleted"` |
| Traveler /me after deactivation | ✓ `role: "none"`, `traveler_id: null` |
| Traveler API after deactivation | ✓ 401 unauthorized |
| Reactivate traveler | ✓ `status: "active"` |
| Traveler /me after reactivation | ✓ `role: "traveler"`, `traveler_id` present |
| Persistence check | ✓ Edition still exists (1 edition via operator view) |

### 6. Local Tests

- [x] 432 passed, 19 skipped (PG-specific tests skipped without local PG)
- [x] Secret scan: no secrets in committed files
- [x] Packaging check: `from app.factory import create_app` OK

## Code Changes

1. **modal_app.py**: Fix image build order (`.env()` before `add_local_dir`)
2. **config.js**: Real Firebase public web config + actual Modal API_BASE
3. **_headers**: CSP connect-src updated to actual Modal origin

## Synthetic Test Accounts

| Role | Email | UID |
|------|-------|-----|
| Operator | `staging-operator@synthetic.test` | `4QSWYIXSRVdskkc1IffLZWowMlM2` |
| Traveler | `staging-traveler@synthetic.test` | `mRthgc78bfeldr7ZEACB8QVXjGC3` |

**Note**: These are synthetic test accounts created for staging verification. No real personal data was used.

## Completion Criteria Status

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Neon project created | ✓ |
| 2 | PostgreSQL 16+ database | ✓ (PG 17.10) |
| 3 | Pooled + direct URLs verified | ✓ |
| 4 | Modal Secret created | ✓ |
| 5 | Modal app deployed | ✓ |
| 6 | /health returns ok | ✓ |
| 7 | CORS configured | ✓ |
| 8 | Cloudflare Pages project | ✓ |
| 9 | Staging frontend deployed | ✓ |
| 10 | Firebase web app created | ✓ |
| 11 | Authorized domains configured | ✓ |
| 12 | Operator bootstrap | ✓ |
| 13 | Synthetic E2E passed | ✓ |
| 14 | Local tests pass | ✓ |
| 15 | Secret scan clean | ✓ |
| 16 | Draft PR created | ✓ |

**All 16 completion criteria met.**
