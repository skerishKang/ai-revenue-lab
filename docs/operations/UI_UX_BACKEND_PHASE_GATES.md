# UI → UX → Backend Phase Gates

- Status: portfolio operating policy
- Owner: Web CTO
- Permanent tracking issue: #154
- Current portfolio mode: `UI_ONLY`
- Hosted-review runbook: `docs/operations/CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md`
- Applies to: every new or revived AI Revenue Lab Business unless a separate approved issue explicitly states otherwise

## 1. Decision

AI Revenue Lab builds and reviews new Businesses in this strict order:

```text
Phase 0 — product framing
→ Phase 1 — UI visual design
→ UI approval gate
→ Phase 2 — UX and interaction design
→ UX approval gate
→ Phase 3 — backend authorization decision
→ Phase 4 — backend and runtime implementation
```

A later phase does not begin because a worker has capacity, a URL exists, a build passes, or a technology is easy to add. Each phase begins only after the previous gate is explicitly accepted.

The current default is **Phase 1 UI work only**. New Business work must not expand into UX or backend scope unless the user and Web CTO authorize the next phase for that specific Business.

## 2. Independent operating dimensions

The following dimensions must be tracked separately:

1. **Git state** — repository, branch, exact SHA, changed paths, PR state.
2. **Hosted-review state** — Pages project, connected repository, branch, root directory, deployed SHA, URL, and access policy.
3. **Phase state** — UI, UX, backend, and release approvals.

A change in one dimension does not automatically change either of the others.

Examples:

- a Draft branch may have a valid hosted-review URL;
- a green Pages deployment may still be invalid because it used the wrong project or root;
- `HOSTED_REVIEW_READY` may coexist with `UI_NOT_READY`;
- `UI_APPROVED` does not authorize backend work;
- Cloudflare's field named `Production branch` does not mean product production approval.

## 3. Phase 0 — Product framing

Phase 0 is intentionally small. It prevents a polished interface from representing an undefined or duplicate product.

Required:

- proposed or canonical Business number;
- stable slug and Korean/English name;
- one-sentence product promise;
- target user and primary use moment;
- primary visual result or artifact;
- overlap and boundary with existing Businesses;
- explicit UI-only non-goals.

Phase 0 does not authorize application architecture, databases, authentication, providers, final UX flows, or a product production release.

## 4. Phase 1 — UI visual design

### 4.1 Goal

Produce a visually convincing product identity and representative screen system before optimizing task flow or implementing runtime behavior.

UI answers:

- What does this product look and feel like?
- What is the visual hierarchy?
- What imagery, typography, color, spacing, density, and composition define it?
- What makes it look like this product rather than a generic AI service?
- What signature motion communicates the concept?
- Does the visual system remain coherent on desktop and mobile?

### 4.2 Required UI scope

Normally create 4–7 representative visual states, such as:

- landing or home;
- primary feed, workspace, publication, map, story, or dashboard;
- item or result detail;
- personalization, evidence, transformation, or comparison state;
- collection, archive, or secondary surface when visually central;
- mobile composition;
- one signature-motion state.

The states prove the visual system. They do not simulate every use case or finalize UX.

### 4.3 Permitted interaction

Minimal interaction is permitted only to review visual composition and motion:

- next/previous state;
- tab or view switching;
- opening and closing a visual panel;
- hover, focus, scroll, or reveal behavior;
- deterministic motion preview;
- switching between representative visual states in a static prototype.

These interactions do not constitute UX approval.

### 4.4 Permitted hosted review

A Phase 1 static reference may be connected to a **dedicated Cloudflare Pages project** before UI approval so the user and Web CTO can inspect it in a normal browser.

Hosted review is permitted only when:

- the Pages project belongs to the intended Business or approved shared host;
- repository, branch, root directory, and exact deployed SHA are verified;
- the hosted content is synthetic or otherwise approved;
- the URL is classified as review infrastructure;
- the PR and phase status remain unchanged;
- the connection follows `CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md`.

A dedicated hosted-review connection is not a product production release, does not require a merge to `main`, and does not authorize UX or backend work.

### 4.5 Prohibited UI-phase expansion

Do not implement or finalize:

- complete onboarding or end-to-end task journeys;
- final information architecture or navigation semantics;
- comprehensive loading, empty, validation, error, recovery, and permission states;
- real forms or durable user input;
- real personalization or recommendation logic;
- authentication or authorization;
- API contracts or network calls;
- databases or persistence;
- live AI providers or model routing;
- crawling or live-data ingestion;
- payments, billing, notifications, or product production deployment.

Do not confuse the final item with an isolated static hosted-review connection. Product production deployment remains prohibited in Phase 1; correctly scoped hosted review is allowed under section 4.4.

Synthetic content and repository-local assets are the default.

### 4.6 UI approval gate

Phase 1 passes only when all of the following are accepted:

- reference research is documented;
- imagery is repository-local and source-documented;
- Korean-first product copy is credible;
- desktop and mobile visual evidence is complete;
- signature motion is reviewable;
- the product avoids generic AI-generated visual language;
- major states share one coherent visual system;
- no obvious overflow, broken asset, console error, or inaccessible primary visual control remains;
- any shared hosted URL has the correct project identity, root, branch, and exact SHA;
- the Web CTO reviews the exact head and actual rendered UI;
- the user explicitly approves the visual direction.

Approval status vocabulary:

- `UI_NOT_READY`
- `UI_CONDITIONALLY_READY`
- `UI_APPROVED`

Only `UI_APPROVED` authorizes a separate UX child issue.

After approval, the accepted UI becomes the visual baseline. Material changes to typography, color, image direction, layout grammar, or signature motion must be documented rather than silently introduced during UX work.

## 5. Phase 2 — UX and interaction design

### 5.1 Entry condition

