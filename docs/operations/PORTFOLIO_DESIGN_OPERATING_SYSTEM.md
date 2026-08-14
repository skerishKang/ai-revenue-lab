# AI Revenue Lab — Portfolio Design Operating System

- Status: **CANONICAL**
- Effective: 2026-08-14
- Scope: all numbered internal user-facing web Businesses
- Owner authority: 2026-08-14 portfolio operating reset after B01 live review
- Methodology reference: `reference/business-06-world-feed-v1/`
- Product-specific owner approval remains separate: `OWNER_UI_APPROVED=false` unless explicitly recorded otherwise.

## 1. Why this policy exists

AI Revenue Lab has enough Businesses that visual work cannot be run as repeated full-site trial-and-error.

Business 01 exposed the failure mode clearly: a first page can become visually strong while the rest of the product still inherits older typography, card/form layouts, CSS generations, and unrelated composition rules. A technically green site can therefore remain an incoherent product.

The portfolio now optimizes for **early art-direction certainty, system proof, and cheap failure** before broad implementation.

The governing sequence for a new or redesigned user-facing web product is:

```text
PRODUCT FRAME
→ REFERENCE TRANSLATION
→ ANCHOR SCREEN
→ ARCHETYPE SYSTEM TEST
→ DESIGN SYSTEM LOCK
→ FULL SURFACE EXPANSION
→ CONTACT-SHEET REVIEW
→ OWNER LIVE REVIEW
```

Do not skip directly from a concept document to full-site implementation.

## 2. Business 06 methodology is the positive process reference

Business 06 World Feed is a methodology reference, not a reusable visual style.

Its useful pattern was:

1. establish an accepted visual baseline before broad UX expansion;
2. document multiple references with explicit `ADOPT`, `REJECT`, and product-specific translation decisions;
3. preserve a clear product-specific visual thesis instead of cloning one source;
4. organize source into tokens/base/layout/components/states/journeys rather than accumulating visual generations;
5. expand the approved visual language into a deterministic journey.

Do **not** copy World Feed's colors, editorial style, density, motion, or composition into unrelated Businesses.

## 3. Phase A — Product frame and visual thesis

Before visual implementation, record a `B##_VISUAL_DIRECTION.md` containing:

- product job and target user;
- one primary user transformation;
- first action and primary result;
- emotional territory;
- primary visual world;
- core object or core interaction;
- information density;
- typography role plan;
- image/asset role;
- motion grammar;
- Desktop composition intent;
- 390px Mobile composition intent;
- anti-patterns;
- portfolio differentiation;
- current legacy surfaces that may be reused versus replaced.

A verbal style label such as `cinematic`, `editorial`, `premium`, `glass`, `dark`, or `minimal` is not a visual thesis.

## 4. Phase B — Reference Translation Sheet

Use 3–7 meaningful references when references are needed. Existing owner/sibling-created reference workspaces are preferred input when they are relevant.

For every load-bearing reference record:

| Field | Meaning |
|---|---|
| REFERENCE | exact work/product/surface |
| OBSERVE | specific useful quality |
| ADOPT | pattern to carry forward |
| REJECT | what must not be copied |
| TRANSLATE | what it becomes in this Business |
| SURFACE | where it must appear |
| VERIFY | screenshot evidence that proves it happened |

A reference is not considered used because its name appears in a prompt or README.

Reference work informs hierarchy, material, rhythm, typography, motion, interaction, or asset treatment. It does not authorize copying a complete third-party identity.

## 5. Phase C — Anchor Screen

Choose **one representative screen** that best expresses the product's identity and core value. Build that screen first on Desktop and 390px Mobile.

The anchor must prove:

- first-five-seconds product identity;
- actual Korean typography behavior;
- dominant object/action hierarchy;
- material/color/spacing system;
- image/asset quality if applicable;
- navigation/chrome relationship;
- responsive composition;
- at least the primary interaction affordance.

Possible status:

```text
ANCHOR_NOT_READY
ANCHOR_REVIEW_READY
ANCHOR_DIRECTION_LOCKED
```

`ANCHOR_DIRECTION_LOCKED` means the direction is stable enough to test as a system. It is **not** whole-product owner approval.

### Hard gate

**Do not style or rebuild every route before `ANCHOR_DIRECTION_LOCKED`.**

If the anchor fails, revise the anchor. Do not spend time propagating a rejected direction through ten pages.

## 6. Phase D — Archetype System Test

After the anchor is locked, select 2–3 screens with materially different layout/interaction demands. Typical archetypes are:

- collection/discovery/object gallery;
- input/write/configure interaction;
- long-form read/detail/result;
- feedback/recovery/comparison when more representative.

For a small product with fewer than three distinct surface types, test every distinct type.

The archetype set must prove that the anchor is a **design system**, not a one-off hero page.

Review the anchor and archetypes side by side on Desktop and Mobile. Ask:

> If logos and route names were removed, would these still look like the same authored product?

Required verdicts:

```text
ARCHETYPE_SYSTEM_FAIL
ARCHETYPE_SYSTEM_PARTIAL
ARCHETYPE_SYSTEM_PASS
```

Only `ARCHETYPE_SYSTEM_PASS` permits broad visual expansion.

## 7. Phase E — Design System Lock

After the archetype pass, record the actual system that implementation must follow:

