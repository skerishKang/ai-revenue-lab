# Product Workspaces

Each directory under `apps/` is an independently implemented product or revenue experiment with its own code, tests, configuration, private-data boundary, authorization, deployment, and evidence.

The user-facing portfolio direction is one **AI Revenue Lab Portal**, but portal composition does not merge the Business applications or databases.

Canonical references:

- `../docs/decisions/ADR-0002-product-workspaces.md`
- `../docs/decisions/ADR-0003-shared-portal-isolated-products.md`
- `../docs/portfolio/BUSINESS_REGISTRY.md`
- `../docs/architecture/PORTAL_PRODUCT_INTEGRATION_CONTRACT.md`

## Current workspaces

| Workspace | Canonical Business number | Current status | Primary product hypothesis | Portal state |
|---|---:|---|---|---|
| `personal-edition` | 1 | Active implementation; production foundation open | A user will pay for a recurring polished publication that visibly adapts to prior feedback. | First planned integration target; existing invitation/token authorization remains authoritative until migrated. |
| `living-travel` | 2 | Implemented private MVP; production foundation and pre-staging security contracts merged | Travel content becomes more valuable when each edition adapts to the traveler's latest interests and situation. | Shared Firebase identity foundation is specified; portal integration is not implemented. |
| `living-fiction` | 3 | Implemented private reader/editorial MVP; production infrastructure open | Shared fictional worlds can support rapid feedback-responsive and optionally personal narrative branches. | Not integrated. |
| `living-learning` | 4 | Adaptive-learning MVP and static adaptive UI preview | A recurring short learning publication becomes more useful when it adapts to the learner's responses. | Not integrated. |
| `world-feed` | Unresolved | Synthetic source-to-microbrief MVP and research track | Abundant AI can turn global-local information into a different personal world edition for each user. | Number reconciliation and portal integration both required. |
| `personal-video-archive` | 13 | Incubation MVP; bilingual redesign and portal shell in Draft PR #78 | Users will return to user-controlled topic feeds when video discovery is cleaner and watched videos become durable private reflections and plans. | Global portal shell ported in Draft PR #78 (visual approval pending); final integration after merge. |
| `korean-ai-platform` | 14 | Private governed-execution console MVP in Draft PR #79 | Users can trust AI execution more when worker, validator, and human approval stages expose evidence, cost, and data-processing context. | Authentication and portal integration are not implemented. |

Business 5–12 are reserved or unresolved. Do not assign them from folder order, issue order, conversation order, or product ranking.

`docs/portfolio/BUSINESS_REGISTRY.md` is the sole canonical number-to-product source after Issue #83 is merged.

## Future portal workspace

The user-facing service launcher and shared account product will be implemented separately at:

```text
apps/portal/
```

It is not created by the documentation issue alone.

`apps/portal/` will own portfolio presentation, shared login/account entry, service catalog, and launch behavior. It will not own Business-private records or replace product-local authorization.

## Workspace boundary

A Business workspace may contain its own:

```text
apps/<product>/
├─ README.md
├─ product or architecture contracts
├─ pyproject.toml or equivalent package manifest
├─ .env.example
├─ app/ or src/
├─ templates and static assets
├─ tests/
├─ scripts/
├─ migrations/
└─ product-local fixtures
```

A product may not place implementation files in the repository root.

## Shared identity boundary

The portfolio uses Firebase project `ai-revenue-lab-identity` as the shared identity provider.

That project proves authentication only. Each workspace remains responsible for:

- product-local user mapping;
- invitation or membership eligibility;
- participant/operator/editor/admin roles;
- record-level and tenant-level authorization;
- suspension, revocation, deletion, and retention;
- product sessions where used.

An authenticated Firebase account must not automatically gain access to every workspace.

## Global and local navigation

An integrated Business must distinguish:

### Global portal layer

- AI Revenue Lab identity;
- return to portal or service switcher;
- shared account and sign-out access.

### Product-local layer

- Business name;
- Business workflow navigation;
- local roles, records, and actions.

The global layer must remain restrained and must not force every Business into one generic dashboard design.

## Shared-code rule

Common code is not extracted merely because several products are intended to join the portal.

Move behavior into `platform/` or a shared package only when:

1. at least two implemented products use substantially the same behavior;
2. both products have working tests for the interface;
3. extraction reduces duplication without coupling unrelated releases;
4. a separate architecture decision approves ownership and compatibility.

Until then, limited duplication is preferable to premature abstraction.

## Business 13 boundary

`personal-video-archive` is video-first and private-record-first.

Its initial product contract authorizes topic search, public video metadata, outbound canonical YouTube links, viewing states, ratings, reflections, plans, tags, and timestamp notes. It does not authorize YouTube comments, social feeds, video downloading or rehosting, historical watch-history import, transcript scraping, advertising, or unreviewed production AI summaries.

See:

- `personal-video-archive/README.md`
- `personal-video-archive/PRODUCT_CONTRACT.md`
- `personal-video-archive/LOCAL_HANDOFF.md`
- GitHub Issues #60, #62, #72, and #76

## Registry maintenance

When creating or renumbering a Business:

1. open a dedicated issue;
2. search for number conflicts;
3. define the product boundary and workspace;
4. update `BUSINESS_REGISTRY.md` in a reviewed PR;
5. update this workspace table and the root README;
6. do not treat deployment success as evidence of active production status.
