# AI Revenue Lab — UI/UX Visual Governance

This directory is the operating entrypoint for the portfolio-wide visual reset program started on 2026-08-11.

Current program state:

```text
PORTFOLIO_PREIMPLEMENTATION_AUDIT_ACTIVE
NUMBERED_VISUAL_IMPLEMENTATION_PAUSED
OWNER_UI_APPROVED=false remains product-specific and unchanged
```

Creation baseline:

```text
origin/main = a631122888d30c5a8a62f4b27e192967da331898
```

## Required reading order

Before any future numbered UI implementation, read:

1. [`UI_UX_VISUAL_DIRECTION_STANDARD.md`](./UI_UX_VISUAL_DIRECTION_STANDARD.md)
2. [`VISUAL_AUDIT_AND_IMPLEMENTATION_PROTOCOL.md`](./VISUAL_AUDIT_AND_IMPLEMENTATION_PROTOCOL.md)
3. [`PORTFOLIO_VISUAL_DIFFERENTIATION_MATRIX.md`](./PORTFOLIO_VISUAL_DIFFERENTIATION_MATRIX.md)
4. the target Business file under [`businesses/`](./businesses/)
5. the target product's authoritative Issue/PR/contracts
6. the real current Desktop/Mobile surface

## Program tracker

See [`PORTFOLIO_VISUAL_AUDIT_TRACKER.md`](./PORTFOLIO_VISUAL_AUDIT_TRACKER.md).

No implementation target marked `RE_AUDIT_REQUIRED`, `PENDING`, `AUTHORITY_RESOLUTION`, `EXTERNAL_NO_BUILD` or `NON_WEB` may begin visual implementation under this program.

## Case studies

- [`CASE_STUDY_B06_WORLD_FEED.md`](./CASE_STUDY_B06_WORLD_FEED.md) — positive methodology example. Copy the rigor, **not the dark signal-room style**.
- [`CASE_STUDY_B01_PERSONAL_EDITION_V3_FAILURE.md`](./CASE_STUDY_B01_PERSONAL_EDITION_V3_FAILURE.md) — failure lesson: large code changes can still miss perceptual/reference fidelity.

## Current Business direction documents

- [`businesses/B01_VISUAL_DIRECTION.md`](./businesses/B01_VISUAL_DIRECTION.md) — `REDESIGN`, first implementation target **after** portfolio preimplementation audit completion.
- [`businesses/B06_VISUAL_DIRECTION.md`](./businesses/B06_VISUAL_DIRECTION.md) — product-specific Signal Room / Personal World Dispatch territory; positive methodology baseline.

More Business direction documents are added only after fresh read-only Desktop/Mobile audits under the new standard.

## Program rule

The correct order is:

```text
ANALYZE REAL SCREEN
→ WRITE/FREEZE DIRECTION
→ CHECK PORTFOLIO COLLISION
→ IMPLEMENT
→ TECHNICAL QA
→ INDEPENDENT VISUAL CONFORMANCE QA
→ LIVE OWNER REVIEW
```

Never reverse the order by implementing first and writing the design rationale afterward.