- loaded font families and deterministic fallback behavior;
- Korean display/body/micro type scales;
- line-height and tracking rules;
- spacing and container rhythm;
- color/material tokens;
- radii/border/shadow policy;
- core object/component grammar;
- imagery crop/treatment rules;
- motion timing and reduced-motion behavior;
- Desktop/Mobile composition transformations;
- state hierarchy;
- prohibited legacy patterns.

This is the point at which `FULL_EXPANSION_ALLOWED` may be recorded.

## 8. Phase F — Full Surface Expansion

Expansion means translating the locked system to each route according to that route's job. It does **not** mean cloning the anchor layout everywhere.

During expansion:

- preserve product behavior unless the work order includes UX changes;
- redesign weak legacy shells rather than cosmetically skinning them;
- do not preserve a generic card/form/two-column structure merely because it already exists;
- do not introduce a new visual concept per route;
- do not add another visual generation to compensate for old CSS conflicts.

For large products, expand in bounded batches and review each batch visually before continuing.

## 9. Phase G — Full-surface contact-sheet gate

Before calling a visual redesign complete, capture **every core user-facing surface** on Desktop and Mobile and inspect them together.

The contact sheet is a mandatory visual artifact for multi-screen products.

Check:

1. same product identity;
2. typography consistency;
3. hierarchy and density;
4. core-object continuity;
5. image/material consistency;
6. interaction affordance consistency;
7. mobile composition quality;
8. no route that falls back to generic SaaS/card/form language;
9. no obvious old-version CSS leakage;
10. no page that looks unfinished only because of excessive empty space.

A single load-bearing incoherent route blocks `FULL_SURFACE_VISUAL_PASS`.

## 10. Failure classification before another version

Do not respond to every visual rejection by inventing V4, V5, V6, V7, V8.

First classify the failure:

```text
CONCEPT_FAILURE
REFERENCE_TRANSLATION_FAILURE
ANCHOR_COMPOSITION_FAILURE
ARCHETYPE_SYSTEM_FAILURE
TYPOGRAPHY_FAILURE
ASSET_FAILURE
IMPLEMENTATION_CASCADE_FAILURE
LEGACY_SHELL_FAILURE
MOBILE_COMPOSITION_FAILURE
```

Rules:

- If the anchor fails, change the direction at the anchor stage.
- If the anchor succeeds but archetypes fail, **keep the anchor** and repair the system translation.
- If source cascade/legacy layers cause the mismatch, consolidate implementation; do not invent a new art direction.
- A version number is revision identity, not evidence of design progress.

## 11. Typography is a system, not a font-name choice

For Korean-first products:

- the actually rendered font must be deterministic enough to review;
- do not declare a font that is not loaded/available and assume the browser used it;
- record actual fallback behavior;
- avoid Latin-first compressed metrics for Hangul;
- Korean display line-height below `1.0` requires an explicit screenshot-reviewed exception;
- body text requires comfortable measure and line-height;
- serif/sans switching must have a semantic role, especially in long-form reading surfaces;
- adjacent routes must not silently use different typography systems.

Typography evidence includes rendered screenshots and, where useful, computed loaded-family inspection.

## 12. Legacy CSS and visual-debt rule

A redesign should converge toward one canonical visual system.

The following is prohibited as a steady-state strategy:

```text
V3 stylesheet
+ V4 override
+ V5 override
+ V6 override
+ V7 authority override
+ route-specific emergency override
```

Compatibility selectors may exist temporarily, but superseded visual layers must be removed from the active rendering path once the new system is proven.

Repeated `!important` escalation is evidence of cascade debt, not design-system completion.

See `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md`.

## 13. Owner review and approval

Technical/browser/visual reviewers may reject objective defects and may record the workflow gates above.

Only explicit owner acceptance creates product-level owner approval.

```text
ANCHOR_DIRECTION_LOCKED != OWNER_UI_APPROVED
ARCHETYPE_SYSTEM_PASS != OWNER_UI_APPROVED
FULL_SURFACE_VISUAL_PASS != OWNER_UI_APPROVED
DEPLOYED != OWNER_UI_APPROVED
```

## 14. Current B01 transition rule

As of 2026-08-14, the current Personal Edition Entry is the **B01 local anchor direction** based on owner feedback that the first page is satisfactory/more balanced.

This does not approve the other participant surfaces. They require system recovery.

B01 next visual sequence is:

```text
KEEP ENTRY AS ANCHOR
→ rebuild/test Library as collection/object archetype
→ rebuild/test Write as interaction archetype
→ rebuild/test Read as long-form archetype
→ ARCHETYPE_SYSTEM_PASS
→ consolidate canonical B01 styles
→ expand Guide / Access / Feedback / History / Adaptation / other participant states
→ full Desktop/Mobile contact sheet
→ owner review
```

Do not create a new B01 art direction merely because the non-Entry pages are weak.

## 15. Portfolio-wide transition rule

Existing Business visual-direction documents remain useful hypotheses and research inputs, but a historical `frozen`, `KEEP`, `REDESIGN`, or technical UI verdict does **not** automatically satisfy this operating system.

Before substantial UI implementation of each internal Business:

1. read its existing direction/reference material;
2. revalidate it against current product truth;
3. complete/refresh the Reference Translation Sheet;
4. prove the anchor;
5. prove the archetype system;
6. only then expand broadly.

The portfolio should reuse **process rigor**, accessibility conventions, evidence tooling, and source discipline—not one universal art style.
