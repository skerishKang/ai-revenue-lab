# AI Revenue Lab

AI Revenue Lab is a private product and research repository for proving a specific business hypothesis:

> AI can do more than reduce cost. Abundant free and high-volume AI inference can create new personalized digital products and generate direct revenue.

## Core thesis

Industrial production made one product cheap enough for millions of people. AI-native production can make millions of different editions, one for each person.

The project therefore focuses on six capabilities:

1. **Volume** — produce information and content at a scale that human teams cannot economically sustain.
2. **Speed** — react to events and user feedback within minutes or hours.
3. **Concurrency** — coordinate multiple implementation, research, validation, and operations workers in parallel.
4. **Real-time reaction** — let current events, operating state, and user feedback change the next output quickly.
5. **Personalization** — turn common source material into a different product edition for each user.
6. **Revenue evidence** — measure whether AI-produced outputs create traffic, subscriptions, purchases, or other direct or attributable revenue.

The canonical portfolio intent is documented in:

- `docs/portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

The repository is successful only when product hypotheses move toward working services, user behavior, operating cost, and business evidence. More files, screens, agents, or deployments are not success by themselves.

## Portfolio product direction

AI Revenue Lab is intended to become one user-facing **AI Revenue Lab Portal** containing multiple independently operated Businesses.

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

The shared identity provider establishes who authenticated. Each Business remains responsible for admission, internal identities, roles, records, databases, deployments, secrets, deletion, and evidence.

This is one portfolio experience, not one monolithic application or one shared product database.

Canonical portal documents:

- `docs/decisions/ADR-0003-shared-portal-isolated-products.md`
- `docs/product/AI_REVENUE_LAB_PORTAL_CONTRACT.md`
- `docs/portfolio/BUSINESS_REGISTRY.md`
- `docs/architecture/PORTAL_PRODUCT_INTEGRATION_CONTRACT.md`

The future user-facing portal belongs in `apps/portal/`. Reusable code belongs in `platform/` only after at least two implemented products prove the same stable requirement and a separate architecture decision approves extraction.

## Portfolio Console direction

`apps/portfolio-console/` is the private owner and operator control tower. It is not the user-facing Portal.

The Console combines deliberate Business authority with automatically synchronized operational facts so the owner can determine what exists, what is deployed, what is being built, what is blocked, and what should happen next without repeatedly re-auditing every repository by hand.

Automation supplies Issue, PR, SHA, CI, deployment, health, and synchronization facts. Humans retain product priority, phase approval, and business judgment.

## Repository model

This repository is the portfolio-level workspace. Each revenue experiment has an independent product directory under `apps/`.

```text
apps/
├─ personal-edition/          # Business 1
├─ living-travel/             # Business 2
├─ living-fiction/            # Business 3
├─ living-learning/           # Business 4
├─ world-feed/                # number reconciliation required
├─ personal-video-archive/    # Business 13
└─ korean-ai-platform/        # Business 14
```

Business 5–12 remain reserved or unresolved until an explicit registry decision assigns them. Workspace existence does not by itself assign a Business number.

Product-specific code, tests, configuration, migrations, scripts, fixtures, and private data boundaries remain inside the corresponding workspace. Shared code is extracted only after demonstrated reuse.

See:

- `apps/README.md`
- `docs/decisions/ADR-0002-product-workspaces.md`
- `docs/portfolio/BUSINESS_REGISTRY.md`

## Default execution loop

After a product decision fixes scope and acceptance, the default operating loop is:

```text
smallest useful scope
→ AI implementation
→ independent validation
→ exact-head approval
→ merge to the configured Production branch
→ automatic Production deployment by the existing Git integration
→ immediate Production acceptance
→ retain or merge a reviewed fix/revert PR
→ record product and business evidence
```

UI, UX, backend, deployment, and business verdicts remain separate so one type of evidence is not misrepresented as another. These gates control scope and risk; they are not intended to create ceremony or delay an authorized deployment.

For Git-connected Cloudflare Pages projects, approving a merge to the configured Production branch is the deployment action. Operators observe and verify the automatic Production deployment. They do not create a second deployment manually.

Preview and staging are disabled by default. They may be introduced only by a new explicit owner decision or an already approved Business-specific contract that names the exception. Before the authorized merge, record the last known-good Production source and configuration plus the required smoke checks.

Routine inspection and authorized configuration should use authenticated APIs, connectors, or CLI automation rather than repeated owner Dashboard work. APIs and CLI must not be used to create, retry, promote, or directly upload a deployment on Git-connected Pages projects. Owner action is reserved for product, risk, and genuinely owner-only decisions.

## Verified product tracks

- **Business 1 — Personal Edition** — conversations and life records edited into recurring letters, magazines, and books.
- **Business 2 — Living Travel** — adaptive travel letters shaped by a traveler's feedback and situation.
- **Business 3 — Living Fiction** — shared canon with optional reader-responsive private narrative branches.
- **Business 4 — Living Learning** — recurring short personalized learning experiences.
- **Business 13 — Personal Video Archive** — user-controlled video topic feeds combined with private viewing reflections, plans, ratings, tags, and records.
- **Business 14 — Korean AI Platform** — governed AI execution with worker, validator, and human approval stages.

**World Feed** has an implemented workspace and research history, but its Business number is not canonical until the numbering conflict is reconciled through the registry process.

## Identity and product access

The portfolio identity project is `ai-revenue-lab-identity`.

Shared authentication does not mean universal product access:

```text
verified Firebase identity
        → stable portal identity
        → product-local identity mapping
        → product-local role and record authorization
