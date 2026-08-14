# New Business Product-Evidence Playbook

- Status: portfolio operating playbook
- Legacy filename retained for link compatibility
- Owner: Web CTO
- Authority: Issue #148 + current portfolio governance
- Phase/evidence policy: `UI_UX_BACKEND_PHASE_GATES.md`
- Backend policy: `BACKEND_MVP_OPERATING_POLICY.md`
- Deployment policy: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`
- Portfolio intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`
- Candidate backlog: `../portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

## 1. Purpose

New or revived Businesses should move to the **smallest credible product evidence** rather than mechanically producing a UI prototype first.

UI-first remains a strong option when the primary uncertainty is visual identity or desirability. It is no longer the repository-wide mandatory sequence.

Possible first slices include:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
```

## 2. Product framing

Before implementation, establish:

- proposed/canonical Business number and stable slug;
- Korean/English name;
- one-sentence product promise;
- target user and use moment;
- primary result/success event;
- overlap and boundary with existing Businesses;
- external/successor implementation boundary;
- current evidence question;
- explicit non-goals.

Do not create an internal workspace for a Business whose canonical lineage says external/successor implementation.

## 3. Choose the first evidence lane

### Visual/competitive demo

Use when the problem is “would anyone want or understand this product?”

Recommended evidence:

- 3–5 product references;
- screen-level pattern analysis;
- repository-local, licensed/owned/generated assets as appropriate;
- representative desktop/mobile states;
- one product-specific motion where useful;
- direct browser visual review.

Avoid generic AI card walls, decorative dashboards, meaningless gradients, or unrelated stock imagery.

### UX / interactive vertical slice

Use when the primary uncertainty is the workflow.

Include the shortest useful journey plus the loading/error/recovery/accessibility states that determine usability.

### Service-led pilot

Use when a person can manually perform bounded work behind the product surface faster than building automation.

Record operator steps, response-time promise, quality control, workload ceiling, data handling, price hypothesis, and automation candidates.

### Local/runtime slice

Use when privacy, indexing, local models, file processing, hardware, or OS integration is the product question.

### Live backend/provider slice

Use when a real database/API/provider/auth path is the product uncertainty. Keep it narrow, observable, reversible, and cost-bounded.

## 4. Reference and asset policy

When visual references are relevant:

- study multiple products rather than cloning one;
- record adopted/rejected patterns;
- keep third-party brand assets/reference screenshots out of Production unless rights permit;
- store Production assets locally where possible;
- record source/license/usage basis for external assets;
- design Korean-first unless the Business contract says otherwise.

## 5. Workspace policy

A `reference/business-XX-.../` workspace is appropriate for bounded visual/product evidence when no runtime workspace is authorized.

An `apps/<slug>/` workspace is appropriate when a real product/runtime implementation is authorized.

Workspace existence does not by itself create canonical numbering, owner approval, backend authorization, or Production authority.

## 6. Role allocation

### Web CTO

- verifies numbering/lineage/product boundary;
- selects the evidence lane and exact scope;
- defines quality/safety/acceptance criteria;
- reviews exact-head evidence;
- rejects objective UI/UX/runtime defects;
- records technical readiness and remaining owner decisions.

### Web Developer

- implements the fixed contract;
- runs implementation self-checks;
- reports exact revision and limitations;
- does not convert self-check into independent validation.

### Independent Local Validator

Use when the work contract requires independent browser/OS/hardware/local-provider validation. The validator must not be the implementation actor for the same revision.

## 7. Visual quality standard

A technically valid UI may still fail product review.

Assess separately:

```text
TECHNICAL_UI_PASS
VISUAL_QUALITY_PASS
MARKET_REFERENCE_PASS
MOBILE_PASS
```

For user-facing products, inspect the real rendered screen. Automated checks alone do not prove hierarchy, desirability, readability, or Korean typography quality.

## 8. Backend decision

Do not freeze backend by default and do not build it for ceremony.

Choose the smallest mode that proves the evidence goal:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

See `BACKEND_MVP_OPERATING_POLICY.md`.

## 9. Publication and deployment

UI/UX/backend approval does not automatically authorize merge or Production.

For Git-connected targets, follow `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`. Wrong-project or automatically generated Preview deployments are never evidence for the intended Business.

## 10. Completion

A work item completes when the selected evidence question is answered with exact-revision evidence and the next product decision is explicit.

Completion is not measured by number of screens, files, agents, or deployments.
