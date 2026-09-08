# AI Revenue Lab

AI Revenue Lab is a private product and research repository for testing a specific business hypothesis:

> Abundant AI production can do more than reduce cost; it can make new personalized digital products and revenue models economically viable.

## Documentation entrypoints

Repository documentation is intentionally split between **current canonical authority** and historical/evidence documents. Start here:

- [`docs/README.md`](docs/README.md) — documentation map and authority rules
- [`docs/architecture/PADIEM_AI_VERTICAL_STACK.md`](docs/architecture/PADIEM_AI_VERTICAL_STACK.md) — Padiem AI vertical platform architecture
- [`docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`](docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md) — IP-CORE / IP-ENGINE / IP-CONTROL / proposed IP-SIDECAR
- [`docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`](docs/product/AI_PRODUCT_CONSUMER_MATRIX.md) — Chat, Claw, StoryMemory, Sidecar and other AI consumers
- [`docs/portfolio/BUSINESS_REGISTRY.md`](docs/portfolio/BUSINESS_REGISTRY.md) — sole Business-number authority

Dated, issue-numbered and phase-specific documents are valuable evidence but are not automatically current architecture or runtime authority.

## Core thesis

The Lab focuses on:

1. **Volume** — produce information/content at a scale human teams cannot economically sustain.
2. **Speed** — react to events and user feedback quickly.
3. **Concurrency** — coordinate implementation, research, validation, and operations in parallel.
4. **Real-time reaction** — let current events and product state change the next output.
5. **Personalization** — turn common source material into different products for different users.
6. **Revenue evidence** — measure user behavior, operating cost, direct/attributable revenue, and willingness to pay.

Canonical operating intent:

- `docs/portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

More files, screens, agents, or deployments are not success by themselves. A Business advances when product, operating, user, and commercial evidence improve.

## Two registries: Businesses and Internal Platform

AI Revenue Lab contains both independently operated Businesses/products and shared Padiem platform infrastructure. They use different identifiers and must not be mixed.

### Business / product portfolio

Business numbering authority is only:

```text
docs/portfolio/BUSINESS_REGISTRY.md
```

Businesses own their product/domain UX, product-local authorization, records, persistence, deployment lifecycle and commercial evidence.

### Padiem Internal Platform

Shared AI infrastructure uses Internal Platform IDs rather than fake Business numbers:

```text
IP-CORE     = Padiem AI Core
IP-ENGINE   = Padiem AI Engine
IP-CONTROL  = Padiem Control Plane
IP-SIDECAR  = Padiem Embedded AI Runtime  [proposed / separately gated]
```

B14 Korean AI Platform remains **Business 14** and is the Provider/model execution authority. Its Router is an internal B14 capability, not a separate Business or platform ID.

Canonical AI composition:

```text
Product / Business domain + UX
        │
        ├─ optional IP-SIDECAR embedded presentation layer
        │
        ▼
IP-ENGINE  cross-runtime trusted service boundary
        │
        ▼
IP-CORE    reusable AI semantics/contracts/runtime
        │
        ▼
B14        provider/model catalog, routing, credentials, execution
        │
        ▼
Provider / Model

IP-CONTROL = cross-cutting identity / tenant / entitlement / usage / audit
             and neutral cross-product declarations
```

Same-runtime/library consumers may use IP-CORE directly only where architecture explicitly permits it. Product code must not create a second generic AI policy engine or Provider/model router.

## Portfolio architecture

AI Revenue Lab is a portfolio of independently operated Businesses, not one monolithic application.

```text
shared portfolio identity
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

Shared authentication proves who authenticated; each Business remains responsible for admission, internal identities, roles, records, databases, secrets, deletion, deployment, and evidence unless a separately accepted shared authority explicitly owns that concern.

Canonical portfolio references:

- `docs/decisions/ADR-0003-shared-portal-isolated-products.md`
- `docs/product/AI_REVENUE_LAB_PORTAL_CONTRACT.md`
- `docs/portfolio/BUSINESS_REGISTRY.md`
- `docs/portfolio/BUSINESS_EXPANSION_LINEAGE.md`
- `docs/portfolio/EXTERNAL_PORTFOLIO_PROJECTS.md`
- `docs/architecture/PORTAL_PRODUCT_INTEGRATION_CONTRACT.md`

## Repository model

