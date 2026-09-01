# AI Revenue Lab

AI Revenue Lab is a private product and research repository for testing a specific business hypothesis:

> Abundant AI production can do more than reduce cost; it can make new personalized digital products and revenue models economically viable.

## Core thesis

The Lab focuses on:

1. **Volume** — produce information/content at a scale human teams cannot economically sustain.
2. **Speed** — react to events and user feedback quickly.
3. **Concurrency** — coordinate implementation, research, validation, and operations in parallel.
4. **Real-time reaction** — let current events and product state change the next output.
5. **Personalization** — turn common source material into different products for different users.
6. **Revenue evidence** — measure user behavior, operating cost, direct/attributable revenue, and willingness to pay.

Canonical intent:

- `docs/portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

More files, screens, agents, or deployments are not success by themselves. A Business advances when product, operating, user, and commercial evidence improve.

## Portfolio architecture

AI Revenue Lab is a portfolio of independently operated Businesses, not one monolithic application.

```text
shared Firebase identity
          │
          ▼
 AI Revenue Lab Portal
 account · catalog · launcher
          │
   ┌──────┼──────┐
   ▼      ▼      ▼
Business 1  Business 2  Business N
own app     own app     own app
own roles   own roles   own roles
own DB      own DB      own DB
```

Shared authentication proves who authenticated; each Business remains responsible for admission, internal identities, roles, records, databases, secrets, deletion, deployment, and evidence.

Canonical architecture/numbering documents:

- `docs/decisions/ADR-0003-shared-portal-isolated-products.md`
- `docs/product/AI_REVENUE_LAB_PORTAL_CONTRACT.md`
- `docs/portfolio/BUSINESS_REGISTRY.md`
- `docs/portfolio/BUSINESS_EXPANSION_LINEAGE.md`
- `docs/portfolio/EXTERNAL_PORTFOLIO_PROJECTS.md`
- `docs/architecture/PORTAL_PRODUCT_INTEGRATION_CONTRACT.md`

## Portfolio Console

`apps/portfolio-console/` is the private owner/operator control tower, not the user-facing Portal.

Its static Business identity must agree with the registry and successor lineage. Volatile facts such as Issue/PR/SHA/CI/deployment/health are synchronized separately. Owner/product decisions remain human-governed evidence, not derived from green automation alone.

## Repository model

Product/runtime workspaces live under `apps/` when a runtime is authorized. Bounded visual/product-evidence work may remain under `reference/`.

Some source-of-truth projects remain in external repositories. They are tracked in `docs/portfolio/EXTERNAL_PORTFOLIO_PROJECTS.md` when portfolio visibility is required but a BI/Business number is not yet assigned or not required.

```text
apps/
├─ personal-edition/          # B1
├─ living-travel/             # B2
├─ living-learning/           # B4
├─ world-feed/                # B6 technical/research workspace
├─ personal-video-archive/    # B13
├─ korean-ai-platform/        # B14
└─ portfolio-console/         # B44 private control tower

