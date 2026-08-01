# Product Demo → MVP → Pilot → Commercialization Gates

- Status: portfolio operating policy
- Owner: Web CTO under owner authority
- Permanent tracking issue: #154
- Canonical intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`
- Owner/operator contract: `OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md`
- Visual policy: `COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md`
- Backend policy: `BACKEND_MVP_OPERATING_POLICY.md`
- Deployment policy: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Decision

AI Revenue Lab no longer uses `UI_ONLY` as the portfolio-wide default.

The portfolio builds the smallest convincing product stage that can answer the current business question:

```text
product framing
→ competitive product demo
→ investor demo or MVP vertical slice
→ service-led or runtime pilot
→ commercial hardening
→ operating product
```

These are evidence stages, not mandatory sequential ceremonies. A Business may skip or combine stages when the value proposition requires it.

Examples:

- a media or travel Business may begin with an image-led investor demo;
- a verification engine may require a working frontend/backend vertical slice immediately;
- a consulting or education Business may begin with a service-led pilot using strong documents and a convincing demo;
- a marketplace may need realistic catalog, search, checkout simulation, and seller workflow before a real payment backend.

## 2. Governing principle

The gate system exists to prevent false claims and uncontrolled irreversible actions. It must not reduce a product to a weak static mockup.

The owner must be treated as a multidisciplinary expert across law, public administration, police studies and policing practice, computer science and software development, Korean institutional and field practice, product, and business. Gates must not be used to replace that professional judgment with generic AI supervision.

Within an authorized stage:

- implement the complete bounded story;
- use realistic synthetic content and high-quality assets;
- simulate missing runtime behavior when appropriate;
- build live backend behavior when it is essential to the evidence goal;
- proceed without repeated minor approval questions;
- preserve reversibility and truthful evidence;
- raise only concrete material risks and unresolved decisions;
- challenge the owner only through a specific, evidence-backed counterargument with a stronger alternative.

Do not use phase boundaries, generic legal cautions, or theoretical risks as a reason to omit the feature, image, interaction, or result that makes the product understandable.

## 3. Stage 0 — Product framing

Required:

- Business number, slug, and name;
- target customer and primary use moment;
- one-sentence product promise;
- primary result or transformation;
- direct competitors and adjacent leaders;
- differentiation thesis;
- evidence stage to build next;
- explicit non-goals for that bounded stage.

Framing should be brief. It is not permission to spend more effort on governance than on the product.

## 4. Stage 1 — Competitive product demo

### 4.1 Goal

Create a product experience that a customer or investor can understand and desire.

The demo should answer:

- What does the product do?
- Who is it for?
- What is the impressive moment?
- Why is it better or different?
- What would the complete product feel like?
- What evidence should be built next?

### 4.2 Normal scope

Use the states and interactions necessary to tell the product story. Four to seven states remain a useful default, not a hard ceiling.

A demo may include:

- image-led landing and editorial compositions;
- realistic feed, workspace, document, map, story, or dashboard surfaces;
- search, filtering, comparison, generation, transformation, and review simulation;
- deterministic AI-result fixtures;
- upload and processing simulation;
- version, approval, history, and collaboration simulation;
- mobile behavior;
- product-specific motion;
- service-led operator steps hidden behind the demo surface.

### 4.3 Quality gate

A competitive demo passes only when:

- reference research is visible in the result, not only documented;
- the visual system is at least credible beside the selected market references;
- imagery, typography, spacing, composition, content, and motion are professionally resolved;
- the product does not look like a generic template, school project, card wall, or AI-generated placeholder;
- the main value proposition can be demonstrated in under three minutes;
- desktop and mobile evidence are complete;
- console, asset, overflow, and accessibility blockers are absent;
- the exact head receives independent technical and visual review;
- the owner explicitly approves the direction.

Status vocabulary:

```text
DEMO_NOT_READY
DEMO_CONDITIONALLY_READY
DEMO_APPROVED
INVESTOR_DEMO_READY
```

`INVESTOR_DEMO_READY` requires the product story, visual quality, and key interaction to be strong enough for an external investor presentation.

## 5. Stage 2 — MVP vertical slice

### 5.1 Goal

Turn the strongest demo story into a usable bounded journey.

An MVP vertical slice may include frontend, backend, persistence, AI providers, or service-led operation. The architecture is chosen by the evidence goal, not by a blanket backend freeze.

### 5.2 Required contract

Define:

- one primary user and one primary success path;
- the minimum live versus simulated behavior;
- data and persistence boundary;
- authentication requirement, if any;
- model/provider requirement, if any;
- service-led manual steps, if any;
- failure and recovery behavior;
- measurable success event;
- operating-cost ceiling;
- demo-data and privacy boundary.

### 5.3 MVP quality gate

The MVP passes when:

- the primary journey completes end to end;
- the key product promise is experienced, not merely described;
- simulated and live behavior are documented truthfully;
- major loading, failure, retry, and completion states exist;
- visual quality from the approved demo is preserved or improved;
- mobile and keyboard behavior are usable where relevant;
- backend contracts and observability are sufficient for the pilot;
- the exact head receives independent review;
- the owner approves the pilot or external use.

Status vocabulary:

```text
MVP_NOT_READY
MVP_CONDITIONALLY_READY
MVP_APPROVED
PILOT_READY
```

## 6. Stage 3 — Service-led or runtime pilot

A pilot may be:

- **service-led** — the product surface is real while an operator performs bounded manual or AI-assisted work behind it;
- **runtime** — the product performs the core flow through live systems;
- **hybrid** — selected steps are automated and selected steps are operated manually.

Manual work is not failure when it is intentionally used to validate customer demand before automation.

Pilot requirements:

- named customer segment;
- bounded offer and price hypothesis;
- defined deliverables and response time;
- privacy and data-handling boundary;
- success, failure, and learning metrics;
- explicit operator workload;
- cost and revenue evidence;
- follow-up commercialization decision.

## 7. Stage 4 — Commercial hardening

Only after a Business earns evidence should work expand into broader production requirements:

- durable authentication and authorization;
- multi-tenant data isolation;
- migrations and retention;
- security review;
- billing and payments;
- provider redundancy and cost controls;
- accessibility and localization completeness;
- operational support, audit, and incident handling;
- scalable deployment and recovery.

Do not burden an early demo with every commercial requirement. Do not carry unacknowledged demo shortcuts into commercial operation.

## 8. Competitive and visual evidence

Every demo or MVP issue must include:

- three to five direct or adjacent product references;
- two to four high-quality visual or interaction references when relevant;
- a reference board containing actual screen evidence or precise screen-level notes;
- adopted patterns and rejected patterns;
- a side-by-side comparison of the result and benchmark;
- image and media source records;
- desktop and mobile captures;
- motion or video evidence when relevant;
- a written market-quality verdict.

See `COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md`.

## 9. Risk and truthfulness

Use realistic data and strong product claims within the chosen demo fiction. Keep truth through evidence rather than excessive visual warnings.

Do not:

- present synthetic transactions as real revenue;
- present staged AI output as a live provider result without disclosure;
- expose private data or secrets;
- perform irreversible external actions without authorization;
- copy protected brand identity or proprietary assets into a public product.

When a risk is manageable, mitigate it. Do not automatically remove the feature or weaken the entire design.

For legal, administrative, policing, public-sector, privacy, and software matters, operators must apply `OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md`: presume owner expertise, avoid boilerplate advice, distinguish law from field practice, and escalate only the concrete residual decision.

## 10. Publication and deployment

Demo publication, MVP deployment, and pilot exposure require explicit owner authorization for the exact target.

Execution follows `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

