# AI Revenue Lab — UI/UX Visual Direction Standard

Status: `AUTHORITATIVE_DRAFT_FOR_OWNER_REVIEW`

Baseline main at creation:

```text
a631122888d30c5a8a62f4b27e192967da331898
```

This document governs future visual analysis, redesign, focused polish, implementation and visual QA for the numbered AI Revenue Lab web products.

It does **not** grant owner approval to any product.

```text
OWNER_UI_APPROVED=false
```

remains separate for every product unless the owner explicitly decides otherwise.

---

## 1. Core principle

Every Business must look and feel like a distinct product, but every Business must be designed with the same level of visual rigor.

Do **not** copy Business 06's dark visual style across the portfolio.

Copy the **quality of its design decisions**:

- identify the product's real user transformation;
- translate that transformation into a visible spatial and motion system;
- use references concretely rather than as vague mood words;
- allow weak legacy visual assets and shells to be replaced;
- make the first viewport communicate product identity and first action;
- make every core state belong to one authored product world;
- verify the real rendered Desktop and Mobile screens after implementation.

The portfolio must not converge on one fashionable visual pattern such as dark backgrounds, giant condensed titles, beige editorial layouts, generic card grids, glassmorphism, or decorative AI illustrations.

---

## 2. Required Product Visual Thesis before implementation

No UI implementation may begin until the target Business has an approved-for-implementation `B##_VISUAL_DIRECTION.md` containing at least:

1. **Product job** — what the user is actually trying to accomplish.
2. **Core transformation** — a short visible journey such as `SIGNAL → OPEN → WHY → ADJUST → RETURN`.
3. **Emotional territory** — 3–5 concrete qualities, not generic adjectives.
4. **Primary visual world** — the spatial/material environment the product belongs to.
5. **Core object** — the thing that should visually dominate the experience.
6. **Information density** — low / mid / high with justification.
7. **Motion grammar** — what moves, why it moves, and what meaning the motion communicates.
8. **Reference Translation Sheet**.
9. **Desktop composition**.
10. **390px Mobile composition**.
11. **How-to-use path** — how a new user understands `START → CORE ACTION → RESULT` within roughly 30 seconds.
12. **Anti-patterns** — what the product must not become.
13. **Differentiation check** — which nearby numbered products it could accidentally resemble and how that overlap is prevented.
14. **Expected Before → After difference**.
15. **Implementation verdict** — `KEEP`, `FOCUSED_POLISH`, or `REDESIGN`.

Implementation must follow the thesis; the thesis must not be retrofitted after implementation to justify whatever was built.

---

## 3. Reference Translation Sheet is mandatory

A reference is not considered used because it was named in a prompt, issue, README, mood board or research note.

Every meaningful reference must be translated through this table:

| Field | Required question |
|---|---|
| `REFERENCE` | What exact product/site/editorial work is being studied? |
| `OBSERVE` | What specific visual/interaction quality matters? |
| `ADOPT` | What pattern will be carried forward? |
| `REJECT` | What will explicitly not be copied? |
| `TRANSLATE` | What does the pattern become in this Business? |
| `SURFACE` | On which concrete screen/state will it appear? |
| `VERIFY` | What screenshot evidence would prove the translation actually happened? |

Rules:

- `premium`, `cinematic`, `editorial`, `immersive`, `modern`, `luxury`, `playful` and similar adjectives are **not** reference translations.
- A reference with no target surface is not implementation guidance.
- A reference translation that cannot be seen in post-implementation screenshots is a `MISS`.
- References should inform hierarchy, rhythm, material, interaction or motion; do not blindly copy complete third-party screens or identities.

---

## 4. First Five Seconds Rule

The first viewport must let a new user answer three questions without reading a long explanation:

1. **What kind of product is this?**
2. **Why is this product visually/experientially different from the other products?**
3. **What should I do first?**

Failure signals include:

- the first viewport is mostly explanatory copy;
- the dominant object has no relationship to the product's core action;
- debug/preview chrome is visible;
- the CTA is visually secondary to decoration;
- the user sees a generic dashboard, card wall or landing-page hero that could belong to another Business;
- the main visual is only a large title plus generic rectangles/gradients without product meaning.

---

## 5. Product utility outranks decoration

The strongest visual element should usually be the core product action or core result.

Examples:

- a writing product: the writing surface must have real visual authority;
- a feed product: the signal/story/feed hierarchy must dominate;
- a verification product: evidence and claim relationships must dominate;
- an archive/publication product: the collectible/readable object must dominate;
- a workflow tool: the current decision/action state must dominate.

Do not strand tiny controls inside oversized decorative compositions.

Negative space is valid only when it improves hierarchy, reading, pacing or emotional meaning.

---

## 6. Asset Quality Rule

Repository-local does not mean visually acceptable.

Existing SVGs, CSS illustrations, placeholder assets or raster images may be replaced when they weaken the product.

Use a focal visual asset when the product needs one. Do not force imagery into data/tool products that are stronger without it.

A focal asset must:

- express the product's actual state/transformation;
- occupy sufficient visual authority to matter;
- work with typography and layout rather than appear dropped into a card;
- remain legible/cropped intentionally across Desktop and Mobile;
- respect licensing/source requirements;
- avoid readable text baked into raster imagery unless explicitly authorized and accessibility-safe.

A CSS rectangle, gradient blob or generic abstract diagram is not automatically an adequate substitute for art direction.

