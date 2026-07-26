# New Business UI-First Playbook

- Status: portfolio operating policy
- Owner: Web CTO
- Permanent tracking issue: #154
- Phase policy: `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- Hosted-review runbook: `docs/operations/CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md`
- Candidate backlog: `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`
- Current mode: `UI_ONLY`
- Applies to: every newly assigned or revived AI Revenue Lab Business

## 1. Purpose

AI Revenue Lab tests whether AI can create economically useful products through volume, speed, concurrency, real-time reaction, personalization, and measurable revenue evidence.

New Businesses begin with **visual UI design only**. The first accepted milestone is a polished product identity and representative responsive screen system. A complete UX flow is a later phase. Authentication, persistence, APIs, databases, live model calls, billing, and product production infrastructure are later still.

The mandatory sequence is:

```text
Product framing
→ UI visual design
→ hosted visual review when useful
→ UI approval
→ UX and interaction design
→ UX approval
→ backend authorization decision
→ backend implementation
→ separately authorized product release
```

Hosted visual review is evidence infrastructure inside the current phase. It is not a new phase and does not advance the gate.

Issue #154 is the permanent open parent. Each phase uses a separate child issue. Completing one child does not close Issue #154.

## 2. Required design direction

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

Provide MP4, GIF, or equivalent evidence when static screenshots cannot prove the behavior. When a correctly connected hosted-review site exists, verify the motion there as well.

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
→ correct GitHub branch and Draft PR
→ dedicated hosted-review connection when useful
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

A reference workspace or hosted URL is not proof of canonical numbering, UX approval, authentication, persistence, backend authorization, production readiness, or live-model operation.

## 4. Phase 1 visual-state contract

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
- authentication, API, database, provider, crawling, payment, billing, or product production release.

A dedicated static hosted-review connection is allowed and is not the prohibited product production release.

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
- explicit UX and backend non-goals;
- intended hosted-review project name, repository, branch, and root directory when hosted review will be used.

## 6. Hosted UI review

### 6.1 Default user inspection method

When the user needs to judge a static UI and the artifact can be hosted safely, the default inspection method is a **dedicated, correctly connected browser site**. Large screenshots remain supporting evidence. They must not be the primary review method merely because they are already committed.

### 6.2 Connection contract

Follow `CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md` and record:

- Pages project name;
- GitHub repository;
- exact branch;
- exact SHA;
- root directory;
- build command;
- output directory;
- resulting URL;
- access policy;
- post-connection asset and identity checks.

For a plain static reference:

```text
Build command: <empty>
Build output directory: .
```

Do not introduce a build framework merely to obtain a Pages URL.

### 6.3 Validity rules

The hosted review is invalid when:

- it uses another Business's Pages project;
- the root points to another app or the repository root without approval;
- the deployed commit differs from the expected exact SHA;
- the visible identity belongs to another product;
- required local assets fail;
- the URL is described as product production without separate authorization.

A Cloudflare success bot comment is not enough. Project identity and content must be verified.

### 6.4 Phase effect

Creating or updating a hosted-review connection does not:

- merge the PR;
- mark the PR Ready;
- grant `UI_APPROVED`;
- authorize UX or backend work;
- release the product to production.

Cloudflare's setting called `Production branch` is only the primary branch for that Pages project. It does not override portfolio governance.

## 7. Model and role allocation

### 7.1 Web CTO

The Web CTO owns:

- Business-number and product-boundary verification;
- duplicate and overlap review;
- reference research and visual direction;
- task decomposition and repository scope;
- image-source and license review;
- intended Pages project/repository/branch/root definition;
- exact-head and hosted-identity evidence review;
- `UI_NOT_READY`, `UI_CONDITIONALLY_READY`, or `UI_APPROVED` judgment;
- creation of a UX issue only after UI approval.

Worker reports and deployment bot comments are not proof without repository, project-identity, and rendered-evidence verification.

### 7.2 Web implementation model

Use the available high-volume Web development model after the UI contract is fixed. It may implement HTML, CSS, minimal JavaScript, synthetic visual fixtures, responsive composition, and focused visual checks. It must not silently redefine the product, design the final UX journey, change another Business, reuse another Business's hosting project, or begin backend work.

### 7.3 Local model and local provider

Use Local selectively for:

- repetitive asset preparation and path normalization;
- synthetic visual fixture generation without private user data;
- local-browser rendering checks;
- responsive overflow checks;
- motion timing and reduced-motion verification;
- console, network, and local asset-path validation.

Do not use Local to expand a UI issue into UX, APIs, persistence, or backend architecture.

### 7.4 Cloudflare account operator

The operator with Cloudflare control-plane access:

- creates the dedicated Pages project;
- connects the approved GitHub repository;
- enters the branch, root, build, output, and access settings;
- reports the resulting project and URL.

A model without Cloudflare account tools must not claim it performed this account-side action. It must still provide the correct exact configuration without turning the task into a different deployment design.

## 8. UI risk levels

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
- Local browser validation when Web evidence is incomplete;
- hosted browser review when the user is expected to approve the visual direction from a site.

U3 runtime work is prohibited inside a Phase 1 UI issue. It belongs to a later explicitly authorized backend issue.

## 9. UI approval evidence

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
- hosted-review project/repository/branch/root/SHA verification when a URL is used;
- explicit Web CTO visual verdict;
- explicit user approval before `UI_APPROVED`.

A successful build is not proof of visual quality. A clickable visual reference is not UX approval. A branch preview is not production. A hosted URL from the wrong project is not evidence.

## 10. Reusable UI-only child issue template

```markdown
## Purpose
Build the first polished responsive visual UI reference for Business XX — <Product>.

## Parent policy
- Permanent umbrella issue: #154
- UI playbook: `docs/operations/NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`
- Phase gates: `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- Hosted review: `docs/operations/CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md`
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

## Hosted-review target
- Pages project: `ai-revenue-<stable-slug>`
- repository: `skerishKang/ai-revenue-lab`
- branch: `<feature branch>`
- root: `reference/business-XX-<stable-slug>-v1`
- build command: empty
- output directory: `.`

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
- billing or product production release

## Acceptance evidence
- exact head and scope
- desktop/mobile captures
- motion and visual-state evidence
- image-source manifest
- console and asset-path check
- hosted project/repository/branch/root/SHA check
- focused checks
- CTO verdict and user visual approval
```

## 11. Permanent umbrella issue rules

Issue #154 remains open and is used to:

- link this playbook, the phase-gate policy, hosted-review runbook, and candidate backlog;
- record the ordered UI queue;
- track each Business as UI, UX, backend, and hosted review separately;
- link UI-only, UX-only, and later backend child issues;
- record accepted visual heads and later UX heads;
- preserve deferred or rejected directions and reasons;
- record wrong-project, wrong-root, and wrong-SHA hosting failures;
- update the process when repeated failures or improvements are discovered.

Only an explicit portfolio-governance replacement decision may close or supersede Issue #154.

## 12. Initial execution order

The first UI child is proposed Business 6 — World Feed. Its existing `apps/world-feed/` work is a technical and research baseline, not an approved visual product UI. The Phase 1 reference belongs under `reference/business-06-world-feed-v1/**`.

The intended review host is a dedicated `ai-revenue-world-feed` Pages project connected to the World Feed branch and reference root. A URL produced under `ai-revenue-personal-video-archive` is invalid World Feed evidence.

After each `UI_APPROVED` result, the user and CTO may open a separate UX issue for that Business while the UI factory proceeds to the next Business. Backend work for newly introduced Businesses remains frozen until UX approval and a separate backend authorization decision.
