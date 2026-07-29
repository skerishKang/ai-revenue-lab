# Business Authority Registry Audit

- **Audited main SHA:** `b24e2452928d8181f5f3f5ee7b5d2aee66ab1538`
- **Audit date:** 2026-07-29
- **Implementation branch:** `feat/portfolio-console-business-authority-280`
- **Related issue:** #280
- **Phase-gate authority:** #154 (permanent UI → UX → backend phase queue)

---

## 1. Business 1–55 coverage

| Range | Count | Classification basis |
|---|---:|---|
| 1–4 | 4 | Canonical: merged `BUSINESS_REGISTRY.md` entries |
| 5 | 1 | Proposed-number: Issue #99 (product-decision) open; registry update pending |
| 6 | 1 | Number-reconciliation-required: registry says reserved; backlog says proposed-number; conflicting |
| 7–12 | 6 | Proposed-number: PR #185 merged as canonical but BUSINESS_REGISTRY.md still shows reserved; conservative classification used per conflict rule |
| 13–14 | 2 | Canonical: merged BUSINESS_REGISTRY.md entries |
| 15 | 1 | Reserved: no product-decision issue exists; backlog candidate not canonical |
| 16–22 | 7 | Candidate: from BUSINESS_CANDIDATE_BACKLOG.md; no product-decision issue |
| 23–25 | 3 | Existing-project: separate repositories exist; no canonical numbering procedure completed |
| 26–35 | 10 | Candidate (spin-outs mapped to candidate): from backlog; no product-decision issues |
| 36 | 1 | Proposed-number: Issue #266 (product-decision), Draft PR #279 (Phase 1 UI) |
| 37 | 1 | Candidate: backlog spin-out; no product-decision issue confirmed |
| 38 | 1 | Proposed-number: Issues #267/#269 (product-decision), Draft PR #278 (Phase 1 UI) |
| 39 | 1 | Candidate: backlog spin-out; no product-decision issue confirmed |
| 40 | 1 | Candidate: branch exists but no PR or product-decision issue confirmed |
| 41 | 1 | Candidate: branch exists but no PR or product-decision issue confirmed |
| 42–43 | 2 | Candidate: backlog spin-outs; no product-decision issues |
| 44 | 1 | Existing-project: this IS the Portfolio Console itself |
| 45–55 | 11 | Candidate: backlog spin-outs/candidates; no product-decision issues |

**Total: 55** — exact ordered unique numbers 1 through 55. No duplicates, no gaps.

---

## 2. Authority classification counts

| Classification | Count |
|---|---|
| `canonical` | 6 (B01–B04, B13, B14) |
| `proposed-number` | 9 (B05, B07–B12, B36, B38) |
| `candidate` | 32 (B16–B22, B26–B35, B37, B39–B43, B45–B55) |
| `existing-project` | 4 (B23–B25, B44) |
| `reserved` | 1 (B15) |
| `number-reconciliation-required` | 1 (B06) |

---

## 3. Phase state counts (UI / UX / Backend)

### UI status
| State | Count |
|---|---|
| `UI_APPROVED` | 8 (B02, B03, B04, B09, B13, B14, B23, B44) |
| `IN_PROGRESS` | 10 (B01, B05, B06, B07, B08, B10, B11, B12, B36, B38) |
| `NOT_STARTED` | 35 (B16–B22, B25, B26–B35, B37, B39–B43, B45–B55) |
| `NOT_APPLICABLE` | 2 (B15, B24) |

### UX status
| State | Count |
|---|---|
| `IN_PROGRESS` | 1 (B23) |
| `NOT_STARTED` | 5 (B02, B03, B04, B13, B14) |
| `BLOCKED_BY_UI` | 37 (B01, B05, B06, B07, B08, B10, B11, B12, B16–B22, B25, B26–B41, B45–B55) |
| `NOT_APPLICABLE` | 3 (B09, B15, B24, B42–B44) |

### Backend status
| State | Count |
|---|---|
| `IMPLEMENTED` | 4 (B02, B03, B23, B24) |
| `IN_PROGRESS` | 1 (B14) |
| `DECISION_PENDING` | 1 (B13) |
| `FROZEN` | 37 (B01, B05, B06, B07, B08, B10, B11, B12, B16–B22, B25, B26–B41, B45–B55) |
| `NOT_APPLICABLE` | 4 (B04, B09, B15, B44) |

---

## 4. Authority conflicts

