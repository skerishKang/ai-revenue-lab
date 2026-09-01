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
