# External Portfolio Projects

- Status: portfolio visibility authority for unnumbered external projects
- Numbering authority: `docs/portfolio/BUSINESS_REGISTRY.md`
- Related lineage authority: `docs/portfolio/BUSINESS_EXPANSION_LINEAGE.md`
- Owner decision: 2026-09-01

## Purpose

Some products should be visible in the AI Revenue Lab portfolio even when they do not yet require a canonical BI/Business number.

This document records those projects without implying that a BI number has been assigned. It complements, but does not replace, `BUSINESS_REGISTRY.md`.

Use this document when all of the following are true:

```text
PORTFOLIO_VISIBILITY_REQUIRED = YES
BI_NUMBER_REQUIRED = NO_OR_NOT_YET
EXTERNAL_SOURCE_OF_TRUTH_EXISTS = YES
INTERNAL_APP_PLACEHOLDER_NOT_AUTHORIZED = YES
```

## Rules

- Do not assign a canonical BI number from this document.
- Do not create an `apps/<project>/` or `reference/business-XX-*` placeholder merely because a project appears here.
- Do not reuse or conflict with numbered Businesses in `BUSINESS_REGISTRY.md`.
- If the owner later requests BI numbering, follow the registry number assignment procedure.
- External repositories remain their own source of truth unless a future migration decision says otherwise.

## Projects

| Portfolio ID | Project | Korean name | Source of truth | Portfolio status | Public surface | Number state | Evidence |
|---|---|---|---|---|---|---|---|
| `external:fmindex` | FMIndex | 펨코지수 | `skerishKang/fmindex` | `paused`; cleanly closed for now | `https://fmindex.pages.dev/` | unnumbered external portfolio project | `main @ 7f70a735b7c49f7e289a0bfa5f63d63255d3e5cc`; `ci` required; open PR count 0; remote branch cleanup complete |
| `external:ipu-ai-firewall` | IPU AI Firewall | IPU AI 방화벽 | `skerishKang/24-1-ipu-ai-security-filter` | `owner_demo_preparation`; local MVP and commercialization-prep docs complete | none approved yet | unnumbered external portfolio project; possible future Business-number decision | `main @ 7389e5e6d4b2a3cae19e3d926e8e631e4a760190`; Issues #105-#117 closed; PRs #110/#111/#112/#113/#115/#118/#119 merged; open PR/issue count 0 at registration |

## FMIndex boundary

FMIndex / 펨코지수 is a KOSPI + FMKorea community sentiment market-assistance index.

Current evidence snapshot:

```text
REPOSITORY = skerishKang/fmindex
CANONICAL_MAIN = 7f70a735b7c49f7e289a0bfa5f63d63255d3e5cc
MAIN_PROTECTED = true
REQUIRED_CI = ci
OPEN_PR_COUNT = 0
REMOTE_BRANCHES = main only
CLOUDFLARE_GIT_CONNECTED_PRODUCTION_BRANCHES = main
LIFECYCLE = paused / cleanly closed for now
```

Portfolio treatment:

```text
BI_NUMBER_REQUIRED = NO
PORTFOLIO_VISIBILITY_REQUIRED = YES
NUMBER_AUTHORITY = unnumbered-external
PORTFOLIO_CLASS = external
BOUNDARY_KIND = external-portfolio-project
DO_NOT_CREATE_INTERNAL_APP_PLACEHOLDER = YES
DO_NOT_FORCE_NUMBER_ASSIGNMENT = YES
```

A future numbered promotion may happen only through a dedicated GitHub Issue, duplicate/conflict search, reviewed PR, and explicit owner decision.

## IPU AI Firewall boundary

IPU AI Firewall / IPU AI 방화벽 is an owner-demo-stage AI safety workbench for preparing sensitive text, document, and short-audio inputs before using external generative AI.

Current product scope:

```text
REPOSITORY = skerishKang/24-1-ipu-ai-security-filter
CANONICAL_MAIN_AT_REGISTRATION = 7389e5e6d4b2a3cae19e3d926e8e631e4a760190
LIFECYCLE = owner_demo_preparation
PUBLIC_SURFACE = none approved yet
OPEN_PR_COUNT_AT_REGISTRATION = 0
OPEN_ISSUE_COUNT_AT_REGISTRATION = 0
REMOTE_BRANCHES_AT_REGISTRATION = main + B63 evidence branches only
```

Current completed evidence:

```text
BRANCH_CLEANUP = completed under IPU Issue #105
ROADMAP_BACKLOG_RECONCILIATION = completed under IPU Issue #106 / PR #110
TEMPLATE_MODE_SMOKE = completed under IPU Issue #107 / PR #111
POC_SAMPLE_TEMPLATE_POLICY = completed under IPU Issue #108 / PR #112
DEMO_OPS_DEPLOYMENT_PLAN = completed under IPU Issue #109 / PR #113
MAIN_BRANCH_PROTECTION_POLICY = completed under IPU Issue #114 / PR #115
OWNER_DEMO_UI_UX_REVIEW = completed under IPU Issue #117 / PR #118
OWNER_ONLY_DEMO_SECRET_CONFIG_PREP = completed under IPU Issue #116 / PR #119
```

Portfolio treatment:

```text
BI_NUMBER_REQUIRED = NO_OR_NOT_YET
PORTFOLIO_VISIBILITY_REQUIRED = YES
NUMBER_AUTHORITY = unnumbered-external
PORTFOLIO_CLASS = external
BOUNDARY_KIND = external-portfolio-project
SOURCE_OF_TRUTH = skerishKang/24-1-ipu-ai-security-filter
DO_NOT_CREATE_INTERNAL_APP_PLACEHOLDER = YES
DO_NOT_FORCE_NUMBER_ASSIGNMENT = YES
```

Relationship to B63:

```text
RELATED_B63_PROPOSAL = YES
B63_REUSABLE_ASSET = YES
B63_CLINICAL_PRODUCT_CANONICAL_STATUS = proposed/validation only
IPU_STANDALONE_PORTFOLIO_VISIBILITY = YES
IPU_CLINICAL_PHI_PRODUCTION_CLAIM = NO
```

Issue #731 for proposed B63 references IPU as a reusable codebase, but IPU remains a separate external source-of-truth repository and is not automatically converted into B63 or a canonical numbered Business by this entry.

Operational boundaries:

```text
BUSINESS_REGISTRY_MUTATION = NO
BI_NUMBER_ASSIGNED = NO
INTERNAL_APPS_WORKSPACE_CREATED = NO
SOURCE_MIGRATION = NO
PUBLIC_DEMO_APPROVED = NO
CUSTOMER_POC_READY_CLAIM = NO
SECRET_OR_DEPLOYMENT_MUTATION = NO
```

A future numbered promotion may happen only through a dedicated GitHub Issue, duplicate/conflict search, reviewed PR, and explicit owner decision.