Product/runtime workspaces live under `apps/` when a runtime is authorized. Shared Padiem packages live under `packages/`. Bounded visual/product-evidence work may remain under `reference/`.

```text
apps/                         # products and runtime services
packages/
├─ padiem-ai-core/            # IP-CORE
└─ padiem-control-plane/      # IP-CONTROL

docs/                         # canonical docs + evidence/history
reference/                    # bounded review/reference workspaces
```

`apps/padiem-ai-engine/` is IP-ENGINE even though its runtime packaging lives under `apps/`; that filesystem location does not make it a numbered Business.

Some source-of-truth projects remain in external repositories. They are tracked in `docs/portfolio/EXTERNAL_PORTFOLIO_PROJECTS.md` or the relevant successor lineage rather than recreated as fake internal placeholders.

Workspace existence does not itself create canonical numbering, owner approval, backend authorization, or Production readiness.

## Selected product relationships to the AI stack

### B62 · Padiem Chat

Padiem Chat owns the general chat product surface: conversations, Projects, attachments, Saved Outputs, modes and product context presentation. Reusable execution/grounding/evidence semantics belong to Core; cross-runtime paths use Engine; Provider/model execution belongs to B14.

### B54 · Padiem Claw / Korean AI Code Agent

Canonical source remains `apps/korean-ai-code-agent/**`. Claw owns repository/task/run/workspace/GitHub product semantics. Generic Agent/Tool/Skill/approval/recovery/orchestration semantics belong to Core, with Engine as the cross-runtime service boundary and B14 as model execution authority.

### B61 · StoryMemory

StoryMemory owns reader/domain semantics including canonical locators, reading progress, knowledge ceiling, annotations and spoiler/no-future behavior. Bible/classic-work locator meaning remains product-owned. Generic retrieval permission/context/evidence semantics belong to Core; Engine projects them across runtimes; B14 executes models.

### B53 · Padiem Sidecar vs IP-SIDECAR

These are distinct identities:

```text
B53 Padiem Sidecar
= commercial product / onboarding / packaging / customer journey

IP-SIDECAR
= proposed reusable embedded AI shell/runtime layer
```

See `docs/internal-platform/sidecar/README.md`.

### B14 · Korean AI Platform

B14 is Padiem's general AI Router Platform and owns Provider/model registry, inference credentials, executable route validation, provider adapters and actual upstream model execution. Current Padiem product-tier declarations are neutral shared declarations in Control Plane; B14 remains final executability authority.

See `apps/korean-ai-platform/README.md`.

## Portfolio Console

`apps/portfolio-console/` is the private owner/operator control tower, not the user-facing Portal.

Its static Business identity must agree with the canonical registries and successor lineage. Volatile facts such as Issue/PR/SHA/CI/deployment/health are synchronized separately. Owner/product decisions remain human-governed evidence, not derived from green automation alone.

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

Current product-development mode remains evidence-driven rather than ceremony-driven. The Web CTO chooses the smallest slice that answers the current uncertainty; UI, UX, backend/runtime, security, deployment and commercial verdicts remain distinguishable evidence classes.

## Evidence standard

Before implementation/review/merge, record and re-read the relevant subset of:

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

## Source readiness is not Production activation

This distinction applies across Core, Engine, Control Plane, products and B14:

```text
SOURCE_PRESENT
!= CONTRACT_AVAILABLE
!= BINDING_CONFIGURED
!= PROVIDER_READY
!= DEPLOYED
!= PRODUCTION_ACCEPTED
```

A class, route, manifest entry, UI control or passing unit test does not by itself prove a live Provider, secret, database, connector or Production binding.

## Deployment model

For Git-connected Production targets, after the required source/evidence/authority gates:

```text
validated exact head
→ authorized expected-head merge
→ configured Production deployment path
→ Production acceptance against resulting revision
→ reviewed fix/revert recovery when required
```

Direct/manual deployment, DNS changes, credential mutation and rollback require the repository's applicable release policy and explicit authority.

## Identity and product access

Shared portfolio identity does not imply universal product access:

```text
verified shared identity
→ stable portal identity
→ product-local identity mapping
→ product-local role and record authorization
```

Control Plane may own accepted canonical subject/tenant/entitlement contracts, but each product remains responsible for its product-specific admission and record authorization unless a shared contract explicitly replaces that responsibility.

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
