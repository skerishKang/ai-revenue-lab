# New Business UI-First Playbook

- Status: portfolio operating policy
- Owner: Web CTO
- Permanent tracking issue: #154
- Candidate backlog: `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`
- Applies to: every newly assigned or revived AI Revenue Lab Business

## 1. Purpose

AI Revenue Lab tests whether AI can create economically useful products through volume, speed, concurrency, real-time reaction, personalization, and measurable revenue evidence.

A new Business therefore begins with a product experience that can be understood and judged quickly. Its first accepted milestone is a polished, responsive, clickable demo. Authentication, persistence, production databases, live model calls, billing, and full operations follow only after the UI direction is accepted.

Issue #154 is the permanent open parent. Each selected Business receives separate product-decision and UI-demo child issues linked to this playbook. Completing one child does not close Issue #154.

## 2. Required design direction

Every new Business UI must satisfy all of the following.

### 2.1 Research real products first

Before designing:

- inspect 3–5 directly or indirectly comparable products;
- inspect 2–4 award-winning or strong editorial design references;
- analyze information architecture, image treatment, typography, motion, transition continuity, and mobile behavior separately;
- combine patterns from multiple references rather than cloning one site;
- record both adoption decisions and rejection reasons.

Third-party brand assets, complete screens, copy, layouts, or illustrations must not be copied without permission.

### 2.2 Use image-led composition

Where visual storytelling is central:

- acquire suitable images before implementation;
- store approved assets inside the repository and serve them from local paths;
- prohibit runtime hotlinking;
- record source URL, creator or owner when available, license or usage basis, acquisition date, and intended use in `IMAGE_SOURCES.md`;
- keep reference-only and production-approved assets clearly distinguished;
- do not treat inaccessible or license-unclear material as production-approved.

### 2.3 Define one signature motion

Each Business receives one product-specific motion that communicates the product concept.

Prefer:

- CSS transform, opacity, masks, clipping, and restrained state-driven JavaScript;
- motion that supports navigation, hierarchy, or transformation;
- mobile-safe performance;
- keyboard-compatible interaction;
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
- developer terminology is kept out of ordinary user flows.

## 3. Product and workspace sequence

Do not create a production workspace solely because an idea was discussed.

```text
candidate or proposed Business
→ product-boundary and numbering decision
→ reference dossier
→ static clickable reference demo
→ visual acceptance
→ implemented product workspace
→ runtime, identity, persistence, live models, billing, and production
```

Default reference workspace:

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

After visual acceptance, product implementation normally belongs under:

```text
apps/<stable-slug>/
```

A reference workspace is not proof of canonical numbering, authentication, persistence, deployment, production readiness, or live-model operation.

## 4. Minimum clickable-demo contract

A first demo normally contains 5–7 meaningful states:

1. identity-rich landing or home;
2. primary input, selection, or onboarding;
3. visible processing or transformation;
4. representative result;
5. result detail, evidence, explanation, or personalization reason;
6. feedback, reaction, or next action;
7. archive, history, collection, or operator state only when central.

It must include at least one complete clickable flow:

```text
Home
→ Start
→ Input or selection
→ Processing
→ Result
→ Feedback or next action
```

The product value must be understandable within a guided 30–90 second demonstration.

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
- desktop and mobile hierarchy;
- overlap and boundary with existing Businesses;
- minimum demo flow;
- explicit non-goals.

## 6. Model and role allocation

### Web CTO

The Web CTO owns:

- Business-number and product-boundary verification;
- duplicate and overlap review;
- reference research and design direction;
- task decomposition and repository scope;
- image-source and license review;
- exact-head evidence review;
- final visual, product, security, and merge judgment.

Worker reports are not proof without repository and evidence verification.

### Web implementation model

Use the available high-volume Web development model after the contract is fixed. It may implement HTML, CSS, JavaScript, synthetic fixtures, responsive behavior, and focused tests, but it must not silently redefine the product, change another Business, or declare final CTO acceptance.

### Local model and local provider

Use Local selectively for:

- repetitive asset preparation and path normalization;
- synthetic fixture generation without private user data;
- local-browser rendering and interaction checks;
- responsive overflow checks;
- motion timing and reduced-motion verification;
- console, network, and asset-path validation;
- exact-head runtime tests for authentication, API, storage, live models, billing, or other U3 work.

Do not require full Local validation for every text, color, spacing, or small image-crop correction.

## 7. UI risk levels

### U0 — copy-only

Examples: labels, helper text, translations.

Required:

- focused source inspection;
- no unrelated changes;
- browser check only when wrapping or layout may change.

Local validation is normally skipped.

### U1 — visual tokens

Examples: color, type size, spacing, radius, shadow, image crop.

Required:

- focused visual evidence;
- capture of the affected state;
- accessibility contrast review when relevant.

Local validation is normally skipped unless remote evidence is unreliable.

### U2 — layout, responsive behavior, and motion

Examples: screen structure, navigation, card movement, animation, breakpoints.

Required:

- desktop and mobile captures;
- complete click-flow evidence;
- motion evidence when static captures are insufficient;
- keyboard and reduced-motion checks;
- Local browser validation when Web evidence is incomplete.

### U3 — runtime and product data

Examples: identity, authorization, API, persistence, uploads, live model providers, billing, private data, production deployment.

Required:

- exact-head Local validation;
- relevant full test suite;
- security and privacy review;
- synthetic or explicitly approved test data;
- unauthorized-access denial evidence;
- staging or production verification only after merge and deployment.

## 8. Required acceptance evidence

Each child UI issue requires:

- exact branch and head commit;
- changed-path list and scope confirmation;
- 1440px-class desktop screenshots;
- approximately 390px mobile screenshots;
- MP4 or GIF for signature motion when relevant;
- complete click-flow recording or state-by-state evidence;
- `IMAGE_SOURCES.md` with no undocumented hotlinks;
- no console errors in the reviewed flow;
- keyboard-operable primary actions;
- reduced-motion behavior;
- focused automated contract checks where practical;
- truthful description of synthetic, mocked, local, preview, staging, and production behavior.

A successful build is not proof of correct visual behavior. A branch preview is not production.

## 9. Reusable child issue template

```markdown
## Purpose
Build the first polished, responsive, clickable UI demo for Business XX — <Product>.

## Parent policy
- Permanent umbrella issue: #154
- Playbook: `docs/operations/NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`
- Candidate backlog: `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md`

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

## Required flow
Home → Start → Input/selection → Processing → Result → Feedback/next action

## Visual requirements
- image-led composition
- product-specific signature motion
- Korean-first copy
- no generic AI visual language
- responsive desktop and mobile behavior

## Explicit non-goals
- production authentication
- production database
- billing
- live private-user data
- production claim

## Acceptance evidence
- exact head
- changed-path scope
- desktop/mobile captures
- motion evidence
- click-flow evidence
- image-source manifest
- console/network check
- focused tests
```

## 10. Permanent umbrella issue rules

Issue #154 remains open and is used to:

- link this playbook and the candidate backlog;
- record the ordered UI queue;
- link product-decision and UI-demo child issues;
- record accepted reference directions, demos, and deployments;
- preserve deferred or rejected directions and reasons;
- update the process when repeated failures or improvements are discovered;
- record the next Business selected by the CTO.

Only an explicit portfolio-governance replacement decision may close or supersede Issue #154.

## 11. Initial execution order

The default first child is Business 6 — World Feed after its numbering and current workspace are reverified. It is an original AI Revenue Lab direction and can demonstrate volume, concurrency, speed, real-time information, and personalization through a highly visual product.

After each accepted demo, the CTO selects the next candidate based on:

1. clarity of product promise;
2. availability of lawful and useful visual assets;
3. ability to demonstrate value in 30–90 seconds;
4. opportunity to reuse a proven pattern without making products visually identical;
5. business or research value;
6. current Web and Local model capacity.

Every queue change is recorded in Issue #154 rather than being left only in conversation history.