| Business | Conflict | Resolution |
|---|---|---|
| B06 (World Feed) | BUSINESS_REGISTRY.md says reserved-06; BUSINESS_CANDIDATE_BACKLOG.md says proposed-number; Issue #98 open | `number-reconciliation-required` — documented conflict, pending resolution |
| B07–B12 | PR #185 merged them as canonical; BUSINESS_REGISTRY.md still shows reserved | `proposed-number` (conservative) — PR #185 updated the code-based registry but the document wasn't updated |
| B15 | Candidate backlog suggests Global AI Newsroom; no product-decision issue; registry shows no assignment | `reserved` (conservative) — until product-decision issue exists |
| B36, B38 | Product-decision issues and UI PRs exist; backlog lists as candidate/spin-out | `proposed-number` — product-decision Issues #266/#267 and UI work elevate above candidate |

---

## 5. Removed stale claims

The following impressionistic progress percentages were removed from `businesses.js`:
- `progress: 82` (B01 Personal Edition)
- `progress: 100` (B02 Living Travel)
- `progress: 100` (B03 Living Fiction)
- `progress: 100` (B04 Living Learning)
- `progress: 72` (B05 Neighbor Market)
- `progress: 35` (B06 World Feed)
- `progress: 30` (B07 Personal Meaning Map)
- `progress: 25` (B08 Family Newspaper)
- `progress: 25` (B09 Personalized Children's Story)
- `progress: 25` (B10 Fan Magazine)
- `progress: 25` (B11 Language Learning Magazine)
- `progress: 25` (B12 Creator Mini-Media)
- `progress: 100` (B13 Personal Video Archive)
- `progress: 50` (B14 Korean AI Platform)
- `progress: 0` (B15 Unassigned)

These percentages were arbitrary — not derived from a verifiable milestone task list. Per phase-gate policy (#154), separate UI/UX/backend states replace them. The Project Directory milestone-progress system in `projects.js` remains intact and was not modified.

Also removed: The old `state` filter (running/review/planning/reserved) was replaced by the `numberAuthority` filter with proper vocabulary. The old `biz-state-filter` select was replaced by `biz-auth-filter`.

---

## 6. Entries lacking product-decision issues

The following entries have no product-decision issue:
- B06 (number-reconciliation-required; Issue #98 is a product-decision issue for World Feed but its number status is unresolved)
- B15 (reserved)
- B16–B22 (candidate)
- B26–B35 (candidate)
- B37 (candidate)
- B39 (candidate)
- B40–B43 (candidate)
- B45–B55 (candidate)

These are marked with `productDecisionIssue: null` in the record.

---

## 7. Entries lacking explicit phase issues

The following entries have no dedicated Phase 1 UI, Phase 2 UX, or backend issues:
- B15 (reserved)
- B16–B22 (candidate)
- B26–B35 (candidate)
- B37 (candidate)
- B39 (candidate)
- B40–B43 (candidate)
- B45–B55 (candidate)

---

## 8. Entries without verified surface URL

The following entries have `surfaceUrl: null`:
- B05 (B06, B07, B08, B09, B10, B11, B12) — no verified deployment
- B15, B16–B22, B25, B26–B35, B36, B37, B38, B39, B40, B41, B42, B43, B45–B55

---

## 9. Rationale for removing arbitrary percentages

Per Issue #280 requirements:
> "Remove impressionistic Business progress percentages unless there is an explicit, verifiable milestone task list and calculation basis."
> "Do not convert UI/UX/backend phases into a fake combined completion percentage."

The previous `progress` values (82, 100, 72, 35, 30, 25, 50, 0) were not derived from a phase-gate task checklist. The Project Directory in `projects.js` uses task-based calculation only for projects with `milestoneStatus: "defined"`. This Business Registry now uses separate UI/UX/backend states instead of a single percentage.

---

## 10. Live-sync credential work NOT performed

As specified in #280 boundary:
- ✅ No GitHub App created or installed
- ✅ No Cloudflare KV namespace created
- ✅ No encrypted secrets configured
- ✅ No GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, or GITHUB_APP_PRIVATE_KEY_PKCS8 set
- ✅ No live-sync activation
- ✅ No arbitrary repository query functionality
- ✅ No GitHub write automation

The credential-free fallback architecture from PR #193 remains intact and unmodified.

---

## 11. Files modified by this PR

All changes are under `apps/portfolio-console/**`:
- `businesses.js` — complete rewrite with normalized B1–55 records
- `app.js` — updated for new fields and authority/phase-state filters
- `styles.css` — added phase-state and authority badge styles
- `index.html` — new filter controls for authority, UI, UX, backend
- `tests/test_business_registry.py` — updated for B1–55 coverage
- `tests/test_static_console.py` — updated for new structure
- `docs/BUSINESS_AUTHORITY_AUDIT_2026-07-29.md` — this document
