# AI Revenue Lab — Operations Index

- Status: **CANONICAL**
- Effective operating reset: 2026-08-14

This directory is the operating authority for AI Revenue Lab implementation and review. When historical documents conflict with the current canonical documents below, follow the current documents and preserve historical files only as evidence of the rules that applied at the time.

## Required reading order

For a numbered internal user-facing web Business, read in this order:

1. `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md` — **mandatory visual/product-design process**: reference translation → anchor → archetypes → full expansion.
2. `AI_DEVELOPMENT_OPERATING_POLICY.md` — roles, exact-revision work, validation, review and merge boundaries.
3. `ui-ux/UI_UX_VISUAL_DIRECTION_STANDARD.md` — visual thesis, Korean typography, reference fidelity, mobile and cross-state quality standard.
4. `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — practical start/rebuild playbook.
5. `UI_UX_BACKEND_PHASE_GATES.md` — independent UI/UX/backend/runtime evidence dimensions.
6. `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md` — canonical source/style/asset structure; no cumulative visual-generation cascade.
7. `EVIDENCE_REQUIREMENTS.md` — exact-SHA and visual/contact-sheet evidence.
8. `WORKFLOW_STATUS_MODEL.md` — implementation, visual-gate, owner, merge and Production statuses.
9. `LIVE_PRODUCTION_UI_REVIEW_POLICY.md` — when live owner review is allowed and when an art-direction reset must pass design gates first.
10. `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` — Git-connected Production and recovery.

Backend/runtime and repository-boundary authorities remain:

- `BACKEND_MVP_OPERATING_POLICY.md`
- `EXTERNAL_DEVELOPMENT_PROJECTS_POLICY.md`
- `CLOUDFLARE_CREDENTIAL_OPERATIONS.md`
- `../portfolio/BUSINESS_REGISTRY.md`
- `../portfolio/BUSINESS_EXPANSION_LINEAGE.md`
- `../portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

## Portfolio operating mode

```text
MVP_AND_VISUAL_UPGRADE
ROLE_SEPARATED_EVIDENCE
DESIGN_GATE_BEFORE_FULL_EXPANSION
REFERENCE_TRANSLATION_REQUIRED
ANCHOR_BEFORE_ARCHETYPES
ARCHETYPES_BEFORE_FULL_SITE
FULL_SURFACE_CONTACT_SHEET_REQUIRED
NO_CUMULATIVE_VISUAL_VERSION_CASCADE
OWNER_APPROVAL_SEPARATE
```

There is still no mandatory repository-wide `UI → UX → backend` ceremony. The Web CTO selects the smallest evidence slice needed for the product uncertainty. However, **when the work includes a new art direction or material visual redesign, the design gates are mandatory before broad UI expansion.**

## Visual redesign invariant

Do not interpret a Business-specific concept document as permission to implement every page immediately.

The default sequence is:

```text
PRODUCT FRAME
→ 3–7 REFERENCES WITH ADOPT/REJECT/TRANSLATE
→ ONE DESKTOP+MOBILE ANCHOR SCREEN
→ 2–3 DISTINCT ARCHETYPE SCREENS
→ SYSTEM PASS
→ FULL EXPANSION
→ ALL-SURFACE DESKTOP+MOBILE CONTACT SHEET
→ OWNER REVIEW
```

If the anchor works but the rest does not, repair system translation. Do not automatically invent another version or art direction.

## Methodology reference

`reference/business-06-world-feed-v1/` is the portfolio's positive **methodology** reference because it established an accepted visual baseline, documented concrete adopted/rejected reference patterns, and then expanded that baseline into UX.

Its visual style is not a portfolio template.

## B01 lesson now encoded as policy

Business 01 demonstrated that a strong first page plus old form/card/two-column routes is not a coherent design system. It also demonstrated that accumulating V3/V4/V5/V6/V7 CSS can make a nominal redesign behave like material skinning over old composition.

Accordingly:

- a first-page success is an anchor, not whole-site approval;
- cross-state coherence is a blocking gate;
- active visual layers must converge after a redesign;
- historical direction documents remain evidence/hypotheses, not automatic current approval.

## Templates

Use:

- `templates/CTO_WORK_ORDER.md`
- `templates/WEB_DEVELOPER_REPORT.md`
- `templates/LOCAL_VALIDATION_REPORT.md`
- `templates/CTO_FINAL_REVIEW.md`

For visual work, the work order and final review must explicitly record the current visual gate and whether full expansion is allowed.

## Approval rule

`OWNER_UI_APPROVED` is never inferred from CI, technical readiness, anchor lock, archetype pass, merge, deployment, or a historical UI approval. Only an explicit current owner decision creates it.