---

## 7. Korean typography standard

Korean display typography must be designed as Korean typography, not inherited from Latin-first display rules.

Default rules:

- Korean display `line-height < 1.0` is prohibited unless an explicit screenshot-reviewed exception is recorded.
- Prefer controlled line shape over maximal font size.
- Avoid over-compressed tracking that makes Hangul blocks collide visually.
- Avoid arbitrary `<br>` line breaks that create poster-like awkward shapes.
- Check the actual rendered title at Desktop and 390px Mobile.
- Do not assume `text-wrap: balance` alone produces acceptable Korean composition.
- Body copy must preserve comfortable measure and line-height even when display typography is expressive.
- Condensed Latin display faces must not silently become the Korean visual default.

Typography QA is visual, not only computed-style QA.

---

## 8. Mobile is a separate composition

390px Mobile is not a shrunk Desktop screenshot.

For every core surface, explicitly decide:

- what appears in the first viewport;
- what becomes primary vs secondary;
- what reorders;
- what becomes sticky or stops being sticky;
- whether product chrome pushes/overlays content;
- whether large display type remains proportional;
- whether the core action is visible without excessive scroll;
- whether decorative objects should be cropped, simplified or removed.

A technically responsive layout can still fail visual QA.

---

## 9. How-to-use requirement

Every product needs a legible `START → CORE ACTION → RESULT` path.

This does not require a separate Guide page for every product.

Use one of:

- self-explanatory first-run product flow;
- compact embedded onboarding;
- a persistent `30초 사용법` entry;
- a dedicated Guide when the product has several states or non-obvious interaction rules.

A process description such as `Gather / Shape / Review / Bind` is not automatically a usage tutorial. The user must understand what **they** click, enter, inspect and receive.

---

## 10. Cross-state coherence

Entry, core action, result, feedback, archive/history, recovery/error and operator states must look like one product unless a deliberate role distinction is documented.

Do not permit:

- a cinematic landing page followed by generic forms/cards;
- one-off visual concepts that disappear after the first screen;
- different typography systems on adjacent routes;
- unrelated imagery per state;
- operator screens that look like a separate product without a justified utilitarian variant.

The visual grammar may change density by state, but identity must persist.

---

## 11. Portfolio differentiation rule

Before implementation, compare the Business against the portfolio matrix.

Every product must reserve its own combination of:

- visual world;
- core object;
- dominant material;
- density;
- motion grammar;
- color temperature;
- typography behavior;
- primary interaction pattern.

If two Businesses overlap strongly, the newer redesign must explain how they diverge.

Do not solve every product with:

- dark background + oversized display title;
- beige editorial paper;
- left rail + right workspace;
- generic three-card grids;
- faux terminal/console visuals;
- identical pill navigation;
- the same `01/02/03` ledger treatment.

Shared accessibility and interaction conventions are good; shared art direction across unrelated products is not.

---

## 12. Definition of visual quality

Technical QA and Visual Direction QA are separate gates.

Technical QA may assert:

- no overflow;
- no console/page errors;
- routes and state transitions work;
- keyboard/focus/reduced-motion behavior;
- assets load;
- backend/state contracts are preserved.

Technical GREEN does **not** imply visual acceptance.

Visual Direction QA must judge:

1. Reference fidelity
2. Product distinctiveness
3. First-viewport impact
4. Hierarchy
5. Asset quality
6. Korean typography
7. Interaction clarity
8. Mobile composition
9. Cross-state coherence
10. How-to-use clarity

Each is recorded as:

```text
MATCH
PARTIAL
MISS
```

A load-bearing `MISS` blocks completion until corrected or explicitly accepted by the owner.

---

## 13. KEEP / FOCUSED_POLISH / REDESIGN definitions

### KEEP

Use only when the current live screen already satisfies the product thesis and major references. Do not use KEEP merely because QA is green.

### FOCUSED_POLISH

Use when the visual system is correct but a bounded issue materially reduces quality, for example:

- Korean title rhythm;
- mobile ordering;
- weak CTA hierarchy;
- localized spacing/density issue;
- one inconsistent state.

### REDESIGN

Use when one or more of the following is true:

- references are materially absent from the rendered product;
- product identity is generic or confused with another Business;
- the first viewport fails the Five Seconds Rule;
- the visual system changes arbitrarily between routes;
- core utility is visually subordinate to decoration;
- focal assets are clearly below product quality;
- the owner rejects the live art direction;
- large implementation changes produced little perceptual change.

---

## 14. Owner authority and deployment boundary

Automated QA, visual reviewers, implementers and web models must never convert technical evidence into owner approval.

```text
OWNER_UI_APPROVED=false
```

remains unchanged unless the owner explicitly approves the live visual result.

Production review should use the exact merged main SHA when the product's deployment policy requires it.

Temporary QA/deployment workflows must not remain in product main after their one-off purpose is complete.

External / integrated-successor Businesses remain outside internal implementation according to the authoritative portfolio truth layer.

---

## 15. Positive and negative case studies

This standard is anchored by two portfolio lessons:

- `CASE_STUDY_B06_WORLD_FEED.md` — positive example of changing product-facing visual material and hierarchy around the real product behavior.
- `CASE_STUDY_B01_PERSONAL_EDITION_V3_FAILURE.md` — example where substantial code/art-direction work still produced insufficient perceptual/reference fidelity.

These are methodology references, not reusable stylesheets.
