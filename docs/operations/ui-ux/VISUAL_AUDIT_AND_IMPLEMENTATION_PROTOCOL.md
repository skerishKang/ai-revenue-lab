# AI Revenue Lab — Visual Audit → Anchor → System → Expansion Protocol

- Status: **CANONICAL**
- Effective: 2026-08-14
- Parent authority: `../PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`

This protocol replaces the prior portfolio-wide `audit → direction document freeze → full implementation → conformance` sequence.

The old sequence failed to distinguish a **written direction** from a **proven design system**. Business 01 showed that an attractive Entry can still be followed by generic/legacy internal routes.

The current sequence is:

```text
GATE A — CURRENT PRODUCT / AUTHORITY AUDIT
GATE B — VISUAL THESIS + REFERENCE TRANSLATION
GATE C — ANCHOR SCREEN
GATE D — ARCHETYPE SYSTEM TEST
GATE E — FULL EXPANSION
GATE F — FULL-SURFACE CONFORMANCE
GATE G — OWNER CURRENT-RESULT REVIEW
```

## GATE A — Current product / authority audit

Before visual judgment classify the Business:

```text
INTERNAL_LIVE_PRODUCT
INTERNAL_REVIEW_SURFACE
EXTERNAL_IMPLEMENTATION
EXPANDED_SUCCESSOR
INTEGRATED_SUCCESSOR
NON_WEB
UNKNOWN_REQUIRES_RESOLUTION
```

External/successor/non-web items are documented, not redesigned internally without separate authority.

For an internal web product, inspect enough real current surfaces to understand the product and legacy debt. For an existing multi-screen product this normally includes root/Entry, Guide/onboarding when present, primary action, primary result/detail, an important feedback/recovery/history surface, and Desktop plus 390px Mobile evidence.

Record exact revision/URL/evidence identity.

## GATE B — Visual thesis + reference translation

Read existing Business direction docs and reference work. They are input, not automatic current implementation authority.

Refresh or create `B##_VISUAL_DIRECTION.md` only as needed to state current product job/transformation, visual world/core object, typography/asset/motion roles, Desktop/Mobile intent, anti-patterns/differentiation, reference translations and legacy reuse/replace decision.

Every meaningful reference uses:

```text
REFERENCE
OBSERVE
ADOPT
REJECT
TRANSLATE
SURFACE
VERIFY
```

Business 06 World Feed is the methodology example for explicit adopted/rejected reference reasoning.

## GATE C — Anchor Screen

Choose one representative screen and build it first at Desktop and 390px Mobile.

Required judgment:

- product identity in first five seconds;
- first action/result hierarchy;
- Korean typography;
- visual world/material;
- core object/asset quality;
- responsive composition;
- product-specific distinction.

Use:

```text
ANCHOR_NOT_READY
ANCHOR_REVIEW_READY
ANCHOR_DIRECTION_LOCKED
```

Do not style all routes while the anchor remains undecided.

## GATE D — Archetype System Test

Select 2–3 structurally different screens. Typical set:

```text
COLLECTION / DISCOVERY / OBJECT
INPUT / WRITE / CONFIGURE
READ / DETAIL / RESULT
```

Substitute feedback/recovery/comparison when more representative.

Capture each on Desktop and Mobile and review them **beside the anchor**.

Judge whether typography is one system, materials/assets belong together, hierarchy changes appropriately without losing identity, controls/interactions feel related, generic SaaS/card/form fallback is absent, and Mobile is re-authored rather than merely stacked.

Use:

```text
ARCHETYPE_SYSTEM_FAIL
ARCHETYPE_SYSTEM_PARTIAL
ARCHETYPE_SYSTEM_PASS
```

Only PASS authorizes `FULL_EXPANSION_ALLOWED`.

## GATE E — Full Expansion

After system pass, record the Design System Lock and expand remaining routes in bounded batches.

A REDESIGN may replace weak visual shells, assets, layout systems and motion grammar while preserving required functional/backend/state contracts.

Do not clone the anchor layout across every route, preserve generic legacy shells for convenience, create route-by-route art directions, or solve old CSS conflicts by adding another generation of global overrides.

Follow `../CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md`.

## GATE F — Full-Surface Conformance

Before visual completion, capture all core user-facing routes/states on Desktop and Mobile and build one reviewable contact-sheet artifact.

Conformance dimensions:

| Dimension | Verdict |
|---|---|
| Reference fidelity | MATCH / PARTIAL / MISS |
| Product distinctiveness | MATCH / PARTIAL / MISS |
| First-viewport clarity | MATCH / PARTIAL / MISS |
| Hierarchy/density | MATCH / PARTIAL / MISS |
| Korean typography | MATCH / PARTIAL / MISS |
| Asset/material quality | MATCH / PARTIAL / MISS |
| Interaction clarity | MATCH / PARTIAL / MISS |
| Mobile composition | MATCH / PARTIAL / MISS |
| Cross-state coherence | MATCH / PARTIAL / MISS |
| How-to-use clarity | MATCH / PARTIAL / MISS |

A load-bearing `MISS` blocks `FULL_SURFACE_VISUAL_PASS` unless explicitly accepted by the owner.

Also inspect active style/source authority for obvious legacy generation leakage when relevant.

## GATE G — Owner current-result review

Owner review occurs on the applicable current result under `../LIVE_PRODUCTION_UI_REVIEW_POLICY.md`.

Technical/design reviewers may lock anchor/system gates and reject objective defects. They may not manufacture final owner aesthetic acceptance.

```text
OWNER_UI_APPROVED=false
```

remains until explicit owner acceptance.

## Failure protocol

Before naming another version or art direction, classify:

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

If the anchor is liked and later routes fail, preserve the anchor and repair the system/translation/cascade unless evidence shows the anchor concept itself is the root cause.

## B01 current application

B01 is currently in system recovery:

```text
Entry → ANCHOR_DIRECTION_LOCKED for system testing
Library → archetype candidate
Write → archetype candidate
Read → archetype candidate
other participant routes → wait for archetype decision
```

The current failure is not evidence that B01 needs another new concept. It is evidence that the accepted Entry has not yet been translated into a canonical cross-state system.

## Portfolio execution rule

Do not block the whole portfolio until every Business has a perfect direction document, and do not blindly implement the whole portfolio from old frozen documents.

When a Business becomes the active visual target:

```text
read current truth + old direction/reference
→ anchor
→ archetypes
→ system decision
→ broad expansion only on pass
```

This is the reusable process intended to make 50+ Businesses tractable.
