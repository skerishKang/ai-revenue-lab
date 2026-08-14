# New / Rebuilt Business Product-Evidence Playbook

- Status: **CANONICAL PLAYBOOK**
- Legacy filename retained for link compatibility.
- Parent authority: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`
- Visual standard: `ui-ux/UI_UX_VISUAL_DIRECTION_STANDARD.md`
- Backend policy: `BACKEND_MVP_OPERATING_POLICY.md`

## 1. Purpose

Move each Business to the smallest credible evidence without repeating Business 01-style full-site visual trial-and-error.

UI-first is appropriate when desirability, identity or product comprehension is the uncertainty. Runtime/service-led/UX-first slices remain valid when those are the real uncertainties.

When a work item includes a **new art direction or material redesign**, the visual-gate sequence below is mandatory even if other UX/backend work proceeds in parallel.

## 2. Start with product truth

Before implementation confirm:

- canonical Business number and slug;
- product name and one-sentence promise;
- target user and use moment;
- primary action/result;
- overlap/boundary with existing Businesses;
- external/successor boundary;
- current evidence question;
- explicit non-goals;
- existing product behavior worth preserving;
- current visual debt and whether legacy UI is reusable.

Do not create an internal implementation for an external/successor Business.

## 3. Choose evidence lane

Possible lanes include:

```text
VISUAL_DIRECTION
UX_VERTICAL_SLICE
SERVICE_LED_PILOT
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
COMMERCIAL_HARDENING
```

Multiple lanes may coexist, but they retain separate evidence/verdicts.

## 4. Visual-direction lane — required execution order

### Step 1 — Read existing references, do not obey them blindly

Read Business-specific direction docs, current Production, current screenshots, owner comments and relevant sibling/owner-created reference work.

Treat old `KEEP`, `REDESIGN`, `frozen`, or approval markers as historical/current inputs, not automatic permission to implement them unchanged.

### Step 2 — Reference dossier

Use 3–7 meaningful references when useful.

Follow the Business 06 methodology:

```text
REFERENCE
→ OBSERVE
→ ADOPT
→ REJECT
→ TRANSLATE TO THIS PRODUCT
→ TARGET SURFACE
→ SCREENSHOT VERIFICATION
```

Do not make a mood board that only says `premium`, `cinematic`, `minimal`, `editorial`, etc.

### Step 3 — Build one Anchor Screen

Select one screen that exposes the product's real identity and primary result/action. Build only enough surrounding structure to judge it honestly.

Required evidence:

- Desktop rendered screen;
- 390px Mobile rendered screen;
- actual typography behavior;
- primary action hierarchy;
- focal asset/core object if applicable;
- no obvious generic UI fallback.

Do not build ten routes while asking whether this one direction is good.

### Step 4 — Lock or reject the anchor

Use:

```text
ANCHOR_NOT_READY
ANCHOR_REVIEW_READY
ANCHOR_DIRECTION_LOCKED
```

If the anchor fails, revise/replace it before propagation.

### Step 5 — Build 2–3 archetypes

Pick materially different surfaces, usually:

- collection/discovery/object;
- input/write/configure;
- read/detail/result.

Use feedback/recovery/comparison instead when more representative.

These screens test whether the anchor has transferable design grammar.

### Step 6 — Side-by-side system review

Review anchor + archetypes together on Desktop and Mobile.

Ask:

- same product without the logo?
- same typography logic?
- same hierarchy and material world?
- same asset treatment?
- same interaction language?
- does any route fall back to generic SaaS/card/form layout?

Only `ARCHETYPE_SYSTEM_PASS` permits `FULL_EXPANSION_ALLOWED`.

### Step 7 — Record Design System Lock

Write down actual tokens/rules before broad expansion:

- typography roles and actual loaded families;
- scale/line-height/tracking;
- color/material;
- spacing/container rhythm;
- core components/objects;
- image rules;
- controls;
- motion/reduced motion;
- Desktop→Mobile transformation rules;
- explicit legacy patterns that are now forbidden.

### Step 8 — Expand in batches

Apply the grammar to remaining routes according to their job. Do not copy one layout everywhere.

For products with many states, expand in 2–4 route batches and visually review each batch before the next.

### Step 9 — Full contact sheet

Before declaring visual completion, create all-core-route Desktop/Mobile screenshots and inspect them together.

Any load-bearing route that looks like another product, an older version, or a generic form/card shell blocks completion.

## 5. What not to do

Do not:

- implement all pages immediately from a concept document;
- call color/material replacement a redesign when layout/type hierarchy is still legacy;
- preserve weak legacy layout solely to save code;
- stack V3/V4/V5/V6/V7 styles in the active cascade;
- solve cascade problems with more `!important` layers;
- switch art direction because one later route failed to translate;
- create a new version number without diagnosing the failure;
- infer owner approval from technical QA or deployment.

## 6. Failure response

Classify before rebuilding:

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

Then fix the smallest correct level.

Example: if Entry is liked but Write/Read/Library are not, do not redesign Entry. Repair system translation and legacy/cascade debt.

## 7. UX / interaction lane

When journey uncertainty dominates, implement the shortest useful path plus load/error/recovery/accessibility states necessary to judge it.

If the product also needs a new art direction, do not let UX implementation quietly create an unreviewed full visual system. Keep the visual gates explicit.

## 8. Service-led / runtime lanes

Service-led, local-runtime and live-provider work follow `BACKEND_MVP_OPERATING_POLICY.md` and their security/data boundaries.

A real backend may begin early when it is the product uncertainty. Conversely, do not add runtime complexity when a deterministic/service-led slice answers the question faster.

## 9. Source structure

For substantial frontend work prefer a structure similar in discipline—not necessarily technology—to Business 06:

```text
styles/
  tokens
  base
  layout
  components
  states/
  journeys/
scripts/
  state modules
  navigation/interaction modules
```

Keep current visual authority obvious. See `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md`.

## 10. Completion

A visual-direction work item is complete only when its selected gate is truthfully satisfied.

Examples:

- anchor task → `ANCHOR_DIRECTION_LOCKED`;
- system test → `ARCHETYPE_SYSTEM_PASS`;
- broad redesign → `FULL_SURFACE_VISUAL_PASS` + technical evidence;
- owner visual approval → explicit owner decision after reviewing the applicable current result.

Completion is not measured by number of pages, commits, agents, versions or deployments.