reference/
├─ business-06-world-feed-v1/
├─ business-07-personal-meaning-map-v1/
├─ business-08-family-newspaper-v1/
├─ business-09-personalized-childrens-story-v1/
├─ business-10-fan-magazine-v1/
├─ business-11-language-learning-magazine-v1/
└─ business-12-creator-mini-media-v1/
```

Workspace existence does not itself create canonical numbering, owner approval, backend authorization, or Production readiness.

## Canonical / expanded Business truth

Numbering authority is only `docs/portfolio/BUSINESS_REGISTRY.md`.

Current high-level mapping includes:

- **B1 — Personal Edition** — recurring personal letters/magazines/books from private fragments and records.
- **B2 — Living Travel** — adaptive travel editions shaped by feedback and current situation.
- **B3 — Living Fiction** — canonical Business identity retained; current implementation is treated as external/parallel under successor policy, with no invented repository link.
- **B4 — Living Learning** — recurring personalized learning experiences.
- **B5 — Neighbor Market** — canonical Business retained; implementation expanded to **DanjiOn / 단지온** at `skerishKang/02-danji-on`. Do not create a duplicate internal `apps/neighbor-market/` implementation.
- **B6 — World Feed / Personal World Discovery** — stable slug `world-feed`; finite source-forward discovery connecting world changes with nearby relevance. Concierge validation remains separate from runtime expansion.
- **B7 — Personal Meaning Map** — canonical number; current reviewed reference workspace retained.
- **B8 — Family Newspaper** — canonical number; current reviewed reference workspace retained.
- **B9 — Personalized Children’s Story** — canonical number; current reviewed reference workspace retained.
- **B10 — Fan Magazine** — canonical number; current reviewed reference workspace retained.
- **B11 — Language Learning Magazine** — canonical number; current reviewed reference workspace retained.
- **B12 — Creator Mini-Media** — canonical number; current reviewed reference workspace retained.
- **B13 — Personal Video Archive** — user-controlled video discovery plus durable private viewing records.
- **B14 — Korean AI Platform** — Korean-first model-access platform; Router Core is an internal B14 capability.
- **B54 — Korean AI Code Agent** — proposed-number first-party client of B14; the hardened CLI/TUI vertical slice is integrated at `apps/korean-ai-code-agent/`, while canonical-number promotion remains a separate registry decision.
- **B60 — AI API / AI API 탐색 허브** — proposed-number discovery/deal-intelligence product for current AI API access paths, free tiers, credits, promotions, low-cost routes and source verification. B60 remains separate from B14 execution/routing; runtime workspace and Production surface are not yet authorized. See Issue #650 and `docs/portfolio/BUSINESS_60_AI_API_PROPOSAL.md`.

External/integrated successor mappings for B23/B24/B25/B26/B27/B28/B30/B31/B50 are maintained in `BUSINESS_EXPANSION_LINEAGE.md` and the Portfolio Console static manifest. Unnumbered external portfolio projects are maintained in `EXTERNAL_PORTFOLIO_PROJECTS.md`. Do not recreate prohibited internal placeholders.

Historical Issues/PRs may contain older proposed/candidate/phase wording. They remain historical evidence; current authority comes from current canonical documents and merged source.

## Development operating model

Canonical entry point:

- `AGENTS.md`

Supporting policy:

- `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md`
- `docs/operations/WORKFLOW_STATUS_MODEL.md`
- `docs/operations/EVIDENCE_REQUIREMENTS.md`
- `docs/operations/UI_UX_BACKEND_PHASE_GATES.md`
- `docs/operations/NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`
- `docs/operations/BACKEND_MVP_OPERATING_POLICY.md`
- `docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

### Current mode

```text
MVP_AND_VISUAL_UPGRADE
ROLE_SEPARATED_EVIDENCE
NO_MANDATORY_UI_UX_BACKEND_SEQUENCE
```

The Web CTO chooses the smallest evidence slice that answers the current uncertainty. Product work may begin with visual design, UX, deterministic simulation, service-led delivery, local runtime, a live backend/provider vertical slice, or commercial hardening when that is the right evidence target.

UI, UX, backend/runtime, security, market-reference, investor-demo, deployment, owner-visual, and commercial verdicts remain separate.

### Responsibility flow

```text
User request / portfolio authority
→ Web CTO exact work contract
→ Web Developer implementation
→ implementation self-check + configured CI
→ independent validation when required
→ Web CTO final review
→ owner decision when materially reserved
→ merge
→ configured Production deployment/acceptance when authorized
```

One actor may perform multiple non-independent stages, but the same actor must not claim both implementation and **independent Local Validation** for the same revision.

## Evidence standard

Before implementation/review/merge, record and re-read:

- repository and current `main`;
- exact base/head SHA;
- target branch;
- allowed/forbidden paths;
- changed files/diff;
- acceptance criteria/non-goals;
- CI/check status;
- exact-head local/browser/runtime evidence when required;
- owner-only decisions still pending.

CI proves only what it actually executes. Wrong-project Preview deployments, accessible URLs, or HTTP 200 responses do not prove the intended reviewed revision.

## Backend evidence modes

Choose explicitly when runtime work is relevant:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

Backend is not frozen by default. Build it early when it is necessary to prove the product and keep it bounded to the evidence goal. Do not add infrastructure for ceremony.

## Deployment model

For Git-connected Production targets, after the required source/evidence/authority gates:

```text
validated exact head
→ authorized expected-head merge
→ configured automatic Production deployment
→ Production acceptance against resulting revision
→ reviewed fix/revert recovery when required
```

Preview/staging/manual deployment is not an operator fallback. It requires explicit authority under `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` or a stricter Business-specific contract.

A green deployment under an unrelated project is invalid product evidence.

## Identity and product access

Portfolio identity project: `ai-revenue-lab-identity`.

Shared identity does not imply universal access:

```text
verified Firebase identity
→ stable portal identity
→ product-local identity mapping
→ product-local role and record authorization
```

Every portal-integrated Business must define authentication mode, product-local authorization owner, deployment lifecycle, deletion/revocation behavior, and evidence that authenticated-but-unauthorized users are denied.

## Governance / business evidence

Every experiment should record the relevant subset of:

- cash infrastructure cost;
- paid AI/model/provider cost;
- free-model usage;
- human/operator time;
- generated outputs;
- user engagement/retention;
- direct or attributable revenue;
- willingness to pay;
- service-led workload and margin.

The goal is not to prove that one model is best. The goal is to determine whether AI-native production can create products and economics that would not be viable with conventional human production alone.
