# UI → UX → Backend Phase Gates

- Status: portfolio operating policy
- Owner: Web CTO
- Permanent tracking issue: #154
- Current portfolio mode: `UI_ONLY`
- Applies to: every new or revived AI Revenue Lab Business unless a separate approved issue explicitly states otherwise

## 1. Decision

For the current portfolio expansion period, AI Revenue Lab builds and reviews new Businesses in this strict order:

```text
Phase 0 — product framing
→ Phase 1 — UI visual design
→ UI approval gate
→ Phase 2 — UX and interaction design
→ UX approval gate
→ Phase 3 — backend authorization decision
→ Phase 4 — backend and runtime implementation
```

A later phase must not begin merely because a worker has capacity or because the technology is easy to add. Each phase begins only after the previous gate is explicitly accepted.

The current default is **Phase 1 UI work only**. New Business work must not expand into UX or backend scope unless the user and Web CTO authorize the next phase for that specific Business.

## 2. Phase 0 — Product framing

Phase 0 is intentionally small. It exists only to prevent a beautiful interface from representing an undefined or duplicate product.

Required:

- proposed or canonical Business number;
- stable slug and Korean/English name;
- one-sentence product promise;
- target user and primary use moment;
- primary visual result or artifact;
- overlap and boundary with existing Businesses;
- explicit UI-only non-goals.

Phase 0 does not authorize application architecture, databases, authentication, providers, deployment, or final UX flows.

## 3. Phase 1 — UI visual design

### 3.1 Goal

Produce a visually convincing product identity and representative screen system before optimizing task flow or implementing runtime behavior.

UI answers:

- What does this product look and feel like?
- What is the visual hierarchy?
- What imagery, typography, color, spacing, density, and composition define it?
- What makes it look like this product rather than a generic AI service?
- What signature motion communicates the concept?
- Does the product remain coherent on desktop and mobile?

### 3.2 Required UI scope

Normally create 4–7 representative visual states, such as:

- landing or home;
- primary feed, workspace, publication, map, story, or dashboard;
- item or result detail;
- personalization, evidence, transformation, or comparison state;
- collection, archive, or secondary surface when visually central;
- mobile composition;
- one signature-motion state.

The exact states vary by Business. They are selected to prove the visual system, not to simulate every use case.

### 3.3 Permitted interaction

Minimal interaction is permitted only to review visual composition and motion:

- next/previous state;
- tab or view switching;
- opening and closing a visual panel;
- hover, focus, scroll, or reveal behavior;
- deterministic motion preview;
- switching between desktop-like visual states in a static prototype.

These interactions do **not** constitute UX approval. A visually clickable reference is still a Phase 1 UI artifact.

### 3.4 Prohibited UI-phase expansion

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
- payments, billing, notifications, or production deployment.

Synthetic content and static local assets are the default.

### 3.5 UI approval gate

Phase 1 passes only when all of the following are accepted:

- reference research is documented;
- imagery is repository-local and source-documented;
- Korean-first product copy is credible;
- desktop and mobile visual evidence is complete;
- signature motion is reviewable;
- the product avoids generic AI-generated visual language;
- major states share one coherent visual system;
- no obvious overflow, broken asset, console error, or inaccessible primary visual control remains;
- the Web CTO reviews the exact head;
- the user explicitly approves the visual direction.

Approval status vocabulary:

- `UI_NOT_READY`
- `UI_CONDITIONALLY_READY`
- `UI_APPROVED`

Only `UI_APPROVED` authorizes a separate UX child issue.

After approval, the accepted UI becomes the visual baseline. Material changes to typography, color, image direction, layout grammar, or signature motion must be documented rather than silently introduced during UX work.

### 3.4 Phase 1 UI deployment after approval

`UI_APPROVED` does not authorize merge or deployment. Deployment requires separate user authorization.

When the user separately authorizes deployment, the default target is the dedicated Business Production project. Preview is used only when a Business-specific issue explicitly requires it (see `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` Section 13).

An approved Phase 1 UI deployment:

