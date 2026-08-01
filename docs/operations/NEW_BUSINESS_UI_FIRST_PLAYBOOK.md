# Competitive Product Demo and MVP Playbook

- Status: portfolio operating policy
- Owner: Web CTO under owner authority
- File name retained for link compatibility
- Canonical intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`
- Stage policy: `UI_UX_BACKEND_PHASE_GATES.md`
- Visual policy: `COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md`
- Backend policy: `BACKEND_MVP_OPERATING_POLICY.md`
- Deployment policy: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Purpose

This playbook turns new and existing Business ideas into commercially credible product evidence.

The target is not a safe visual reference. The target is the strongest reversible demo, MVP, or pilot that can prove the next business question.

A successful result should make a customer or investor think:

- the product solves a real problem;
- the team understands the category;
- the design is professionally competitive;
- the core experience can work;
- the product is worth trying, funding, or buying.

## 2. Select the evidence goal first

Before implementation, choose one primary evidence goal:

```text
VISUAL_DESIRABILITY
INVESTOR_STORY
USER_JOURNEY
TECHNICAL_FEASIBILITY
CUSTOMER_PILOT
REVENUE_TEST
```

Then choose the smallest suitable product stage:

```text
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
```

Do not default to a static UI when the product's value depends on live behavior. Do not build a full backend when a strong simulated journey can answer the question faster.

## 3. Product framing

Record:

- Business number, name, and stable slug;
- target customer;
- painful use moment;
- product promise;
- primary impressive result;
- existing alternatives;
- differentiation thesis;
- selected evidence goal and stage;
- bounded non-goals.

The product promise should describe the user's changed outcome, not the implementation technology.

## 4. Competitive research

### 4.1 Required reference set

Normally inspect:

- three to five direct or adjacent products;
- two to four category-leading visual, editorial, interaction, game, media, or industrial references;
- one best-in-class mobile reference when mobile matters.

### 4.2 Screen-level analysis

For each useful reference, analyze actual screens or precise screen evidence:

- entry and hero composition;
- image and video treatment;
- information hierarchy;
- type scale and density;
- navigation and progressive disclosure;
- signature interaction;
- trust and social-proof treatment;
- data and content realism;
- mobile adaptation;
- what makes the product feel paid, mature, or investable.

### 4.3 Reconstruct and improve

Pattern-level reconstruction is encouraged for rapid learning and prototyping.

Use it to understand:

- layout proportions;
- interaction timing;
- content rhythm;
- component behavior;
- conversion structure;
- product storytelling.

The final product must combine and improve patterns into an original identity. Do not publish copied brand marks, proprietary illustrations, or verbatim copy without permission.

## 5. Reference dossier

Each substantial demo or MVP requires:

```text
REFERENCE_BOARD.md
REFERENCE_NOTES.md
IMAGE_SOURCES.md
MOTION_SPEC.md when applicable
```

`REFERENCE_BOARD.md` must map reference screens to product decisions. A list of company names is insufficient.

The dossier should show:

- the benchmark screen or exact URL and capture date;
- the pattern being studied;
- where it appears in the new product;
- how the result differs or improves;
- what was rejected and why.

## 6. Visual direction

### 6.1 Image and media use

Use the strongest suitable source in this order:

1. owner-provided or product-owned media;
2. licensed commercial or open media;
3. high-quality generated photography, illustration, 3D, or motion;
4. commissioned repository-local artwork;
5. diagrams and simple SVGs as supporting information graphics.

Simple diagrams must not become the default substitute for meaningful visual storytelling.

For image-relevant Businesses, at least two major states should normally be genuinely image-led: imagery controls the composition rather than appearing as a small decoration.

### 6.2 Product-specific systems

Choose a visual system appropriate to the category:

- editorial and image-rich for media, travel, family, memory, fan, fashion, creator, and commerce products;
- spatial and geographic for location products;
- precise operational systems for verification, connectors, consoles, and workflow engines;
- human and evidence-rich for education, health, public service, and professional services;
- cinematic or immersive for entertainment and story products.

Do not force every Business into the same rounded-card dashboard.

### 6.3 Typography and content

Use Korean-first product writing unless the Business requires another language.

Customer-facing content must be credible, concrete, and category-specific. Replace fixture labels and generic AI claims with believable product states, examples, names, dates, results, and decisions.

### 6.4 Motion

Use motion to communicate product meaning, not merely decoration.

Possible roles:

- transformation;
- before/after comparison;
- generation or assembly;
- spatial navigation;
- evidence accumulation;
- approval and versioning;
- storytelling and reveal.

Motion should be smooth, reviewable, reduced-motion compatible, and visually competitive.

## 7. Demo behavior

A competitive demo may simulate substantial functionality:

- search and filtering;
- uploads and processing;
- AI generation and revision;
- recommendation and personalization;
- approval and collaboration;
- history and version comparison;
- maps, timelines, feeds, and dashboards;
- checkout, booking, or application flows;
- notifications and status changes.

Simulation should be deterministic enough to review and rich enough to explain the complete product possibility.

Repository evidence should identify simulated behavior. The interface should not be covered in repetitive warnings.

## 8. MVP behavior

When the evidence goal requires real behavior, build a vertical slice following `BACKEND_MVP_OPERATING_POLICY.md`.

Prefer one excellent complete journey over many incomplete features.

A vertical slice should include the necessary combination of:

- frontend;
- API or backend function;
- persistence;
- AI provider or deterministic fallback;
- authentication when essential;
- observability;
- realistic seed data;
- recovery and failure behavior.

Service-led manual operation may replace automation when it provides faster customer evidence.

## 9. Review standard

Technical review and visual review are separate.

### Technical floor

- intended states and journeys work;
- assets load;
- console and page errors are absent;
- responsive behavior is usable;
- accessibility blockers are absent;
- secrets and private data are not exposed;
- tests and source scope are truthful.

### Market-quality review

- the product can sit beside its references without embarrassment;
- the main screen has a strong focal point;
- images and content feel intentional and premium;
- type hierarchy and spacing are mature;
- the interface does not look generic, childish, or fixture-driven;
- mobile is designed, not merely compressed;
- the signature interaction is memorable;
- the business value can be presented in under three minutes;
- the result has a credible reason to exist beyond the benchmark products.

Status:

```text
TECHNICAL_UI_PASS
VISUAL_QUALITY_PASS
MARKET_REFERENCE_PASS
INVESTOR_DEMO_PASS
```

Do not declare `VISUAL_QUALITY_PASS` solely because there is no overflow or because local SVGs exist.

## 10. Independent review

The implementation worker may not approve its own visual result.

Independent review should compare:

- exact head;
- reference board;
- desktop and mobile evidence;
- motion evidence;
- current deployed or previous baseline;
- benchmark screenshots;
- product promise and commercial goal.

The reviewer must identify both blockers and missed opportunities.

## 11. Existing Business upgrades

For each existing Business:

1. inspect the current deployed or authoritative visual head;
2. score it using `PORTFOLIO_PRODUCT_QUALITY_AUDIT.md`;
3. classify A, B, C, or D;
4. preserve valid backend and domain logic;
5. open `Visual Upgrade v2` for B or `Product Upgrade v2` for C;
6. create new references and before/after evidence;
7. deploy only after exact-head approval.

The first upgrade wave should prioritize Businesses with:

- real backend or strong functionality but weak presentation;
- near-term customer or investor relevance;
- strong image or storytelling potential;
- existing deployment and easy before/after comparison.

## 12. Risk treatment

The owner is the final risk decision-maker.

Operators should report material risks once, with concrete options. They must not repeatedly teach generic law, policy, or security concepts, or silently weaken the product.

Use:

```text
risk
→ evidence
→ practical mitigation
→ residual risk
→ owner decision when necessary
```

Examples of mitigation include licensing, generated substitutes, redaction, access control, synthetic data, reversible demo mode, feature flags, and explicit runtime boundaries.

## 13. Default workspace

A demo or visual-upgrade workspace may use:

```text
reference/business-XX-<slug>-v2/
```

An MVP implementation normally belongs under:

```text
apps/<slug>/
```

Do not force a reference workspace when the evidence goal requires an application vertical slice.

## 14. Completion report

Every completion report should include:

- evidence goal and stage;
- benchmark products;
- exact branch and head;
- changed paths;
- product story and main journey;
- live versus simulated behavior;
- visual and media sources;
- desktop, mobile, and motion evidence;
- technical checks;
- competitive comparison verdict;
- owner decision required, if any;
- next commercial evidence step.

## 15. Default instruction

```text
Do not make the safest possible prototype.
Make the strongest reversible product evidence that truthfully demonstrates the Business.
```