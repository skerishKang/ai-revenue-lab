# New Business UI-First Playbook

- Status: portfolio operating policy
- Owner: Web CTO
- Permanent tracking issue: #154
- Phase policy: `UI_UX_BACKEND_PHASE_GATES.md`
- Deployment policy: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`
- Portfolio intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`
- Candidate backlog: `../portfolio/BUSINESS_CANDIDATE_BACKLOG.md`
- Current mode: `UI_ONLY`
- Applies to: every newly assigned or revived AI Revenue Lab Business

## 1. Purpose

AI Revenue Lab tests whether abundant AI production can create economically useful products through volume, speed, concurrency, real-time reaction, personalization, and measurable business evidence.

New Businesses begin with visual UI because a clear product identity is the fastest way to test whether an idea is distinct, understandable, and worth expanding. UI-first is a scope-control method, not an instruction to maximize prototypes or delay authorized deployment.

The default sequence is:

```text
product framing
→ UI visual design
→ UI approval
→ optional separately authorized publication
→ UX design
→ UX approval
→ backend decision
→ backend implementation
→ Production evidence
```

Each phase uses a separate authority. Completing one child issue does not close Issue #154.

## 2. Product framing before UI

Before implementation, establish:

- proposed or canonical Business number;
- stable slug and Korean/English name;
- one-sentence product promise;
- target user and primary use moment;
- primary result or artifact;
- boundary and overlap with existing Businesses;
- explicit UI-only non-goals.

Do not create a production workspace solely because an idea appeared in conversation. Preserve unresolved ideas in the candidate backlog until the product and numbering decision is explicit.

## 3. Required design direction

### 3.1 Research real products

Before designing:

- inspect 3–5 direct or indirect comparable products;
- inspect 2–4 strong editorial, award, or interaction references;
- analyze image treatment, typography, composition, density, motion, and mobile adaptation separately;
- combine patterns from multiple references rather than cloning one product;
- record adoption decisions and rejection reasons.

Third-party screens, brand assets, copy, layouts, or illustrations must not be copied without permission.

### 3.2 Use image-led composition where relevant

When visual storytelling is central:

- acquire suitable images before implementation;
- store approved assets inside the repository;
- prohibit runtime hotlinking;
- record source, owner or creator when available, license or usage basis, acquisition date, and intended use in `IMAGE_SOURCES.md`;
- distinguish reference-only assets from Production-approved assets.

### 3.3 Define one signature motion

Each Business should have one product-specific motion that communicates its concept.

Prefer:

- CSS transforms, opacity, masks, clipping, and restrained state-driven JavaScript;
- motion that supports hierarchy or transformation;
- mobile-safe performance;
- keyboard-compatible controls;
- `prefers-reduced-motion` support.

Provide video or equivalent evidence when screenshots cannot prove the behavior.

### 3.4 Exclude generic AI visual language

Do not default to:

- purple-blue gradient heroes;
- decorative robots, brains, sparkles, or meaningless AI icons;
- identical rounded glass cards across every product;
- decorative dashboards with fake metrics;
- empty claims such as “revolutionize with AI”;
- developer-fixture copy;
- unrelated stock imagery.

Use product-specific editorial, document, map, story, media, timeline, spatial, or operational metaphors instead.

### 3.5 Korean-first language

Unless a Business-specific decision states otherwise:

- Korean is the original and default product language;
- English is secondary when implemented;
- missing translations fall back to Korean;
- synthetic copy must read like a credible product state;
- developer terminology stays out of ordinary user-facing screens.

## 4. Workspace and source boundary

Default UI reference workspace:

```text
reference/business-XX-<stable-slug>-v1/
├─ README.md
├─ REFERENCE_NOTES.md
├─ IMAGE_SOURCES.md
├─ MOTION_SPEC.md
├─ index.html
├─ styles.css
├─ app.js
└─ assets/images/
```

`app.js` may contain only the state switching needed to inspect composition and motion. It must not be presented as accepted UX behavior.

After UI and UX approval, product implementation normally belongs under:

```text
apps/<stable-slug>/
```

A reference workspace is not proof of canonical numbering, UX approval, backend authorization, production readiness, or live-model operation.

## 5. Phase 1 visual-state contract

A first UI reference normally contains 4–7 representative states:

1. identity-rich landing or home;
2. primary feed, workspace, publication, map, story, or dashboard;
3. representative item, result, or detail view;
4. personalization, evidence, transformation, or comparison view;
5. archive or secondary surface only when visually central;
6. mobile composition;
7. signature-motion state.

The purpose is to prove the visual system, not the full journey.

Minimal controls are allowed only for review:

- previous/next state;
- view or tab switching;
- panel open/close;
- hover, focus, scroll, reveal, and motion demonstration.

Out of scope inside the UI implementation issue:

- complete onboarding and end-to-end journeys;
- final navigation semantics and information architecture;
- full loading, empty, validation, error, recovery, and permission matrices;
- real forms, durable input, personalization logic, or recommendation logic;
- authentication, API, database, provider, crawling, payment, or billing;
- backend or runtime deployment.

A separately authorized publication of an already accepted static UI is allowed under Section 9.

## 6. Required reference dossier

Before implementation, record:

- product promise;
- target user and primary use moment;
- direct and indirect reference products;
- editorial or award references;
- patterns to adopt and reject;
- chosen visual metaphor;
- typography and density direction;
- image plan and source constraints;
- signature motion;
- desktop and mobile hierarchy;
- overlap and boundary with existing Businesses;
- representative UI states;
- explicit UX and backend non-goals.

## 7. Model and role allocation

### Web CTO

Owns:

- product-number and boundary verification;
- duplicate and overlap review;
- reference research and visual direction;
- task scope and repository boundary;
- image-source and license review;
- exact-head evidence review;
- `UI_NOT_READY`, `UI_CONDITIONALLY_READY`, or `UI_APPROVED` judgment;
- creation of a UX issue only after UI approval.

Worker reports are not proof without repository and evidence verification.

### Web implementation model

Implements the fixed UI contract: HTML, CSS, minimal JavaScript, synthetic visual fixtures, responsive composition, and focused checks.

It may not silently redefine the product, design the final UX journey, change another Business, or begin backend work.

### Local model and local provider

Use selectively for:

- repetitive asset preparation and path normalization;
- synthetic fixtures without private user data;
- local browser rendering and responsive checks;
- overflow, motion, reduced-motion, console, network, and asset-path validation.

Do not use Local to expand a UI issue into UX, persistence, or backend architecture.

Routine repository, GitHub, and Cloudflare facts should be obtained through authenticated tools instead of asking the owner to copy them manually.

## 8. UI risk levels and evidence

### U0 — copy-only

- focused source inspection;
- no unrelated changes;
- browser check when wrapping or layout may change.

### U1 — tokens and imagery

- focused capture of affected states;
- accessibility contrast review when relevant;
- updated image-source documentation.

### U2 — layout, responsive composition, and motion

- desktop and mobile captures;
- motion evidence when screenshots are insufficient;
- keyboard and reduced-motion checks;
- local browser validation when remote evidence is incomplete.

U3 runtime work is prohibited inside a Phase 1 UI issue and belongs to a separately authorized later phase.

Every UI child issue requires the applicable evidence:

- exact branch and head;
- changed paths and scope confirmation;
- desktop and approximately 390px mobile evidence;
- signature-motion evidence when relevant;
- every required visual state;
- `IMAGE_SOURCES.md` with no undocumented hotlinks;
- no console errors or failed local assets in reviewed states;
- keyboard-operable review controls;
- reduced-motion behavior;
- truthful description of synthetic behavior;
- Web CTO visual verdict;
- explicit user approval before `UI_APPROVED`.

A successful build is not proof of visual quality. A clickable reference is not UX approval. Deployment is a separate authority.

## 9. Publication after UI approval

`UI_APPROVED` does not automatically authorize merge or deployment.

When the user separately authorizes publication, the default is direct deployment of the validated accepted `main` SHA to the dedicated Business Production project.

Preview is optional and used only when the issue records a concrete reason or the user explicitly asks for it.

Before Production publication:

- verify the accepted exact head and latest `main`;
- verify the dedicated project, root, branch, and hostname;
- record the current known-good rollback authority;
- identify required desktop, mobile, asset, console, and TLS checks.

After publication:

- verify the actual deployed SHA or bytes;
- run immediate Production smoke and visual acceptance;
- retain or rollback;
- record deployment evidence separately from UI, UX, backend, and business verdicts.

Publication must not start UX, backend, authentication, persistence, live AI, analytics, billing, or unrelated source work.

See `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

## 10. Reusable UI-only child issue template

```markdown
## Purpose
Build the first polished responsive visual UI reference for Business XX — <Product>.

## Parent authority
- Issue #154
- `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- `docs/operations/NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`
- `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

## Current phase
Phase 1 — UI only

## Product promise
> <one sentence>

## Workspace
`reference/business-XX-<stable-slug>-v1/**`

## Required research
- 3–5 comparable products
- 2–4 editorial or award references
- adoption and rejection analysis

## Required visual states
- landing/home
- primary product surface
- representative detail/result
- personalization/evidence/transformation
- mobile composition
- signature motion

## Visual requirements
- image-led composition where relevant
- product-specific signature motion
- Korean-first copy
- no generic AI visual language
- coherent desktop and mobile system

## Permitted interaction
Minimal state switching and motion preview only.

## Explicit non-goals
- complete UX journey
- final navigation semantics
- complete loading/error/state matrix
- real forms or persistence
- authentication
- API or database
- live AI or crawling
- billing or runtime deployment

A later separately authorized publication follows the direct-Production and rollback policy.

## Acceptance evidence
- exact head and scope
- desktop/mobile captures
- motion evidence
- visual-state evidence
- image-source manifest
- console and asset-path check
- focused checks
- CTO verdict and user visual approval
```

## 11. Permanent umbrella issue

Issue #154 remains open and is used to:

- link the playbook, phase policy, operating intent, deployment policy, and candidate backlog;
- record the ordered UI queue;
- track UI, UX, backend, deployment, and business evidence separately;
- link child issues;
- record accepted visual and UX heads;
- preserve deferred or rejected directions and reasons;
- improve the process when repeated failures are discovered.

Only an explicit portfolio-governance replacement decision may close or supersede Issue #154.

## 12. Execution priority

The UI factory should increase the rate at which distinct product ideas become reviewable and, after authorization, operational.

Do not let repetitive reporting, optional Preview infrastructure, or manual status copying consume more effort than the product work they are meant to support.
