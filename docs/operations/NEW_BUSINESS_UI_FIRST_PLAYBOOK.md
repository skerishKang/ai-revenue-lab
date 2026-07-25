# New Business UI-First Playbook

- Status: portfolio operating policy
- Owner: Web CTO
- Tracking issue: to be linked from the permanent open umbrella issue
- Applies to: every newly assigned or newly revived AI Revenue Lab Business

## 1. Purpose

AI Revenue Lab exists to test whether AI can create economically useful products through volume, speed, concurrency, real-time reaction, and personalization. New Businesses therefore begin with a product experience that can be understood and judged quickly, rather than with invisible backend infrastructure.

The first accepted milestone for a new Business is a polished, responsive, clickable product demo. Authentication, persistence, production databases, live model calls, billing, and full operational infrastructure follow only after the UI direction is accepted.

This playbook is reusable. Each new Business receives a child product issue and a child UI-demo issue under the permanent umbrella issue. The umbrella issue remains open as the portfolio-wide operating queue.

## 2. Non-negotiable design direction

Every new Business UI must follow all of these rules.

1. **Reference real products before designing.**
   - inspect three to five directly or indirectly comparable products;
   - inspect two to four strong award-winning or editorial design references;
   - separate information architecture, image treatment, typography, motion, and mobile behavior;
   - combine patterns from multiple references rather than cloning one product.

2. **Use image-led composition.**
   - acquire suitable images before implementation where the product depends on visual storytelling;
   - copy approved assets into the repository and serve them from local paths;
   - prohibit runtime hotlinking;
   - record source URL, creator or owner when available, license or usage basis, acquisition date, and intended use in `IMAGE_SOURCES.md`;
   - never treat an inaccessible or license-unclear asset as production-approved.

3. **Give each product a signature motion.**
   - define one product-specific transition or animated behavior that communicates the product concept;
   - prefer CSS transforms, opacity, masks, clipping, and small state-driven JavaScript;
   - preserve mobile performance and keyboard usability;
   - honor `prefers-reduced-motion`;
   - provide motion evidence as MP4, GIF, or equivalent reviewable capture when static screenshots are insufficient.

4. **Avoid generic AI-generated visual language.**
   - no default purple-blue gradient hero;
   - no decorative robot, brain, sparkles, or meaningless AI iconography;
   - no uniform grid of rounded glass cards as the default page structure;
   - no empty claims such as “revolutionize with AI”;
   - no fake metrics or decorative dashboards without a product purpose;
   - use product-specific editorial, document, map, story, media, timeline, or spatial metaphors instead.

5. **Treat award references as systems, not decoration.**
   - record what the reference teaches about first-three-second impact, visual hierarchy, spacing, motion, transition continuity, and mobile adaptation;
   - do not copy protected layouts, brand assets, copy, illustrations, or complete screens.

6. **Korean-first product language.**
   - original product copy is written in Korean unless a Business-specific decision says otherwise;
   - English is secondary where implemented;
   - missing translations fall back to Korean;
   - synthetic copy must sound like a real product, not a developer fixture or AI placeholder.

## 3. Product and workspace sequence

Do not create a production workspace merely because an idea was discussed.

Recommended sequence:

```text
candidate or numbered Business
→ product-boundary decision
→ reference dossier
→ static clickable reference demo
→ visual acceptance
→ implemented product workspace
→ runtime, identity, persistence, and live-model phases
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

A reference workspace is not proof of production readiness, canonical deployment, authentication, or a completed Business implementation.

After visual acceptance, the product implementation belongs under:

```text
apps/<stable-slug>/
```

unless a reviewed product decision explicitly chooses another isolated repository.

## 4. Minimum clickable-demo contract

A new Business demo should normally include five to seven meaningful states:

1. identity-rich landing or home state;
2. primary input, selection, or onboarding state;
3. visible processing or transformation state;
4. representative result state;
5. result detail, evidence, explanation, or personalization reason;
6. feedback, reaction, or next-action state;
7. archive, history, collection, or operator state only when central to the product.

The demo must contain at least one complete clickable path:

```text
Home
→ Start
→ Input or selection
→ Processing
→ Result
→ Feedback or next action
```

The result must explain the Business value within 30–90 seconds of guided use.

## 5. Required reference dossier

Before implementation, the Web CTO records:

- product promise in one sentence;
- target user and primary use moment;
- direct and indirect reference products;
- award or editorial design references;
- patterns to adopt and patterns to reject;
- chosen visual metaphor;
- typography and density direction;
- image plan and source constraints;
- signature motion;
- desktop and mobile information hierarchy;
- overlap and boundary with existing Businesses;
- minimum demo flow;
- explicit non-goals.

A reference must be cited by URL in the dossier, but third-party assets must not be copied unless their use is permitted and documented.

## 6. Model and role allocation

### Web CTO

The Web CTO owns:

- Business-number and product-boundary verification;
- duplicate and overlap review;
- reference research;
- design direction and acceptance criteria;
- task decomposition and repository scope;
- image-source and license review;
- exact-head review of implementation evidence;
- final visual, product, security, and merge judgment.

The CTO does not accept worker reports as proof without checking repository state and evidence.

### Web implementation model

Use the available high-volume Web development model for rapid implementation after the task contract is fixed. It may own HTML, CSS, JavaScript, synthetic fixtures, responsive behavior, and focused tests, but it must not silently redefine the product, alter another Business, or declare final CTO acceptance.

### Local implementation and validation model

Use the Local model and local provider where they add leverage:

- repetitive asset preparation and path normalization;
- synthetic fixture generation without private user data;
- local-browser rendering and interaction checks;
- responsive overflow checks;
- motion timing and reduced-motion verification;
- console, network, and asset-path validation;
- exact-head runtime tests when authentication, API, storage, model calls, or other U3 behavior is introduced.

Do not require full Local validation for every text, color, or spacing correction. Local work is risk-based.

## 7. UI risk levels and validation

### U0 — copy-only

Examples: product text, labels, helper text, translation correction.

Required:

- focused source inspection;
- no unrelated file changes;
- browser check only when wrapping or layout may change.

Local validation is normally skipped.

### U1 — visual tokens

Examples: color, font size, spacing, radius, shadow, image crop.

Required:

- focused visual evidence;
- desktop or mobile capture for affected state;
- accessibility contrast check when relevant.

Local validation is normally skipped unless the change is difficult to reproduce remotely.

### U2 — layout, responsive behavior, and motion

Examples: new screen structure, navigation, card movement, animation, breakpoint behavior.

Required:

- desktop and mobile captures;
- complete click-flow evidence;
- motion capture when static evidence is insufficient;
- keyboard and reduced-motion checks;
- Local browser validation when Web evidence is incomplete or unreliable.

### U3 — runtime and product data

Examples: identity, authorization, API, persistence, uploads, live model provider, billing, private data, production deployment.

Required:

- exact-head Local validation;
- relevant full test suite;
- security and privacy review;
- synthetic or explicitly approved test data;
- evidence that unauthorized access fails;
- production or staging verification only after merge and deployment.

## 8. Acceptance evidence for each UI demo

Each child UI issue must require:

- exact branch and head commit;
- changed-path list and scope confirmation;
- 1440px-class desktop screenshots;
- approximately 390px mobile screenshots;
- MP4 or GIF for signature motion when relevant;
- completed click-flow recording or state-by-state evidence;
- `IMAGE_SOURCES.md` with no undocumented hotlinks;
- no console errors in the reviewed flow;
- keyboard-operable primary actions;
- reduced-motion behavior;
- focused automated contract checks where practical;
- truthful statement of synthetic, mocked, local, preview, staging, or production behavior.

A successful static build is not proof of correct visual behavior, and a branch preview is not production.

## 9. Child issue template

Create a separate child issue for each new Business UI. Use this structure:

```markdown
## Purpose
Build the first polished, responsive, clickable UI demo for Business XX — <Product>.

## Parent policy
- Permanent umbrella issue: #<issue>
- Operating playbook: `docs/operations/NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`

## Product promise
> <one sentence>

## Required research
- 3–5 comparable products
- 2–4 award/editorial references
- reference analysis and rejection notes

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
- image-led product composition
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

The portfolio-wide umbrella issue remains open.

It is used to:

- link the authoritative playbook;
- record the ordered Business UI queue;
- link each product-decision and UI-demo child issue;
- record accepted reference demos and deployments;
- preserve deferred or rejected directions without losing the idea;
- update the process when a repeated failure or improvement is discovered.

Completing one Business or one UI demo does not close the umbrella issue. Only an explicit portfolio-governance decision may replace or close it.

## 11. Initial execution order

The default starting point is Business 6 — World Feed because it is an original AI Revenue Lab product direction, has an existing research workspace, and can demonstrate volume, concurrency, speed, and personalization through a highly visual interface.

After each accepted demo, the CTO selects the next Business based on:

1. clarity of product promise;
2. availability of useful visual references and lawful assets;
3. ability to demonstrate the idea in 30–90 seconds;
4. reuse of an already accepted pattern without making products visually identical;
5. expected business or research value;
6. current Web and Local model capacity.

The queue may change, but every change is recorded in the permanent umbrella issue rather than being lost in conversation history.
