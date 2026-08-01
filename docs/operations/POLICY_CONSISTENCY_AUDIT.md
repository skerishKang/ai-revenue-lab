# Portfolio Policy Consistency Audit

- Status: repository-wide governance audit for PR #365
- Authority: `PORTFOLIO_PRODUCT_QUALITY_AUDIT.md`, `OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md`
- Result: `REPOSITORY_POLICY_CONFLICTS=0`
- External control-plane status: `GITHUB_GOVERNANCE_REVIEW_REQUIRED`

## Audit baseline

- Audit date: 2026-08-01
- Audit branch: `policy/portfolio-demo-mvp-quality-overhaul`
- Starting exact head: `668b8d7c4fb08be1bfe1e879391e9017caab9c9e`
- Base: `main` `17825a76f09716231ccef6e682ac439a51e021a8`

## Inspected repository paths

```text
README.md
.github/**
docs/operations/**
docs/portfolio/**
apps/**/README.md
apps/**/docs/**
reference/**/README.md
reference/**/REFERENCE_NOTES.md
active policy / playbook / operating guidance documents
```

## Search patterns

```text
UI_ONLY | UX_NOT_STARTED | BACKEND_FROZEN | backend frozen
UI → UX → backend | UI.*UX.*backend
NOT_DEPLOYED_PENDING_UI_APPROVAL | Preview.*disabled
merge.*deployment action | Deployment: NONE | Not independently validated
PIXEL_VISUAL_QA_PENDING | WEB_CTO_.*PENDING
novice | 초보 | generic warning | generic legal | 법률 검토 | 전문가 검토
REFERENCE_NOTES | IMAGE_SOURCES | image-led | SVG | visual quality
UI_APPROVED | TECHNICAL_UI_PASS | INVESTOR_DEMO_PASS | MARKET_REFERENCE_PASS
```

## Classification method

Each repository match was classified as one of:

```text
ACTIVE_CONFLICT
BUSINESS_SPECIFIC_VALID
HISTORICAL_VALID
AMBIGUOUS_NEEDS_CLARIFICATION_IN_DOC
NO_ACTION
```

`reference/**` Phase 1 records and recorded per-Business phase history were treated as business-specific / historical and preserved unchanged.

## Repository ACTIVE_CONFLICT list before repair

| # | file | conflict | disposition |
|---|---|---|---|
| 1 | `README.md` | Default execution loop described merge-to-Production as the only deployment action and stated "Preview and staging are disabled by default" | Rewritten to reference the two-lane deployment policy |
| 2 | `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md` | Current mode `UI_ONLY`; mandatory UI→UX→backend sequence | Updated to `MVP_AND_VISUAL_UPGRADE` and current evidence stages |
| 3 | `docs/portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md` | Deployment doctrine read as merge-only | Clarified to name both deployment lanes |
| 4 | `apps/portfolio-console/README.md` | Preview-disabled statement lacked two-lane context | Clarified canonical default and explicit demo-lane authority |

## External GitHub control-plane finding

The repository-only scan did not inspect mutable GitHub Issue bodies. Independent Web CTO review found that permanent umbrella Issue #154 still declared the superseded `UI_ONLY`, mandatory UI→UX→backend, and backend-frozen model as current policy.

This is an external governance conflict, not a repository-file conflict.

Required resolution:

```text
Issue #154 body and title updated to MVP_AND_VISUAL_UPGRADE
old UI_ONLY contract marked superseded historical policy
PR #365 exact policy head recorded during transition
Issue #366 linked as the portfolio-wide audit and renewal program
```

Repository validators cannot by themselves prove mutable GitHub Issue-body state. Final governance acceptance therefore requires an authenticated external control-plane check in addition to `scripts/validate-portfolio-governance.py`.

## Documents modified and reasons

```text
README.md
  - Deployment section aligned to the two-lane policy.

docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md
  - Portfolio mode and evidence-stage vocabulary updated.

docs/portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md
  - Deployment doctrine clarified to name both lanes.

apps/portfolio-console/README.md
  - Project preview default clarified against the two-lane policy.
```

## Preserved historical / business-specific items

```text
reference/business-35/36/37/39-*-v1/README.md + index.html — per-Business Phase 1 UI_ONLY records
reference/business-06-world-feed-v1/README.md — Business 6 Phase 1 record
apps/portfolio-console/functions/_lib/business-verdict-parser.js — recorded verdict vocabulary parser
docs/operations/UI_UX_BACKEND_PHASE_GATES.md §13 — explicitly superseded defaults
```

## New policy linkage map

```text
docs/operations/README.md (hub)
├── OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md
├── UI_UX_BACKEND_PHASE_GATES.md
├── NEW_BUSINESS_UI_FIRST_PLAYBOOK.md
├── COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md
├── BACKEND_MVP_OPERATING_POLICY.md
├── PORTFOLIO_PRODUCT_QUALITY_AUDIT.md
└── DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md
```

Validator: `scripts/validate-portfolio-governance.py`

## Final verdict

```text
REPOSITORY_POLICY_CONFLICTS=0
EXTERNAL_GITHUB_GOVERNANCE_CHECK_REQUIRED
HISTORICAL_RECORDS_PRESERVED
BUSINESS_SPECIFIC_PHASE_RECORDS_PRESERVED
OWNER_EXPERTISE_POLICY_LINKED
COMPETITIVE_VISUAL_POLICY_LINKED
BACKEND_MVP_POLICY_LINKED
DEPLOYMENT_LANES_ALIGNED
PORTFOLIO_AUDIT_POLICY_LINKED
```
