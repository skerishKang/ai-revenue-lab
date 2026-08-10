# AI Revenue Lab — UI/UX Visual Governance

This directory is the operating entrypoint for the portfolio-wide visual reset program started on 2026-08-11.

Current program state:

```text
PORTFOLIO_PREIMPLEMENTATION_DIRECTION_PASS_COMPLETE
B01_NEXT_IMPLEMENTATION_TARGET
OWNER_UI_APPROVED=false remains product-specific and unchanged
```

Creation baseline:

```text
origin/main = a631122888d30c5a8a62f4b27e192967da331898
```

## Required reading order

Before any numbered UI implementation:

1. [`UI_UX_VISUAL_DIRECTION_STANDARD.md`](./UI_UX_VISUAL_DIRECTION_STANDARD.md)
2. [`VISUAL_AUDIT_AND_IMPLEMENTATION_PROTOCOL.md`](./VISUAL_AUDIT_AND_IMPLEMENTATION_PROTOCOL.md)
3. [`PORTFOLIO_VISUAL_DIFFERENTIATION_MATRIX.md`](./PORTFOLIO_VISUAL_DIFFERENTIATION_MATRIX.md)
4. target [`businesses/B##_VISUAL_DIRECTION.md`](./businesses/)
5. authoritative target Issue/PR/product contracts
6. real current Desktop/Mobile surface

Then implement, run technical QA, and independently judge `MATCH / PARTIAL / MISS` against the frozen direction.

## Program tracker and evidence

- [`PORTFOLIO_VISUAL_AUDIT_TRACKER.md`](./PORTFOLIO_VISUAL_AUDIT_TRACKER.md) — complete verdict map and evidence run IDs.
- [`AUDIT_EVIDENCE_INDEX.md`](./AUDIT_EVIDENCE_INDEX.md) — screenshot collection provenance/digests and known B44 blocker.
- [`PORTFOLIO_IMPLEMENTATION_BOUNDARIES.md`](./PORTFOLIO_IMPLEMENTATION_BOUNDARIES.md) — external/successor/non-web/gap boundaries.

## Case studies

- [`CASE_STUDY_B06_WORLD_FEED.md`](./CASE_STUDY_B06_WORLD_FEED.md) — positive methodology example. Copy the rigor, **not the dark signal-room style**.
- [`CASE_STUDY_B01_PERSONAL_EDITION_V3_FAILURE.md`](./CASE_STUDY_B01_PERSONAL_EDITION_V3_FAILURE.md) — failure lesson: large code changes can still miss perceptual/reference fidelity.

## Business direction coverage

Direction documents now exist for every current internal web implementation/review target:

```text
B01 B02 B04 B06 B07
B08 B09 B10 B11 B12 B13
B14 B15 B16 B17 B18 B19 B20 B21 B22
B29
B32 B33 B34 B35 B36 B37 B38 B39 B40 B41 B42 B43 B44
B45 B46 B47 B48 B49
B51 B52 B53 B55
B57 B58 B59
```

They live under [`businesses/`](./businesses/).

Entries deliberately without internal web direction documents are explained in `PORTFOLIO_IMPLEMENTATION_BOUNDARIES.md`:

```text
B03 B05
B23–B28
B30–B31
B50
B54 (CLI/TUI)
B56 (intentional numbering gap)
```

## Key portfolio conclusions

Fresh same-condition Desktop/Mobile evidence exposed two recurring problems that future implementations must actively undo:

1. **dark giant-title convergence** across otherwise unrelated editorial/media products;
2. **generic light-card prototype convergence** across safety/engine/operations products.

The differentiation matrix now reserves a product-specific core object and visual world for every internal web target.

## Known limitation

B44 Portfolio Console authority is resolved, but the automated live screenshot attempt hit a Cloudflare `dash.cloudflare.com` security-verification challenge. That challenge screenshot is not accepted as product evidence. B44 remains `LIVE_CONFORMANCE_PENDING`; this does not block B01 from beginning because B44's role/boundary is documented and B44 is not the current redesign target.

## Program rule

```text
ANALYZE REAL SCREEN
→ WRITE/FREEZE DIRECTION
→ CHECK PORTFOLIO COLLISION
→ IMPLEMENT
→ TECHNICAL QA
→ INDEPENDENT VISUAL CONFORMANCE QA
→ LIVE OWNER REVIEW
```

Never implement first and write the design rationale afterward.

## Next target

```text
B01 Personal Edition
```

B01 must implement `businesses/B01_VISUAL_DIRECTION.md`, then be independently verified against that document before B02 work begins.
