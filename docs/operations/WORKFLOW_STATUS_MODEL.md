# Workflow Status Model

- Status: **CANONICAL**
- Parent design authority: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`

This model separates product/design gates, implementation, validation, CTO readiness, owner decisions, merge and Production. Do not collapse them into one `done` flag.

## 1. Product evidence stage

A work item may target one current evidence stage:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
OPERATING_PRODUCT
```

These are not mandatory sequential stages for every Business.

## 2. Visual design gate

Use when the work creates or materially redesigns a user-facing visual system:

```text
VISUAL_GATE_NOT_REQUIRED
VISUAL_THESIS_PENDING
VISUAL_THESIS_READY
REFERENCE_TRANSLATION_READY
ANCHOR_NOT_READY
ANCHOR_REVIEW_READY
ANCHOR_DIRECTION_LOCKED
ARCHETYPE_SYSTEM_PENDING
ARCHETYPE_SYSTEM_FAIL
ARCHETYPE_SYSTEM_PARTIAL
ARCHETYPE_SYSTEM_PASS
FULL_EXPANSION_ALLOWED
FULL_SURFACE_VISUAL_FAIL
FULL_SURFACE_VISUAL_PASS
```

Rules:

- `ANCHOR_DIRECTION_LOCKED` permits archetype testing, not broad route expansion.
- `ARCHETYPE_SYSTEM_PASS` is required before `FULL_EXPANSION_ALLOWED` for a material redesign.
- `FULL_SURFACE_VISUAL_PASS` requires multi-route Desktop/Mobile contact-sheet review when applicable.
- none of these states means `OWNER_UI_APPROVED`.

## 3. Failure diagnosis

Before creating another visual version, record one or more when relevant:

```text
CONCEPT_FAILURE
REFERENCE_TRANSLATION_FAILURE
ANCHOR_COMPOSITION_FAILURE
ARCHETYPE_SYSTEM_FAILURE
TYPOGRAPHY_FAILURE
ASSET_FAILURE
LEGACY_SHELL_FAILURE
IMPLEMENTATION_CASCADE_FAILURE
MOBILE_COMPOSITION_FAILURE
```

This prevents a later-route translation failure from being misdiagnosed as a need for a brand-new concept.

## 4. Implementation

```text
NOT_STARTED
IN_PROGRESS
IMPLEMENTED_SELF_CHECK_PENDING
IMPLEMENTED_SELF_CHECKED
BLOCKED
SUPERSEDED
```

`IMPLEMENTED_SELF_CHECKED` is implementation-actor evidence, not independent validation.

## 5. Independent validation

```text
NOT_REQUIRED
PENDING
BLOCKED
FAILED
PASSED
INVALIDATED_BY_NEW_REVISION
```

Use `PASSED` only when the required independent validator tested the exact revision and did not create a new product-source revision during that validation.

## 6. CI

```text
NOT_CONFIGURED
NOT_REQUIRED
PENDING
FAILED
PASSED
```

CI never substitutes for a different required evidence type.

## 7. Evidence-dimension verdicts

Use separately when relevant:

```text
TECHNICAL_UI_PASS
VISUAL_DIRECTION_PASS
CROSS_STATE_COHERENCE_PASS
KOREAN_TYPOGRAPHY_PASS
MOBILE_COMPOSITION_PASS
UX_PASS
BACKEND_RUNTIME_PASS
SECURITY_PASS
MARKET_REFERENCE_PASS
INVESTOR_DEMO_PASS
COMMERCIAL_EVIDENCE_PASS
```

Never infer one from another.

## 8. Web CTO final review

```text
NOT_REVIEWED
NOT_READY
CONDITIONALLY_READY
READY
```

- `NOT_READY` — required criteria/evidence fail.
- `CONDITIONALLY_READY` — acceptable within explicitly recorded non-misleading conditions.
- `READY` — current exact head satisfies the technical/review contract and all required pre-merge evidence.

`READY` does not create owner approval, merge authority or Production acceptance.

## 9. Owner decision

Use only when a material decision is reserved to the owner:

```text
NOT_REQUIRED
PENDING
APPROVED
REJECTED
```

For visual products, keep the more explicit record when useful:

```text
OWNER_REVIEW_REQUIRED
OWNER_UI_APPROVED
OWNER_UI_REJECTED
REDESIGN_REQUIRED
```

An anchor/system pass must not be relabeled as owner approval.

If the owner explicitly delegates design selection, record `CTO_DELEGATED_DECISION`.

## 10. Merge

```text
NOT_AUTHORIZED
AUTHORIZED
MERGED
CLOSED_UNMERGED
```

Use expected-head protection when merging reviewed work.

For a broad new art direction, merge authorization must respect the applicable visual-design gate and `LIVE_PRODUCTION_UI_REVIEW_POLICY.md`.

## 11. Production

```text
NOT_APPLICABLE
NOT_AUTHORIZED
AWAITING_GIT_DEPLOYMENT
DEPLOYED_UNVERIFIED
ACCEPTED
FAILED
RESTORED
```

Production status is revision/deployment evidence only.

## 12. Revision rule

Every source-dependent status records the exact SHA or exact artifact/revision identity. A new commit affecting the judged surface may move validation/review/gates back to pending or invalidated.