Phase 2 may begin only after the same Business has `UI_APPROVED` evidence.

### 5.2 Goal

Turn the accepted visual system into an understandable, efficient, accessible, and complete user experience using synthetic data and frontend-only behavior.

UX answers:

- What does the user do first?
- What is the shortest successful path?
- How does navigation preserve context?
- What happens during loading, emptiness, errors, recovery, and completion?
- What feedback follows each action?
- What information is shown now versus progressively disclosed?
- Can the main task be completed with keyboard and mobile input?

### 5.3 Required UX scope

Depending on the Business:

- information architecture;
- primary and secondary journeys;
- navigation and back behavior;
- form and selection behavior;
- loading, empty, validation, error, retry, and completion states;
- progressive disclosure;
- accessibility semantics and keyboard behavior;
- mobile interaction behavior;
- synthetic feedback and personalization loop;
- usability evidence for the main journey.

Use static fixtures, browser memory, and deterministic mock behavior. UX work still does not require a backend.

A dedicated hosted-review URL may continue to serve UX evidence, but it must remain correctly connected and must not be relabelled as a product production release.

### 5.4 UX approval gate

Phase 2 passes only when:

- the primary journey is complete and understandable;
- all required states are inventoried and represented;
- navigation and interaction semantics are consistent;
- keyboard and mobile behavior are verified;
- critical error and recovery paths are present;
- the accepted UI visual baseline is preserved or approved changes are documented;
- hosted evidence, when used, maps to the reviewed exact head;
- the Web CTO reviews the exact head;
- the user explicitly approves the experience.

Approval status vocabulary:

- `UX_NOT_READY`
- `UX_CONDITIONALLY_READY`
- `UX_APPROVED`

Only `UX_APPROVED` permits a backend authorization decision.

## 6. Phase 3 — Backend authorization decision

Phase 3 is a decision gate, not automatic implementation.

After UX approval, the Web CTO prepares a short backend decision that answers:

- Does this Business need a backend for the next evidence goal?
- What is the smallest required backend slice?
- Which data must persist?
- Is authentication required now?
- Is a live AI provider required now?
- Can the next business test still use static or local-only behavior?
- What privacy, security, cost, and operational risks are introduced?
- Which Web and Local models should implement and validate it?

Possible decisions:

- `BACKEND_DEFERRED`
- `FRONTEND_ONLY_PILOT`
- `LOCAL_RUNTIME_ONLY`
- `BACKEND_AUTHORIZED`

No backend implementation issue is opened until the user explicitly approves `BACKEND_AUTHORIZED` or another narrowly defined runtime decision.

## 7. Phase 4 — Backend and runtime implementation

Only after authorization may work include:

- authentication and product-local authorization;
- APIs and server-side validation;
- databases and migrations;
- uploads and private records;
- live AI providers and model routing;
- crawling or current-data ingestion;
- persistence and audit history;
- billing and payments;
- staging and product production deployment.

Backend work must preserve the approved UI and UX contracts. It must not redesign the product as an incidental consequence of implementation.

Product production release requires separate product-specific evidence. A Pages URL created for UI or UX review cannot be promoted by terminology alone.

## 8. Current portfolio freeze

Until this policy is explicitly changed:

- new Business work is limited to Phase 0 and Phase 1;
- UI issues are processed one by one or in controlled parallel batches;
- correctly isolated static hosted review is allowed;
- a Business that receives `UI_APPROVED` may move to a separate UX issue;
- backend work for newly introduced Businesses remains frozen;
- existing production or backend maintenance may continue only through already authorized product-specific issues;
- the permanent Issue #154 remains open and records each Business phase and gate result.

## 9. Issue structure

Use separate issues for separate gates:

```text
Product/number decision issue
UI-only issue
UX-only issue after UI approval
Backend decision issue after UX approval
Backend implementation issues only after authorization
```

A hosted-review connection may be recorded within the UI or UX issue because it is evidence infrastructure, not a new product phase. A separate connection-fix issue may be used when account-side configuration is materially wrong.

Do not create one issue titled “UI/UX/MVP” that mixes visual design, interaction design, databases, authentication, and release work.

## 10. Phase and hosting evidence in Issue #154

Record each Business in the permanent queue using this format:

```text
Business XX — <Product>
Product status: proposed / canonical
UI: NOT_STARTED / IN_PROGRESS / UI_NOT_READY / UI_CONDITIONALLY_READY / UI_APPROVED
UX: BLOCKED_BY_UI / NOT_STARTED / IN_PROGRESS / UX_NOT_READY / UX_CONDITIONALLY_READY / UX_APPROVED
Backend: FROZEN / DECISION_PENDING / DEFERRED / AUTHORIZED / IN_PROGRESS
Hosted review: NOT_CONFIGURED / CONNECTION_PENDING / WRONG_PROJECT / WRONG_ROOT / WRONG_SHA / READY / FAILED
Current child issue: #...
Pages project: <name or none>
Hosted URL: <URL or none>
Expected hosted SHA: <SHA or none>
Accepted visual head: <SHA or none>
Accepted UX head: <SHA or none>
Next action: ...
```

This keeps Git state, hosting state, visual approval, experience approval, backend authorization, and product production release from being confused.

## 11. Evidence validity rules

The following are invalid as sole evidence:

- worker completion reports;
- GitHub screenshots that cannot be inspected at useful scale;
- successful builds without rendered review;
- Cloudflare bot comments from an unrelated Pages project;
- a URL without project, branch, root, and SHA verification;
- a hosted static reference labelled as production;
- a Pages primary branch interpreted as product release authorization.

When a user needs to judge a static UI, a correctly connected dedicated hosted-review site is the default inspection method. Screenshots remain supporting evidence, not a substitute for an available interactive review surface.
