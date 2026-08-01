# Operations Documents

- `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md` — canonical portfolio mission: prove the excellence and commercial usefulness of AI through competitive demos, MVPs, pilots, and operating products.
- `OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md` — mandatory owner-expertise baseline and limits on generic, unsolicited operator advice.
- `UI_UX_BACKEND_PHASE_GATES.md` — product evidence stages: framing → competitive demo → investor demo or MVP → pilot → commercial hardening.
- `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — competitive product demo and MVP implementation playbook; file name retained for compatibility.
- `COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md` — screen-level benchmarking, imagery, typography, composition, motion, and investor/customer visual-quality gates.
- `BACKEND_MVP_OPERATING_POLICY.md` — backend modes, vertical slices, service-led pilots, data, providers, observability, testing, cost, and hardening.
- `PORTFOLIO_PRODUCT_QUALITY_AUDIT.md` — portfolio-wide A/B/C/D audit and Visual Upgrade v2 / Product Upgrade v2 program.
- `POLICY_CONSISTENCY_AUDIT.md` — repository policy audit plus the required external GitHub governance control-plane check.
- `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` — approved exact-head demo deployments, canonical Production deployments, acceptance, and recovery.
- `../portfolio/BUSINESS_CANDIDATE_BACKLOG.md` — idea-preservation backlog and proposed Business map.
- Permanent portfolio tracking issue: `#154`.

## Current portfolio mode

```text
MVP_AND_VISUAL_UPGRADE
```

The former portfolio-wide `UI_ONLY` default is superseded.

For each Business, choose the strongest reversible evidence stage required by the current business question:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
OPERATING_PRODUCT
```

A media product may begin with an image-led investor demo. A verification or data product may require a live frontend/backend vertical slice. A consulting product may use a service-led pilot. The evidence goal determines scope.

## Product-quality standard

Technical correctness is the minimum floor.

A Business is not visually approved merely because:

- it has the required number of screens;
- it uses repository-local SVGs;
- it has no overflow or console errors;
- it lists several reference products;
- it is deployed.

Substantial product review must separately judge:

```text
TECHNICAL_UI_PASS
VISUAL_QUALITY_PASS
MARKET_REFERENCE_PASS
INVESTOR_DEMO_PASS
```

Comparable products must be studied at the screen level, and the influence must be visible in the resulting product.

## Owner expertise and operator standard

The owner is a **multidisciplinary expert decision-maker** with formal education and practical experience across law, public administration, police studies and policing practice, computer science and software development, public-sector decision-making, product strategy, and AI-assisted implementation.

This is not merely a rule against calling the owner a novice. It is an affirmative expertise baseline that every operator and AI agent must use.

The owner is the final product, business, legal-risk, policy, Korean institutional and field-practice, and technical decision-maker.

Operators must:

- presume expert knowledge rather than provide introductory supervision;
- identify only concrete, material risks relevant to the action;
- avoid generic legal, administrative, privacy, security, or software lectures unless requested;
- distinguish statutory rules, formal procedures, institutional customs, and actual Korean field practice;
- recognize that the owner may have stronger domain and field knowledge than a general-purpose AI model;
- preserve intended product value and propose practical mitigations before deleting features, imagery, language, or ambition;
- proceed within authorized scope without repeated minor questions;
- challenge the owner only with a specific, evidence-backed counterargument and a stronger alternative;
- distinguish implementation facts from expert product judgment;
- optimize for visible product and business evidence rather than ceremony.

The full mandatory contract is `OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md`.

Default instructions:

```text
Treat the owner as a multidisciplinary expert.
Add decision value; do not add generic supervision.

Do not make the safest possible prototype.
Make the strongest reversible product evidence that truthfully demonstrates the Business.
```

## Portfolio-wide renewal

Every existing Business is audited and classified:

```text
A — externally credible; targeted refinement only
B — sound structure; major visual upgrade required
C — product journey and visual system require redesign
D — thesis or market position requires reconsideration
```

Preserve strong backend and domain logic. Replace weak UI. Reframe products that do not merit further investment.

Use controlled upgrade waves and before/after evidence.

## Backend standard

Backend work is no longer frozen by default.

Choose explicitly:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

Build backend behavior when it is necessary to prove the product. Keep it bounded to the primary evidence journey and stage-appropriate risk.

## Deployment lanes

Deployment follows `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

### Approved exact-head demo

Use for investor demos, competitive demos, and reviewable MVP candidates without merging the source:

```text
reviewed Draft PR exact head
→ explicit owner approval for the SHA and target
→ approved GitHub Actions workflow
→ dedicated Business project
→ public-byte and visual/journey verification
→ PR remains Draft and unmerged
```

### Canonical Production

Use when the source is accepted as the operating repository version:

```text
reviewed exact head
→ explicit merge and Production authorization
→ merge to the configured Production branch
→ automatic Git-connected deployment
→ real-environment acceptance
→ reviewed fix/revert recovery
```

Deployment proves environment state. It does not by itself prove product quality, investor readiness, or business value.

## Local editing standard

For structural changes spanning several policy or source files, local repository editing is preferred when it improves consistency and validation.

The expected workflow is:

```text
clean local checkout
→ dedicated branch
→ edit the complete document set coherently
→ repository-wide search for conflicting rules
→ diff and link validation
→ focused tests
→ commit and push
→ Draft PR
```

Direct connector edits remain appropriate for bounded changes. Do not force partial line-by-line remote editing when a local multi-file refactor is safer and clearer.

## External governance control plane

Repository-file validation is necessary but not sufficient because permanent GitHub Issues and PR bodies also direct workers.

Before declaring portfolio governance fully aligned, verify through authenticated GitHub inspection that:

- Issue #154 reflects `MVP_AND_VISUAL_UPGRADE` and does not present `UI_ONLY`, mandatory UI→UX→backend, or backend frozen as current policy;
- Issue #366 remains the active portfolio product-quality audit and renewal program;
- PR #365 or its merged replacement is the authoritative policy source;
- historical issue comments and Business-specific records are not mistaken for current portfolio defaults.

See `POLICY_CONSISTENCY_AUDIT.md`.

## Portfolio tracking

Issue #154 remains open while the portfolio is active.

It should track:

- product thesis;
- current evidence stage;
- visual A/B/C/D classification;
- authoritative head and deployment;
- demo/MVP/backend mode;
- investor/customer readiness;
- pilot, cost, and revenue evidence;
- next highest-value action.