- publishes only the already accepted static UI reference and its repository-local assets;
- uses a Business-specific dedicated Cloudflare Pages project;
- does not authorize source changes, a new commit, branch movement, PR Ready status, merge, or issue closure unless separately requested;
- does not convert review controls or synthetic states into accepted UX;
- does not authorize authentication, persistence, APIs, databases, live AI, analytics, billing, or other backend work;
- must report the deployed exact commit SHA and preserve the approved visual head;
- must record rollback baseline deployment ID before deploying;
- must execute immediate Production smoke acceptance after deploying;
- must be recorded as deployment evidence separately from UI, UX, and backend gate status.

A deployment is not proof of UX approval, backend authorization, production readiness, or product completion.

## 4. Phase 2 — UX and interaction design

### 4.1 Entry condition

Phase 2 may begin only after the same Business has `UI_APPROVED` evidence.

### 4.2 Goal

Turn the accepted visual system into an understandable, efficient, accessible, and complete user experience using synthetic data and frontend-only behavior.

UX answers:

- What does the user do first?
- What is the shortest successful path?
- How does navigation preserve context?
- What happens during loading, emptiness, errors, recovery, and completion?
- What feedback follows each action?
- What information is shown now versus progressively disclosed?
- Can the main task be completed with keyboard and mobile input?

### 4.3 Required UX scope

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

### 4.4 UX approval gate

Phase 2 passes only when:

- the primary journey is complete and understandable;
- all required states are inventoried and represented;
- navigation and interaction semantics are consistent;
- keyboard and mobile behavior are verified;
- critical error and recovery paths are present;
- the accepted UI visual baseline is preserved or approved changes are documented;
- the Web CTO reviews the exact head;
- the user explicitly approves the experience.

Approval status vocabulary:

- `UX_NOT_READY`
- `UX_CONDITIONALLY_READY`
- `UX_APPROVED`

Only `UX_APPROVED` permits a backend authorization decision.

## 5. Phase 3 — Backend authorization decision

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

## 6. Phase 4 — Backend and runtime implementation

Only after authorization may work include:

- authentication and product-local authorization;
- APIs and server-side validation;
- databases and migrations;
- uploads and private records;
- live AI providers and model routing;
- crawling or current-data ingestion;
- persistence and audit history;
- billing and payments;
- authorized runtime and Production deployment, with optional staging only when explicitly required.

Backend work must preserve the approved UI and UX contracts. It must not redesign the product as an incidental consequence of implementation.

## 7. Current portfolio freeze

Until this policy is explicitly changed:

- new Business work is limited to Phase 0 and Phase 1;
- UI issues are processed one by one or in controlled parallel batches;
- a Business that receives `UI_APPROVED` may move to a separate UX issue;
- backend work for newly introduced Businesses remains frozen;
- existing production or backend maintenance may continue only through already authorized product-specific issues;
- the permanent Issue #154 remains open and records each Business phase and gate result.

## 8. Issue structure

Use separate issues for separate gates:

```text
Product/number decision issue
UI-only issue
UX-only issue after UI approval
Backend decision issue after UX approval
Backend implementation issues only after authorization
```

Do not create one issue titled “UI/UX/MVP” that mixes visual design, interaction design, databases, authentication, and deployment.

## 9. Phase evidence in Issue #154

Record each Business in the permanent queue using this format:

```text
Business XX — <Product>
Product status: proposed / canonical
UI: NOT_STARTED / IN_PROGRESS / UI_NOT_READY / UI_CONDITIONALLY_READY / UI_APPROVED
UX: BLOCKED_BY_UI / NOT_STARTED / IN_PROGRESS / UX_NOT_READY / UX_CONDITIONALLY_READY / UX_APPROVED
Backend: FROZEN / DECISION_PENDING / DEFERRED / AUTHORIZED / IN_PROGRESS
Current child issue: #...
Accepted visual head: <SHA or none>
Accepted UX head: <SHA or none>
Next action: ...
```

This keeps visual approval, experience approval, and runtime implementation from being confused.
