# AI Revenue Lab — Operations Index

- Status: **CANONICAL OPERATIONS AUTHORITY**
- Effective operating reset: 2026-08-14

This directory owns implementation/review/release/evidence operating policy. It does **not** redefine current Padiem AI architecture.

Cross-layer architecture authority:

`../architecture/PADIEM_AI_VERTICAL_STACK.md`

Repository documentation index:

`../README.md`

## Required reading order

For a numbered internal user-facing web Business, read in this order:

1. `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md` — mandatory visual/product-design process for relevant visual work.
2. `AI_DEVELOPMENT_OPERATING_POLICY.md` — roles, exact-revision work, validation, review and merge boundaries.
3. `ui-ux/UI_UX_VISUAL_DIRECTION_STANDARD.md` — visual thesis, Korean typography, reference fidelity, mobile and cross-state quality standard.
4. `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — practical start/rebuild playbook.
5. `UI_UX_BACKEND_PHASE_GATES.md` — independent UI/UX/backend/runtime evidence dimensions.
6. `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md` — canonical source/style/asset structure.
7. `EVIDENCE_REQUIREMENTS.md` — exact-SHA and visual/runtime evidence.
8. `WORKFLOW_STATUS_MODEL.md` — implementation, owner, merge and Production statuses.
9. `LIVE_PRODUCTION_UI_REVIEW_POLICY.md` — live owner-review boundary.
10. `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` — Git-connected Production and recovery.

Backend/runtime/repository-boundary authorities include:

- `BACKEND_MVP_OPERATING_POLICY.md`
- `EXTERNAL_DEVELOPMENT_PROJECTS_POLICY.md`
- `CLOUDFLARE_CREDENTIAL_OPERATIONS.md`
- `../portfolio/BUSINESS_REGISTRY.md`
- `../portfolio/BUSINESS_EXPANSION_LINEAGE.md`
- `../portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

## Padiem AI architecture vs operations

For work involving Padiem AI products/platforms, classify the owning layer **before** applying operational workflow:

```text
Product/domain UX                     -> Product / Product Adapter
Reusable AI semantics                 -> IP-CORE
Cross-runtime AI service projection   -> IP-ENGINE
Model/provider routing + execution    -> B14
Identity/tenant/entitlement/usage     -> IP-CONTROL
Reusable embedded delivery            -> IP-SIDECAR when applicable
```

Canonical cross-runtime path:

```text
Product -> Product Adapter -> IP-ENGINE -> IP-CORE -> B14 -> Provider/Model
```

An accepted same-runtime consumer may reuse IP-CORE directly. That composition choice does not move shared ownership into the product.

## Historical P01 / E9 operational files

Files beginning with `P01_`, `E9_`, old issue numbers or dated activation/audit names are retained for implementation/activation history and evidence.

`P01` is historical program lineage for work that became IP-CORE/IP-ENGINE. It is **not** a separate current platform layer.

When an older operations file conflicts with the current architecture, current merged source, or a newer canonical release contract:

1. preserve the old file as historical evidence;
2. follow the current owner-layer architecture;
3. revalidate volatile SHA/issue/deployment/binding facts;
4. do not silently reactivate an old route/provider/configuration.

## Portfolio operating mode

```text
MVP_AND_VISUAL_UPGRADE
ROLE_SEPARATED_EVIDENCE
DESIGN_GATE_BEFORE_FULL_EXPANSION_WHEN_VISUAL_DIRECTION_CHANGES
NO_MANDATORY_UI_UX_BACKEND_SEQUENCE
OWNER_APPROVAL_SEPARATE
```

The Web CTO selects the smallest evidence slice needed for the current product uncertainty. When work materially changes art direction, apply the portfolio design gates before broad expansion.

## Visual redesign invariant

Default sequence for a material visual redesign:

```text
PRODUCT FRAME
-> REFERENCES WITH ADOPT/REJECT/TRANSLATE
-> DESKTOP+MOBILE ANCHOR
-> DISTINCT ARCHETYPE SCREENS
-> SYSTEM PASS
-> FULL EXPANSION
-> ALL-SURFACE REVIEW
-> OWNER REVIEW
```

A successful first page is an anchor, not automatic approval for every surface.

## Source / deployment truth

Never collapse these states:

```text
DOCUMENTED
SOURCE_PRESENT
TESTED
MERGED
CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

Examples:

- a Core capability may exist while Engine projection is deferred;
- a connector contract/UI may exist while OAuth is not configured;
- a model route may be declared while B14 rejects it as unavailable;
- a deployed product shell may still fail a live provider call.

CI proves only what it executes. Exact Production claims require current deployment/version/readback and the appropriate live acceptance evidence.

## Templates

Use:

- `templates/CTO_WORK_ORDER.md`
- `templates/WEB_DEVELOPER_REPORT.md`
- `templates/LOCAL_VALIDATION_REPORT.md`
- `templates/CTO_FINAL_REVIEW.md`

## Approval rule

`OWNER_UI_APPROVED` is never inferred from CI, technical readiness, anchor lock, merge, deployment, historical approval, or another product's acceptance. Only an explicit current owner decision creates it.

Documentation cleanup itself authorizes no Production, secret, provider, database or connector mutation.