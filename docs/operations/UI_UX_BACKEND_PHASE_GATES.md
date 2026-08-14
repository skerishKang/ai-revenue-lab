# UI / UX / Backend Evidence Gates

- Status: **CANONICAL**
- Parent design authority: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`
- Deployment authority: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Decision

UI/visual, UX, backend/runtime, security, deployment and business evidence remain separate dimensions. There is no mandatory repository-wide `UI → UX → backend` ceremony.

However, **a new art direction or material visual redesign has its own mandatory internal sequence** because broad visual implementation is expensive to undo:

```text
VISUAL_THESIS_READY
→ REFERENCE_TRANSLATION_READY
→ ANCHOR_DIRECTION_LOCKED
→ ARCHETYPE_SYSTEM_PASS
→ FULL_EXPANSION_ALLOWED
→ FULL_SURFACE_VISUAL_PASS
```

This visual sequence does not prevent UX/backend work from proceeding when separately authorized. It prevents unproven art direction from being propagated across a product.

## 2. Evidence dimensions

### UI / visual

Answers two different questions:

1. **Technical UI** — does it render/function safely and responsively?
2. **Visual direction** — is it coherent, distinctive, reference-faithful and appropriate across states?

Verdicts:

```text
TECHNICAL_UI_PASS / FAIL
VISUAL_DIRECTION_NOT_READY
ANCHOR_DIRECTION_LOCKED
ARCHETYPE_SYSTEM_PASS / PARTIAL / FAIL
FULL_SURFACE_VISUAL_PASS / FAIL
```

No one verdict implies another.

### UX / interaction

Answers whether the intended task journey, navigation, feedback, recovery, accessibility and mobile/keyboard behavior are understandable and usable.

```text
UX_NOT_READY
UX_CONDITIONALLY_READY
UX_APPROVED
```

### Backend / runtime

Select and validate the smallest appropriate mode:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

### Security/privacy

Trust-boundary, auth/authz, secret, private-data, destructive-action and provider risk stay separately reviewable. A visual gate never weakens a security gate.

### Deployment

Deployment proves that an authorized revision operates at the intended target. It does not manufacture design-system pass, owner approval, UX approval or business evidence.

### Business evidence

Record user behavior, willingness to pay, workload, revenue, retention, cost or other experiment-specific evidence.

## 3. When visual gates are required

They are required for:

- a new Business visual system;
- owner-requested redesign;
- material art-direction change;
- broad typography/layout/material rework;
- redesign that changes several user-facing routes;
- recovery from a product whose first page and internal routes no longer look coherent.

They may be `NOT_REQUIRED` for:

- tiny isolated visual bug fixes inside an already accepted system;
- copy-only changes;
- narrowly scoped accessibility fixes that do not alter art direction;
- backend/runtime-only work with no material visual change.

The work order must record the reason.

## 4. Anchor gate

Before an anchor can be locked, require real Desktop and 390px Mobile rendered evidence and direct visual review of:

- product identity;
- first action/result hierarchy;
- Korean typography;
- material/color/spacing;
- core object/asset quality;
- responsive composition.

`ANCHOR_DIRECTION_LOCKED` permits system testing, not full-site expansion and not owner approval.

## 5. Archetype system gate

Choose 2–3 structurally different screens. The set must stress different information and interaction demands.

Review all of them beside the anchor. Only `ARCHETYPE_SYSTEM_PASS` permits `FULL_EXPANSION_ALLOWED`.

A technically correct archetype with generic form/card/two-column fallback can still fail.

## 6. Full-surface gate

For multi-screen products, `FULL_SURFACE_VISUAL_PASS` requires a Desktop/Mobile contact sheet of all core user-facing states.

A route that visibly belongs to an older design generation, another product, or a generic UI family is a blocking visual defect unless explicitly accepted.

## 7. Visual-first evidence slice

Use when identity/desirability is the primary uncertainty:

```text
product frame
→ reference translation
→ anchor
→ archetypes
→ system decision
```

Do **not** begin with a full route inventory implementation merely because all routes already exist.

## 8. UX-first / combined slice

Use the smallest useful journey. If a material new visual system is being created at the same time, it still follows anchor/archetype gates before broad propagation.

## 9. Service-led / runtime-first / commercial slices

These remain valid and may precede visual maturity when that is what the product question demands. Their evidence does not silently create permission to declare a weak UI complete.

## 10. Owner and CTO authority

The Web CTO can reject objective visual/UX/technical defects and can record workflow gates such as `ANCHOR_DIRECTION_LOCKED` and `ARCHETYPE_SYSTEM_PASS`.

Only explicit owner acceptance creates `OWNER_UI_APPROVED` or equivalent owner visual approval.

If design selection authority is explicitly delegated, record `CTO_DELEGATED_DECISION`; do not rewrite owner-approval history.

## 11. Revision identity

Every gate belongs to an exact revision or clearly identified artifact. A new commit that affects the judged surface invalidates the gate unless applicability is explicitly reviewed.

## 12. Merge and Production

Passing one evidence dimension does not automatically authorize merge/Production.

For art-direction resets, follow `LIVE_PRODUCTION_UI_REVIEW_POLICY.md`: broad live expansion is not a substitute for anchor/archetype proof.

For Git-connected Production, follow `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` after the applicable gates and authority are satisfied.
