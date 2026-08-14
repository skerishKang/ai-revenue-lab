# AI Revenue Lab — UI/UX Visual Direction Standard

- Status: **CANONICAL**
- Effective: 2026-08-14
- Parent authority: `../PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`
- Methodology case: `CASE_STUDY_B06_WORLD_FEED.md`
- Failure cases: B01 case studies in this directory

This standard governs visual analysis, redesign, focused polish, implementation and visual QA for numbered internal user-facing web products.

It never creates product-level owner approval by itself.

```text
OWNER_UI_APPROVED=false
```

remains separate until explicit owner acceptance.

## 1. Core principle

Every Business must be a distinct authored product. Portfolio consistency means **consistent decision quality and evidence discipline**, not shared art direction.

Do not copy Business 06's look, Business 01's glass/material system, or any other successful Business across unrelated products. Reuse methodology, accessibility conventions, implementation discipline and QA rigor.

## 2. Mandatory visual gates

For a new art direction or substantial redesign:

```text
VISUAL_THESIS_READY
→ REFERENCE_TRANSLATION_READY
→ ANCHOR_REVIEW_READY
→ ANCHOR_DIRECTION_LOCKED
→ ARCHETYPE_SYSTEM_PASS
→ FULL_EXPANSION_ALLOWED
→ FULL_SURFACE_VISUAL_PASS
→ OWNER_REVIEW_REQUIRED
```

The first four gates exist to prevent expensive whole-site redesigns around an unproven idea.

### Hard prohibition

Do not implement/style every route before `ARCHETYPE_SYSTEM_PASS`.

A work order that asks for broad redesign must still stage the implementation so the anchor and archetypes can be visually judged before the remaining routes are propagated.

## 3. Product Visual Thesis

Before visual implementation, the Business direction document must state:

1. product job;
2. target user and use moment;
3. core transformation;
4. first action and primary result;
5. emotional territory;
6. visual world;
7. core visual object or interaction;
8. density;
9. typography role plan;
10. image/asset role;
11. motion grammar;
12. Desktop composition;
13. 390px Mobile composition;
14. how-to-use path;
15. anti-patterns;
16. differentiation against nearby Businesses;
17. reuse/replace verdict for legacy UI;
18. implementation verdict: `KEEP`, `FOCUSED_POLISH`, or `REDESIGN`.

The thesis must precede implementation. Do not retrofit it afterward.

## 4. Reference Translation Sheet

Every load-bearing reference must answer:

| Field | Required question |
|---|---|
| REFERENCE | What exact work/surface is studied? |
| OBSERVE | What precise quality matters? |
| ADOPT | What pattern is useful? |
| REJECT | What will not be copied? |
| TRANSLATE | What does it become for this product? |
| SURFACE | Where will it appear? |
| VERIFY | What rendered evidence proves it? |

The Business 06 `REFERENCE_NOTES.md` pattern is the preferred methodological example: multiple sources were studied, useful patterns and rejected patterns were recorded, and the product difference was stated explicitly.

Generic words such as `premium`, `cinematic`, `editorial`, `immersive`, `modern`, `luxury`, `minimal`, and `playful` are not sufficient reference translation.

## 5. Anchor Screen standard

The anchor is the one screen that best proves identity and the core product promise. It must be reviewed at Desktop and 390px Mobile before broad expansion.

It must make the user understand within roughly five seconds:

- what kind of product this is;
- what visually distinguishes it;
- what to do first.

The anchor also establishes the first real typography/material/spacing/asset relationship. It is more authoritative than a mood board.

## 6. Archetype System standard

The anchor is not proof of a system.

Choose 2–3 materially different surfaces and prove that the same visual language survives different demands. Prefer a combination such as:

- collection/discovery/object surface;
- input/write/configuration surface;
- long-form read/detail/result surface.

Substitute feedback/recovery/comparison when those better represent the product.

Review the anchor plus archetypes side-by-side. Failure to look like one authored product is `ARCHETYPE_SYSTEM_FAIL` even if every individual screen looks acceptable in isolation.

## 7. First Five Seconds Rule

The first viewport fails when:

- it is mostly explanation;
- the dominant visual is unrelated to the core action/result;
- tiny controls are stranded inside oversized decoration;
- a generic dashboard/card wall could belong to any Business;
- a giant title is doing the work that product composition should do;
- debug/preview chrome dominates;
- the first action is visually unclear.

## 8. Product utility outranks decoration

The strongest element should usually be the core action or result.

Examples:

- writing product → writing/fragment surface has authority;
- feed product → signal/story hierarchy dominates;
- verification product → claim/evidence relationship dominates;
- archive/publication product → collectible/readable object dominates;
- workflow product → current decision/action dominates.

