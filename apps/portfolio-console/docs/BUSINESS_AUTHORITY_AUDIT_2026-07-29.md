# Business Authority Registry Audit

- **Audited main SHA:** `b24e2452928d8181f5f3f5ee7b5d2aee66ab1538`
- **Audit date:** 2026-07-29
- **Implementation branch:** `feat/portfolio-console-business-authority-280`
- **Implementation PR:** #282 (OPEN Draft — correction pass)
- **Related issue:** #280
- **Phase-gate authority:** #154 (permanent UI → UX → backend phase queue)

---

## 1. Audit methodology

Each Business 1–55 was classified by searching GitHub Issues, PRs, repository workspaces, and authority documents in this order (per Issue #280):

1. `docs/portfolio/BUSINESS_REGISTRY.md` — merged canonical entries
2. Explicit product-decision Issue
3. Phase 1 UI Issue / Phase 2 UX Issue / backend authorization Issue
4. PR body, current state, merge status, Web CTO verdict comments
5. `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`
6. Repository-local workspace and verified hosting evidence

Lower-priority sources never override higher-priority authorities.

---

## 2. Business 1–55 coverage

**Total: 55** — exact ordered unique numbers 1 through 55. No duplicates, no gaps.

| Range | Count | Classification | Basis |
|---|---:|---|---|
| 1–4 | 4 | canonical | Merged BUSINESS_REGISTRY.md entries |
| 5 | 1 | proposed-number | Issue #99 (product-decision) open; registry update pending |
| 6 | 1 | number-reconciliation-required | Registry says reserved; backlog says proposed-number |
| 7–12 | 6 | proposed-number | PR #185 merged as canonical but registry doc not updated |
| 13–14 | 2 | canonical | Merged BUSINESS_REGISTRY.md entries |
| 15 | 1 | proposed-number | Issue #187 (product-decision) + #188 (Phase 1 UI) open |
| 16–22 | 7 | proposed-number | Issues #189, #191, #196, #198, #200, #204, #222 (product) + Phase 1 UI issues |
| 23–25 | 3 | existing-project | Separate repositories exist; no canonical numbering procedure |
| 26–31 | 6 | proposed-number | Issues #226, #230, #234, #236, #240, #241 (product) + Phase 1 UI issues |
| 32–35 | 4 | proposed-number | Issues #246, #247, #252, #253 (product) + Phase 1 UI issues |
| 36–43 | 8 | proposed-number | Issues #266, #259, #267, #261, #270, #271, #274, #275 (product) + Phase 1 UI issues |
| 44 | 1 | existing-project | This IS the Portfolio Console itself |
| 45–55 | 11 | candidate | From BUSINESS_CANDIDATE_BACKLOG.md; no product-decision issues confirmed |

---

## 3. Number-authority classification counts

Generated from runtime records via `ARL_VOCABULARY.generateSummary()` — all sums = 55.

| Classification | Count |
|---|---|
| canonical | 6 |
| proposed-number | 33 |
| candidate | 11 |
| existing-project | 4 |
| reserved | 0 |
| number-reconciliation-required | 1 |
| **Sum** | **55** |

---

## 4. Phase state counts

Generated from runtime records — all sums = 55.

### UI status
| State | Count |
|---|---|
| UI_APPROVED | 8 |
| IN_PROGRESS | 34 |
| NOT_STARTED | 11 |
| NOT_APPLICABLE | 2 |
| **Sum** | **55** |

### UX status
| State | Count |
|---|---|
| IN_PROGRESS | 1 |
| NOT_STARTED | 6 |
| BLOCKED_BY_UI | 45 |
| NOT_APPLICABLE | 3 |
| **Sum** | **55** |

### Backend status
| State | Count |
|---|---|
| IMPLEMENTED | 4 |
| IN_PROGRESS | 1 |
| DECISION_PENDING | 1 |
| FROZEN | 46 |
| NOT_APPLICABLE | 3 |
| **Sum** | **55** |

---

## 5. Product-decision issue mapping

| Business | Product-decision Issue | Phase 1 UI Issue | Current PR |
|---|---:|---:|---:|---:|
| 15 | #187 | #188 | #194 |
| 16 | #189 | #190 | #195 |
| 17 | #191 | #192 | #233 |
| 18 | #196 | #197 | #203 |
| 19 | #198 | #199 | #202 |
| 20 | #200 | #201 | #206 |
| 21 | #204 | #205 | #207 |
| 22 | #222 | #223 | #224 |
| 26 | #226 | #227 | #228 |
| 27 | #230 | #231 | #232 |
| 28 | #234 | #235 | #239 |
| 29 | #236 | #237 | #238 |
| 30 | #240 | #242 | #245 |
| 31 | #241 | #243 | #244 |
| 32 | #246 | #248 | #251 |
| 33 | #247 | #249 | #250 |
| 34 | #252 | #254 | #258 |
| 35 | #253 | #255 | #257 |
| 36 | #266 | #268 | #279 |
| 37 | #259 | #260 | #264 |
| 38 | #267 | #269 | #278 |
| 39 | #261 | #262 | #265 |
| 40 | #270 | #272 | #281 |
| 41 | #271 | #273 | #283 |
| 42 | #274 | #276 | — (branch only) |
| 43 | #275 | #277 | #284 |

---

## 6. Corrected false claims from previous audit

The following errors from the first implementation pass have been corrected:

| Previous claim | Correction |
|---|---|
| B15: no product-decision issue → reserved | B15 has Issue #187 (product-decision) + #188 (UI) → proposed-number |
| B16–B22: candidate, no product-decision issues | All have product-decision Issues (#189–#222) → proposed-number |
| B26–B35: candidate, no product-decision issues | B26–B35 have product-decision Issues (#226–#253) → proposed-number |
| B37/B39: no product-decision issue confirmed | B37 has #259, B39 has #261 → proposed-number |
| B40/B41: branch exists but no Issue confirmed | B40 has #270, B41 has #271 → proposed-number |
| B42/B43: no product-decision issues | B42 has #274, B43 has #275 → proposed-number |
| Authority counts sum to 53 | Now correctly sums to 55 (6+33+11+4+0+1 = 55) |
| UX counts sum to 45 | Now correctly sums to 55 |
| Backend counts sum to 45 | Now correctly sums to 55 |

---

## 7. Removed stale claims

All 15 impressionistic progress percentages were removed from `businesses.js`:
- `progress: 82` (B01), `100` (B02), `100` (B03), `100` (B04)
- `progress: 72` (B05), `35` (B06)
- `progress: 30` (B07), `25` (B08), `25` (B09), `25` (B10), `25` (B11), `25` (B12)
- `progress: 100` (B13), `50` (B14), `0` (B15)

These percentages were arbitrary — not derived from a verifiable milestone task list. The Project Directory milestone-progress system in `projects.js` remains intact.

---

## 8. Entries without verified surface URL

- B05–B12, B15–B22, B25–B43, B45–B55: `surfaceUrl: null` (no verified deployment)
- B03: `surfaceUrl: null` (previous deployment now 404)

---

## 9. Live-sync credential work NOT performed

- ✅ No GitHub App created or installed
- ✅ No Cloudflare KV namespace created
- ✅ No encrypted secrets configured
- ✅ No GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, or GITHUB_APP_PRIVATE_KEY_PKCS8 set
- ✅ No live-sync activation
- ✅ No arbitrary repository query functionality
- ✅ No GitHub write automation

The credential-free fallback architecture from PR #193 remains intact and unmodified.

---

## 10. Files modified by this correction pass

All changes under `apps/portfolio-console/**`:

| File | Change |
|---|---|
| `business-authority-vocabulary.js` | **New** — constants + `rec()` factory + `generateSummary()` |
| `businesses.js` | Rewritten — only data records, corrected classifications |
| `business-authority-summary.js` | **New** — thin derived view from runtime records |
| `app.js` | Minor update — added `summary` reference |
| `index.html` | Updated — added `?v=ba-v20260729-1` tokens, new script tags |
| `styles.css` | Unchanged from previous pass |
| `tests/test_business_registry.py` | Rewritten — product-decision mappings, invariant sums |
| `tests/test_static_console.py` | Minor update |
| `docs/BUSINESS_AUTHORITY_AUDIT_2026-07-29.md` | This document — rewritten with correct data |
