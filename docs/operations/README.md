# Operations Documents

- `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md` — canonical portfolio mission: prove the excellence and commercial usefulness of AI through competitive demos, MVPs, pilots, and operating products.
- `UI_UX_BACKEND_PHASE_GATES.md` — product evidence stages: framing → competitive demo → investor demo or MVP → pilot → commercial hardening.
- `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — competitive product demo and MVP implementation playbook; file name retained for compatibility.
- `COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md` — screen-level benchmarking, imagery, typography, composition, motion, and investor/customer visual-quality gates.
- `BACKEND_MVP_OPERATING_POLICY.md` — backend modes, vertical slices, service-led pilots, data, providers, observability, testing, cost, and hardening.
- `PORTFOLIO_PRODUCT_QUALITY_AUDIT.md` — portfolio-wide A/B/C/D audit and Visual Upgrade v2 / Product Upgrade v2 program.
- `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` — Git-connected automatic Production execution, acceptance, and reviewed recovery.
- `../portfolio/BUSINESS_CANDIDATE_BACKLOG.md` — idea-preservation backlog and proposed Business map.
- Permanent portfolio tracking issue: `#154`.

## Current portfolio mode

```text
MVP_AND_VISUAL_UPGRADE
```

The former portfolio-wide `UI_ONLY` default is superseded.

For each Business, choose the strongest reversible evidence stage required by the current business question:

```text
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
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

## Operator standard

The owner is the final product, business, legal-risk, policy, and technical decision-maker.

Operators must:

- identify concrete risks without generic lecturing;
- preserve intended product value;
- propose practical mitigations before deleting features, imagery, language, or ambition;
- avoid treating the owner as a novice;
- proceed within authorized scope without repeated minor questions;
- distinguish implementation facts from expert product judgment;
- optimize for visible product and business evidence rather than ceremony.

Default instruction:

```text
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

## Deployment default

Deployment remains governed by `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

```text
explicit authorization
→ reviewed exact head
→ approved merge to the configured Production branch
→ automatic Git-connected deployment
→ real-environment acceptance
→ retain or merge a reviewed fix/revert PR
```

Deployment proves environment state. It does not by itself prove product quality, investor readiness, or business value.

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