Publication does not freeze the product forever. Material visual or functional upgrades are expected, but they require a new exact-head review and a clear comparison against the current deployed baseline.

## 11. Existing Business upgrade rule

All existing Businesses are re-audited under the new standard.

Classification:

```text
A — externally credible; targeted refinement only
B — sound structure; major visual upgrade required
C — product journey and visual system require redesign
D — product thesis or market position requires reconsideration
```

For B and C Businesses:

- preserve valid backend and domain logic;
- open a dedicated `Visual Upgrade v2` or `Product Upgrade v2` issue;
- create a new branch and Draft PR;
- benchmark current market leaders again;
- produce before/after evidence;
- do not silently mutate the previously approved head.

## 12. Portfolio tracking

Issue #154 remains the portfolio queue, but it tracks product evidence rather than only UI status.

Use:

```text
Business XX — <Product>
Product thesis: DECIDED / REVIEW_REQUIRED
Current stage: FRAMED / COMPETITIVE_DEMO / INVESTOR_DEMO / MVP / PILOT / COMMERCIAL
Visual quality: NOT_AUDITED / A / B / C / D
Demo: NOT_STARTED / IN_PROGRESS / APPROVED / INVESTOR_READY
MVP: NOT_STARTED / IN_PROGRESS / APPROVED / PILOT_READY
Backend: NOT_NEEDED / SIMULATED / SERVICE_LED / LIVE_SLICE / HARDENING
Deployment: NOT_AUTHORIZED / AUTHORIZED / PRODUCTION_VERIFIED / BLOCKED
Commercial evidence: NONE / INTEREST / PILOT / REVENUE
Authoritative head: <SHA or none>
Next highest-value action: ...
```

## 13. Superseded defaults

The following former portfolio defaults are superseded:

- `UI_ONLY` for every new Business;
- mandatory UI → UX → backend sequencing regardless of evidence need;
- backend frozen until a complete UX matrix is approved;
- static local assets as the preferred answer for every visual category;
- risk avoidance through feature and expression reduction;
- technical validation as sufficient proof of UI quality;
- operator behavior that treats the owner as a supervised novice rather than a multidisciplinary expert.

The new default is:

```text
BUILD THE STRONGEST REVERSIBLE PRODUCT EVIDENCE FOR THE CURRENT BUSINESS QUESTION
```