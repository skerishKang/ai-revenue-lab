# New Business UI-First Playbook

- Status: portfolio operating policy
- Owner: Web CTO
- Permanent tracking issue: #154
- Phase policy: `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- Candidate backlog: `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`
- Current mode: `UI_ONLY`
- Applies to: every newly assigned or revived AI Revenue Lab Business

## 1. Purpose

AI Revenue Lab tests whether AI can create economically useful products through volume, speed, concurrency, real-time reaction, personalization, and measurable revenue evidence.

For the current portfolio expansion period, new Businesses begin with **visual UI design only**. The first accepted milestone is a polished product identity and representative responsive screen system. A complete UX flow is a later phase. Authentication, persistence, APIs, databases, live model calls, billing, and production infrastructure are later still.

The mandatory sequence is:

```text
Product framing
→ UI visual design
→ UI approval
→ UX and interaction design
→ UX approval
→ backend authorization decision
→ backend implementation
```

Issue #154 is the permanent open parent. Each phase uses a separate child issue. Completing one child does not close Issue #154.

## 2. Required design direction

Every new Business UI must satisfy all of the following.

### 2.1 Research real products first

Before designing:

- inspect 3–5 directly or indirectly comparable products;
- inspect 2–4 award-winning or strong editorial design references;
- analyze information architecture only as visual context, without finalizing UX;
- analyze image treatment, typography, composition, density, motion, and mobile adaptation separately;
- combine patterns from multiple references rather than cloning one site;
- record both adoption decisions and rejection reasons.

Third-party brand assets, complete screens, copy, layouts, or illustrations must not be copied without permission.

### 2.2 Use image-led composition

Where visual storytelling is central:

- acquire suitable images before implementation;
- store approved assets inside the repository and serve them from local paths;
- prohibit runtime hotlinking;
- record source URL, creator or owner when available, license or usage basis, acquisition date, and intended use in `IMAGE_SOURCES.md`;
- distinguish reference-only assets from production-approved assets;
- do not treat inaccessible or license-unclear material as production-approved.

### 2.3 Define one signature motion

Each Business receives one product-specific motion that communicates the concept.

Prefer:

- CSS transforms, opacity, masks, clipping, and restrained state-driven JavaScript;
- motion that supports hierarchy or transformation;
- mobile-safe performance;
- keyboard-compatible controls when controls are present;
- `prefers-reduced-motion` support.

Provide MP4, GIF, or equivalent evidence when static screenshots cannot prove the behavior.

### 2.4 Exclude generic AI visual language

Do not default to:

- purple-blue gradient heroes;
- decorative robots, brains, sparkles, or meaningless AI icons;
- identical rounded glass cards across every screen;
- fake metrics or decorative dashboards;
- empty claims such as “revolutionize with AI”;
- placeholder copy that reads like a developer fixture;
- unrelated stock imagery.

Use product-specific editorial, document, map, story, media, timeline, spatial, or operational metaphors instead. AI is an internal production capability, not a decorative theme.

### 2.5 Korean-first product language

Unless a Business-specific decision states otherwise:

- Korean is the original and default product language;
- English is secondary when implemented;
- missing translations fall back to Korean;
- synthetic copy must read like a credible product state;
- developer terminology is kept out of ordinary user-facing screens.

## 3. Product and workspace sequence

Do not create a production workspace solely because an idea was discussed.

```text
candidate or proposed Business
→ product-boundary and numbering decision
→ visual reference dossier
→ Phase 1 UI reference
→ UI approval
→ separate Phase 2 UX issue
→ UX approval
→ separate backend decision
→ implementation workspace and runtime phases
```

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
└─ assets/
   └─ images/
```

`app.js` may contain only the minimal state switching needed to inspect composition and motion. It must not be treated as accepted UX behavior.

After UI and UX approval, product implementation normally belongs under:

```text
apps/<stable-slug>/
```

A reference workspace is not proof of canonical numbering, UX approval, authentication, persistence, deployment, production readiness, or live-model operation.

## 4. Phase 1 UI visual-state contract

A first UI reference normally contains 4–7 representative visual states:

1. identity-rich landing or home;
2. primary feed, workspace, publication, map, story, or dashboard;
3. representative item, result, or detail view;
4. personalization, evidence, transformation, or comparison view;
5. archive, collection, or secondary surface only when visually central;
6. mobile composition;
7. signature-motion state.

The purpose is to prove the visual system, not the full journey.

Minimal controls are allowed only for review:

- previous/next state;
- view or tab switching;
- panel open/close;
- hover, focus, scroll, reveal, and motion demonstration.

The following are out of scope for the UI phase:

- complete onboarding and end-to-end task journeys;
- final navigation semantics and information architecture;
- comprehensive loading, empty, validation, error, recovery, and permission states;
- real forms, durable input, personalization logic, or recommendations;
- authentication, API, database, provider, crawling, payment, billing, or production deployment.

The visual proposition must be understandable within 30–90 seconds.

## 5. Required reference dossier

Before implementation, the Web CTO records:

- one-sentence product promise;
- target user and primary use moment;
- direct and indirect reference products;
- award or editorial references;
- patterns to adopt and reject;
- chosen visual metaphor;
- typography and density direction;
- image plan and source constraints;
- signature motion;
- desktop and mobile visual hierarchy;
- overlap and boundary with existing Businesses;
- representative UI states;
- explicit UX and backend non-goals.

## 6. Model and role allocation

### Web CTO

The Web CTO owns:

- Business-number and product-boundary verification;
- duplicate and overlap review;
- reference research and visual direction;
- task decomposition and repository scope;
- image-source and license review;
- exact-head evidence review;
- `UI_NOT_READY`, `UI_CONDITIONALLY_READY`, or `UI_APPROVED` judgment;
- creation of a UX issue only after UI approval.

Worker reports are not proof without repository and evidence verification.

### Web implementation model

Use the available high-volume Web development model after the UI contract is fixed. It may implement HTML, CSS, minimal JavaScript, synthetic visual fixtures, responsive composition, and focused visual checks. It must not silently redefine the product, design the final UX journey, change another Business, or begin backend work.

### Local model and local provider

Use Local selectively for:

- repetitive asset preparation and path normalization;
- synthetic visual fixture generation without private user data;
- local-browser rendering checks;
- responsive overflow checks;
- motion timing and reduced-motion verification;
- console, network, and local asset-path validation.

Do not use Local to expand a UI issue into UX, APIs, persistence, or backend architecture.

## 7. UI risk levels

### U0 — copy-only

Required:

- focused source inspection;
- no unrelated changes;
- browser check only when wrapping or layout may change.

Local validation is normally skipped.

### U1 — visual tokens and images

Examples: color, type size, spacing, radius, shadow, imagery, and crop.

Required:

- focused visual evidence;
- capture of the affected state;
- accessibility contrast review when relevant;
- updated image-source documentation when assets change.

Local validation is normally skipped unless remote evidence is unreliable.

### U2 — layout, responsive composition, and motion

Required:

- desktop and mobile captures;
- motion evidence when static captures are insufficient;
- keyboard and reduced-motion checks for review controls;
- Local browser validation when Web evidence is incomplete.

U3 runtime work is prohibited inside a Phase 1 UI issue. It belongs to a later explicitly authorized backend issue.

## 8. UI approval evidence

Each UI child issue requires:

- exact branch and head commit;
- changed-path list and scope confirmation;
- 1440px-class desktop screenshots;
- approximately 390px mobile screenshots;
- MP4 or GIF for signature motion when relevant;
- evidence for every required visual state;
- `IMAGE_SOURCES.md` with no undocumented hotlinks;
- no console errors or failed local assets in the reviewed states;
- keyboard-operable review controls when controls exist;
- reduced-motion behavior;
- focused visual or static contract checks where practical;
- truthful description of synthetic and reference-only behavior;
- explicit Web CTO visual verdict;
- explicit user approval before `UI_APPROVED`.

A successful build is not proof of visual quality. A clickable visual reference is not UX approval. A branch preview is not production.

## 9. Reusable UI-only child issue template

```markdown
## Purpose
Build the first polished responsive visual UI reference for Business XX — <Product>.

## Parent policy
- Permanent umbrella issue: #154
- UI playbook: `docs/operations/NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`
- Phase gates: `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- Candidate backlog: `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

## Current phase
Phase 1 — UI only

## Product promise
> <one sentence>

## Required research
- 3–5 comparable products
- 2–4 award or editorial references
- adoption and rejection analysis

## Workspace
`reference/business-XX-<stable-slug>-v1/**`

## Required files
- README.md
- REFERENCE_NOTES.md
- IMAGE_SOURCES.md
- MOTION_SPEC.md
- index.html
- styles.css
- app.js
- assets/images/**

## Required visual states
- landing/home
- primary product surface
- representative detail/result
- personalization/evidence/transformation
- mobile composition
- signature motion

## Visual requirements
- image-led composition
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
- billing or deployment

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

## 10. Permanent umbrella issue rules

Issue #154 remains open and is used to:

- link this playbook, the phase-gate policy, and the candidate backlog;
- record the ordered UI queue;
- track each Business as UI, UX, and backend separately;
- link UI-only, UX-only, and later backend child issues;
- record accepted visual heads and later UX heads;
- preserve deferred or rejected directions and reasons;
- update the process when repeated failures or improvements are discovered.

Only an explicit portfolio-governance replacement decision may close or supersede Issue #154.

## 11. Initial execution order

The first UI child is proposed Business 6 — World Feed. Its existing `apps/world-feed/` work is a technical and research baseline, not an approved visual product UI. The new work begins at Phase 1 UI and must not reuse the existence of backend-oriented code as proof of visual acceptance.

After each `UI_APPROVED` result, the user and CTO may open a separate UX issue for that Business while the UI factory proceeds to the next Business. Backend work for newly introduced Businesses remains frozen until UX approval and a separate backend authorization decision.