```

A Firebase account alone must not grant participant, traveler, reader, operator, editor, or administrator access.

Personal Edition is the first planned portal integration target. Its current invitation/token and administrator controls remain authoritative until a separate reversible migration is implemented and accepted.

## Operating model

- Product vision, architecture, issue decomposition, acceptance criteria, documentation, and final review use the strongest available reasoning and review capability.
- Free and high-volume models are the default implementation workforce once tasks are precisely specified.
- Runtime content production should prefer replaceable free or low-cost models.
- Strong paid models may be used for exceptional design, diagnosis, or final audit, but the project records where and why they were used.
- Models remain replaceable through provider adapters rather than being embedded directly into product code.
- Each Business is reviewed, deployed, measured, and continued or stopped independently.
- The Portal does not weaken product-local authorization, privacy, or test gates.
- The Console must reduce manual operating work rather than become another reporting burden.
- Platform-specific Preview failures do not block the normal Git-connected automatic Production path. Operators must not create Preview or another deployment mechanism without new explicit owner authority.

## Current portfolio status

- independent product workspace architecture is established;
- shared-portal and isolated-product architecture is documented under Issue #83;
- shared Firebase identity infrastructure exists for the portfolio;
- portal implementation under `apps/portal/` is not yet authorized by this documentation alone;
- Personal Edition is the first portal integration target;
- Personal Video Archive is undergoing a Korean-first bilingual visual redesign in Draft PR #78;
- Korean AI Platform private MVP is tracked through Issue #80 and Draft PR #79;
- Portfolio Console has a merged Business 1–55 static-authority and automatic GitHub-fact mapping foundation; live Production activation remains separately authorized and verified;
- Business numbering is canonical only through `docs/portfolio/BUSINESS_REGISTRY.md`.

## Governance rule

Every experiment must record:

- cash infrastructure cost;
- paid AI cost;
- free-model usage;
- human work time;
- generated outputs;
- user engagement;
- direct or attributable revenue.

Every portal-integrated Business must additionally record:

- authentication mode;
- product-local authorization owner;
- portal integration state;
- deployment lifecycle;
- deletion and revocation behavior;
- evidence that authenticated but unauthorized users are denied.

The goal is not to prove that one model is best. The goal is to determine whether abundant AI production can create economically valuable products that would not be viable with human production alone.