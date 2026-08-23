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
| `world-feed` | 6 | Existing technical/research workspace; current commercial thesis narrowed to Personal World Discovery and current numbered review implementation lives under `reference/business-06-world-feed-v1/` | A finite, source-forward personal edition can help a reader discover meaningful world changes and connect selected discoveries to nearby relevance without becoming an infinite generic news feed. | Not integrated; current concierge validation remains separate from runtime expansion. |
| `personal-video-archive` | 13 | Incubation MVP; bilingual redesign and portal shell in Draft PR #78 | Users will return to user-controlled topic feeds when video discovery is cleaner and watched videos become durable private reflections and plans. | Global portal shell code and visual review accepted in Draft PR #78 at head 989d0056605e091a2fa842e49dc92f29aed68fbb; PR #78 remains unmerged pending latest-main integration and final merge review. Actual portal production integration is not completed by the PR #78 merge alone. |
| `korean-ai-platform` | 14 | Existing Korean-first model-platform runtime; Router Core and owner-tryable Alpha work remain separately bounded | Korean developers can access external, domestic, and self-hosted models through one platform with controlled execution and BYOK; model/provider selection and fallback belong to Business 14’s internal Router Core. | Authentication and portal integration are not implemented. |

Business 14 is the public model-access platform. The former independent `ai-model-router` identity is superseded; routing is an internal Business 14 capability. Proposed Business 54 is **Korean AI Code Agent / 한국형 AI 코드 에이전트**, a terminal-first first-party client that consumes Business 14. `apps/korean-ai-code-agent/` is now present on current `main` after the hardened CLI/TUI vertical slice passed Linux and Windows exact-head CI; B54 remains proposed-number authority rather than a canonical numbered Business.

## Proposed Business 60 workspace

Business 60 is proposed as **AI API / AI API 탐색 허브** under Issue #650.

```text
proposed number: B60
stable slug: ai-api
future workspace: apps/ai-api/
workspace currently created: no
current runtime: none
current public surface: none
```

B60 is the discovery/deal-intelligence product for current AI API access paths, free tiers, credits, launch promotions, low-cost provider routes, eligibility, expiry, setup guidance, official sources and verification freshness. Its public frontdoor is intentionally cinematic rather than a generic SaaS directory.

B60 must remain separate from Business 14: B60 discovers/verifies/explains access; B14 executes/routes/meters model calls. A future handoff between them does not merge their product identities or authorization boundaries.

See `../docs/portfolio/BUSINESS_60_AI_API_PROPOSAL.md`. Number registration alone does not authorize creation of `apps/ai-api/`, Neon schema, credentials, API-key persistence, domain/DNS changes, or Production deployment.

## Assigned but not yet created workspaces

| Workspace | Canonical Business number | Current state | Primary product hypothesis | Portal state |
|---|---:|---|---|---|
| `neighbor-market` | 5 | concept; workspace not yet created | Residents will discover and support resident-operated work when current-apartment and nearby-apartment relationships are prioritized before general neighborhood businesses. | Not implemented. |

Business 5 is assigned but its workspace is not yet created.

## Canonical Businesses currently represented by review workspaces

B7–B12 are canonical portfolio assignments after Issue #617, but their current implementation authority remains the existing reviewed `reference/` workspace. Canonical numbering does not require creating duplicate `apps/` placeholders.

| Canonical Business | Stable slug | Current authoritative review workspace | Current boundary |
|---:|---|---|---|
| 7 | `personal-meaning-map` | `../reference/business-07-personal-meaning-map-v1/` | Synthetic/review UI/UX evidence; no product runtime or backend authorization implied. |
| 8 | `family-newspaper` | `../reference/business-08-family-newspaper-v1/` | Synthetic/review UI/UX evidence; no family-data runtime, sharing, or persistence implied. |
| 9 | `personalized-childrens-story` | `../reference/business-09-personalized-childrens-story-v1/` | Synthetic/review UI/UX evidence; no child-data runtime or generation backend implied. |
| 10 | `fan-magazine` | `../reference/business-10-fan-magazine-v1/` | Synthetic/review UI/UX evidence; no live ingestion or public-figure data pipeline implied. |
| 11 | `language-learning-magazine` | `../reference/business-11-language-learning-magazine-v1/` | Synthetic/review UI/UX evidence; no learner evaluation or persistence backend implied. |
| 12 | `creator-mini-media` | `../reference/business-12-creator-mini-media-v1/` | Synthetic/review UI/UX evidence; no publishing integration, persistence, or analytics implied. |

`docs/portfolio/BUSINESS_REGISTRY.md` is the sole canonical number-to-product source after Issue #83 is merged. Historical issue text that called B6–B12 proposed, candidate, reserved, or unresolved remains historical evidence rather than current numbering authority.

## Future portal workspace

The user-facing service launcher and shared account product will be implemented separately at:

```text
apps/portal/
```

It is not created by the documentation issue alone.

`apps/portal/` will own portfolio presentation, shared login/account entry, service catalog, and launch behavior. It will not own Business-private records or replace product-local authorization.

## Workspace boundary

A Business runtime workspace may contain its own:

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

A product may not place runtime implementation files in the repository root.

A canonical Business may temporarily remain represented by a `reference/business-XX-.../` review workspace when no separate runtime implementation has been authorized. Number assignment alone is not authority to create an `apps/` product.

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

Issue #617 is the reconciliation record that promoted the established B6–B12 operational assignments into the canonical registry while preserving their earlier proposed/candidate history and existing workspace boundaries.