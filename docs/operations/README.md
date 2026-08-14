# Operations Documents

Canonical operating entry points:

- `AI_DEVELOPMENT_OPERATING_POLICY.md` — role-separated AI development, exact-revision review, and flexible product-evidence model.
- `WORKFLOW_STATUS_MODEL.md` — implementation, validation, CTO readiness, owner decision, merge, and Production statuses.
- `EVIDENCE_REQUIREMENTS.md` — exact-SHA implementation/validation/review evidence requirements.
- `UI_UX_BACKEND_PHASE_GATES.md` — separate UI/UX/backend/runtime verdicts without a mandatory sequential ceremony.
- `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — legacy-named product-evidence playbook; UI-first is one valid lane when visual desirability is the uncertainty, not the repository-wide default.
- `BACKEND_MVP_OPERATING_POLICY.md` — smallest useful service-led/local/live backend/runtime evidence modes.
- `EXTERNAL_DEVELOPMENT_PROJECTS_POLICY.md` — external/successor Businesses are lineage/link authority inside AI Revenue Lab, not duplicate internal implementation targets.
- `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` — Git-connected automatic Production execution, acceptance, and reviewed recovery.
- `LIVE_PRODUCTION_UI_REVIEW_POLICY.md` — live Production visual-review contract where that Business-specific policy applies.
- `../portfolio/BUSINESS_REGISTRY.md` — canonical Business numbering authority.
- `../portfolio/BUSINESS_EXPANSION_LINEAGE.md` — external/successor implementation-location authority.
- `../portfolio/BUSINESS_CANDIDATE_BACKLOG.md` — idea-preservation backlog.

Templates:

- `templates/CTO_WORK_ORDER.md`
- `templates/WEB_DEVELOPER_REPORT.md`
- `templates/LOCAL_VALIDATION_REPORT.md`
- `templates/CTO_FINAL_REVIEW.md`

## Current portfolio operating mode

```text
MVP_AND_VISUAL_UPGRADE
ROLE_SEPARATED_EVIDENCE
NO_MANDATORY_UI_UX_BACKEND_SEQUENCE
```

The current repository does **not** freeze all new work at UI-only scope. The Web CTO selects the smallest product-evidence slice needed to answer the current uncertainty.

Examples:

- visual desirability uncertain → `COMPETITIVE_DEMO` / UI-heavy scope;
- task journey uncertain → UX prototype/vertical slice;
- demand can be tested manually → `SERVICE_LED_PILOT`;
- local model/indexing is the product → `LOCAL_RUNTIME`;
- a real API/database/provider is the key uncertainty → `LIVE_VERTICAL_SLICE`;
- existing demand requires reliability/billing/security → `COMMERCIAL_HARDENING`.

UI, UX, backend/runtime, security, market-reference, investor-demo, commercial, deployment, and owner-visual decisions stay distinct. Starting backend early does not imply backend acceptance; a polished UI does not imply UX acceptance; a deployed page does not imply product or revenue validation.

## Role and independence rule

One actor may perform multiple non-independent stages, but the same actor must not claim both implementation and independent Local Validation for the same revision.

Implementation self-checks are useful and should be recorded accurately. They do not become independent evidence by changing the label.

## Deployment default

For Git-connected projects, follow `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`:

```text
validated exact head
→ authorized expected-head merge
→ configured Git-connected Production deployment
→ Production acceptance
→ reviewed fix/revert recovery when necessary
```

Preview/staging/manual deployment is not implicitly authorized by this operating model.

## Owner visual review

The Web CTO independently rejects objective defects such as overflow, clipping, unreadable contrast, broken hierarchy, failed controls, responsive breakage, or runtime errors.

When a specific work contract reserves aesthetic/taste approval to the owner, the CTO does not infer `OWNER_UI_APPROVED`. When the owner explicitly delegates design selection to the CTO, record the decision as a CTO-delegated product decision.

## Permanent queue

Issue #154 remains the portfolio queue while AI Revenue Lab continues creating, revisiting, validating, or commercializing Businesses. Child work may close independently without closing the portfolio queue.