Negative space is valid only when it improves hierarchy, reading, pacing or emotional meaning. Empty area that makes a route look unfinished is not successful minimalism.

## 9. Korean typography standard

Korean display typography is not a Latin display system with Hangul substituted into it.

Rules:

- actual rendered/loaded family must be understood; naming an unavailable font is not typography control;
- Korean display `line-height < 1.0` is prohibited unless a screenshot-reviewed exception is recorded;
- avoid severe negative tracking that compresses Hangul blocks;
- control line shape before maximizing font size;
- avoid arbitrary `<br>` poster shapes;
- body copy requires comfortable width and line-height;
- serif/sans switching must have a semantic role;
- adjacent routes must not silently use different typography systems;
- Desktop and 390px Mobile titles must both be visually reviewed.

Typography QA is rendered-screen QA, not only CSS-token inspection.

## 10. Asset quality standard

Repository-local does not mean visually acceptable.

Replace weak CSS illustrations, generic placeholders, stale imagery or low-authority assets when the product needs stronger material. A focal asset must express the real product state/transformation and survive intentional Desktop/Mobile cropping.

Do not introduce imagery merely to decorate a tool that is stronger without it.

## 11. Mobile is a separate composition

390px Mobile is not a shrunk Desktop layout.

For every anchor/archetype/core route decide:

- first viewport priority;
- reordering;
- sticky/non-sticky behavior;
- type scale;
- crop/removal of decorative objects;
- visibility of the primary action;
- reading measure and control density.

A technically responsive screen can still fail visual QA.

## 12. Cross-state coherence

A product fails cross-state coherence when it has, for example:

- a cinematic/art-directed landing page followed by generic forms/cards;
- one typography language on Entry and another on Read;
- unrelated image treatment per route;
- old shell structures merely recolored to match a new palette;
- one-off hero concepts that disappear after Entry;
- mobile states that lose the product's hierarchy.

Density can change by route. Identity must persist.

## 13. Design-system translation, not layout cloning

After archetype pass, record the actual transferable grammar: typography, spacing, materials, color, image treatment, core objects, controls, motion and responsive rules.

Full expansion uses this grammar to solve each route's job. Do not clone the exact anchor layout across every page.

## 14. Redesign means replacement when necessary

Use:

### KEEP
Current live structure already expresses the visual thesis and references.

### FOCUSED_POLISH
The system is correct and a bounded defect—type rhythm, spacing, hierarchy, one state, mobile ordering—needs repair.

### REDESIGN
The product identity, reference translation, cross-state system, core utility hierarchy, asset quality or owner direction is materially wrong.

When REDESIGN is appropriate, preserving a weak legacy shell for implementation convenience is not a virtue.

## 15. No version-number escape hatch

A visual failure must be diagnosed before another version is named.

Use one or more:

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

If the anchor succeeds and later routes fail, do not discard the anchor or invent a new concept automatically. Repair translation/system/cascade.

## 16. Technical QA and Visual QA are separate

Technical QA covers overflow, errors, routes, controls, keyboard/focus, reduced motion, assets and runtime contracts.

Visual Direction QA judges:

1. reference fidelity;
2. product distinctiveness;
3. first-viewport clarity;
4. hierarchy;
5. typography;
6. asset quality;
7. interaction clarity;
8. mobile composition;
9. cross-state coherence;
10. how-to-use clarity.

Use `MATCH`, `PARTIAL`, `MISS` for each. A load-bearing `MISS` blocks the applicable visual gate.

## 17. Full-surface evidence

A multi-screen redesign is not complete until all core user-facing routes are captured on Desktop and Mobile and reviewed together as a contact sheet.

The reviewer must be able to spot routes that look like another product, routes that reverted to generic UI, typography drift, density discontinuity, stale asset treatment and visual cascade leakage.

## 18. Portfolio differentiation

Every Business reserves its own combination of visual world, core object, material, density, motion grammar, temperature, typography behavior and interaction pattern.

Do not solve the portfolio with one repeated fashion such as:

- dark background + giant title;
- beige editorial paper;
- glassmorphism;
- left rail + right workspace;
- three-card grids;
- identical pill navigation;
- repeated `01/02/03` ledger treatment.

## 19. Owner authority

The workflow may lock an anchor and pass a system without final owner approval.

Only explicit owner acceptance creates `OWNER_UI_APPROVED=true` or equivalent owner-approved state.

## 20. Current B01 interpretation

The 2026-08-14 B01 Entry is the local anchor direction because the owner stated the first page is satisfactory/more balanced, while the remaining pages are not satisfactory.

Therefore the correct action is **system recovery**, not another new B01 concept:

```text
Entry anchor KEEP
→ Library / Write / Read archetype rebuild
→ archetype system review
→ canonical style consolidation
→ remaining participant-route expansion
→ full contact sheet
→ owner review
```
