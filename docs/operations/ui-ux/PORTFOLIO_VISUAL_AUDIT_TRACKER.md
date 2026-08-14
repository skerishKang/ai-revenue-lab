# AI Revenue Lab — Portfolio Visual Audit Tracker

- Status: **IMPLEMENTATION_READINESS_REVALIDATION_REQUIRED**
- Effective reset: 2026-08-14
- Parent authority: `../PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`

## 1. Why the tracker changed

The previous portfolio pass classified many Business directions as `frozen`, `KEEP`, `FOCUSED_POLISH`, `REDESIGN`, or `REDESIGN_ART_LAYER` before implementation.

Business 01 demonstrated that a direction document and successful technical QA are not enough to prove that a visual concept survives multiple real product surfaces. A strong Entry can coexist with weak/generic internal routes when legacy shells and visual generations remain active.

Therefore the previous preimplementation direction pass remains **historical research/evidence**, but its `frozen` wording no longer means `FULL_EXPANSION_ALLOWED`.

## 2. New portfolio interpretation

For every internal user-facing web Business with material visual work pending:

```text
EXISTING DIRECTION DOC = HYPOTHESIS / RESEARCH INPUT
EXISTING REFERENCE WORK = INPUT
HISTORICAL TECHNICAL UI PASS = ENGINEERING EVIDENCE
HISTORICAL OWNER ACCEPTANCE = VALID ONLY FOR THE EXACT ACCEPTED RESULT
```

Before broad new visual implementation, each Business must obtain current gate evidence:

```text
VISUAL_THESIS_READY
REFERENCE_TRANSLATION_READY
ANCHOR_DIRECTION_LOCKED
ARCHETYPE_SYSTEM_PASS
FULL_EXPANSION_ALLOWED
```

## 3. Portfolio implementation rule

Do not run the portfolio as:

```text
B01 full redesign
→ B02 full redesign
→ B04 full redesign
→ ...
```

when each design direction is still unproven as a system.

Run each substantial redesign as:

```text
Business N: anchor
→ Business N: archetypes
→ system decision
→ only then broad expansion
```

If the anchor/archetypes fail early, the failure cost stays bounded.

## 4. Current B01 state

As of current owner feedback on 2026-08-14:

```text
Business: B01 Personal Edition
Entry: KEEP AS LOCAL ANCHOR
Anchor status: ANCHOR_DIRECTION_LOCKED for system testing
Whole-product owner approval: NO
Other participant surfaces: REDESIGN / SYSTEM RECOVERY REQUIRED
Admin/operator: out of current visual recovery scope unless separately reviewed
```

Next B01 gate set:

```text
Library = collection/object archetype
Write   = interaction archetype
Read    = long-form archetype
```

Required next decision:

```text
ARCHETYPE_SYSTEM_PASS
or
ARCHETYPE_SYSTEM_FAIL/PARTIAL with diagnosed cause
```

Only after a pass:

```text
consolidate canonical B01 visual source
→ expand remaining participant routes
→ full Desktop/Mobile contact sheet
→ owner whole-product review
```

Do not create V8 simply because the current non-Entry pages are weak.

## 5. Business 06 state

Business 06 World Feed remains the strongest **methodology reference**:

- accepted visual baseline before later UX expansion;
- explicit reference `ADOPT / REJECT / product difference` notes;
- source separated into tokens/base/layout/components/states/journeys;
- visual system extended into a deterministic journey.

This does not mean B06's current visual style should be copied or that every current B06 surface is permanently exempt from future review.

## 6. Existing Business-specific direction documents

All existing files under:

```text
docs/operations/ui-ux/businesses/B##_VISUAL_DIRECTION.md
```

remain useful. Their role is now:

```text
VISUAL HYPOTHESIS
+ REFERENCE/DIFFERENTIATION INPUT
+ LEGACY AUDIT INPUT
```

Before implementation, refresh only what current evidence contradicts. Do not rewrite every direction document for ceremony.

## 7. Boundary Businesses

External, successor, integrated, protected-authority, non-web, and numbering-gap boundaries remain governed by:

- `PORTFOLIO_IMPLEMENTATION_BOUNDARIES.md`
- `../../portfolio/BUSINESS_REGISTRY.md`
- `../../portfolio/BUSINESS_EXPANSION_LINEAGE.md`

This visual-policy reset does not authorize internal implementation where repository authority excludes it.

## 8. Historical evidence preservation

The previous tracker revision, audit runs/artifacts and old verdict table remain available in Git history. Do not reinterpret those artifacts as fabricated or invalid; they represent the evidence and methodology used at that time.

The change is forward-looking:

> historical direction freeze no longer equals current system-proof or full-expansion authority.

## 9. Current portfolio queue rule

For the next internal Business selected for visual work, the work order must record:

- current product truth;
- existing direction/reference material read;
- anchor route;
- 2–3 planned archetypes;
- current visual gate;
- full-expansion authorization status;
- owner-review status.

The portfolio can still progress quickly, but it must fail cheaply at the anchor/system stage instead of expensively after a complete site rebuild.
