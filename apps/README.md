# Product and Runtime Workspaces

```text
DOC_STATUS = CURRENT_WORKSPACE_INDEX
OWNER = repository workspace governance
SCOPE = stable source/workspace identities, not live PR/deployment status
LAST_VERIFIED = 2026-09-08
```

`apps/` contains independently implemented products **and** runtime services. Directory presence does not itself create a Business number, Production authorization, or current deployment claim.

For current documentation authority, start with:

- `../docs/README.md`
- `../docs/portfolio/BUSINESS_REGISTRY.md` — sole Business-number authority
- `../docs/architecture/PADIEM_AI_VERTICAL_STACK.md` — Padiem AI platform architecture
- `../docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md` — shared platform IDs/source authority
- `../docs/product/AI_PRODUCT_CONSUMER_MATRIX.md` — AI-consuming product relationships

## Important distinction: Business vs Internal Platform

Not every directory under `apps/` is a numbered Business.

```text
apps/padiem-ai-engine/ = IP-ENGINE · Padiem AI Engine
                         shared Internal Platform runtime service
                         NOT a Business number
```

Shared packages also live under `packages/`:

```text
packages/padiem-ai-core/       = IP-CORE
packages/padiem-control-plane/ = IP-CONTROL
```

B14 Korean AI Platform remains a numbered Business and the Provider/model execution authority.

## Current workspace inventory

| Workspace | Stable identity / role | Notes |
|---|---|---|
| `personal-edition` | B1 Personal Edition | product workspace |
| `living-travel` | B2 Living Travel | product workspace |
| `living-fiction` | B3 Living Fiction | product workspace; consult registry/lineage for current source authority |
| `living-learning` | B4 Living Learning | product workspace and AI consumer |
| `world-feed` | B6 World Feed / Personal World Discovery | product/research workspace; canonical product state comes from registry and current product docs |
| `personal-video-archive` | B13 Personal Video Archive | product workspace |
| `korean-ai-platform` | **B14 Korean AI Platform** | general AI Router Platform; Provider/model execution authority |
| `korean-ai-code-agent` | **B54 Padiem Claw / Korean AI Code Agent** | canonical B54 source; task/run/workspace product layer |
| `padiem-chat` | **B62 Padiem Chat** | standalone general AI product |
| `padiem-ai-engine` | **IP-ENGINE** | shared cross-runtime AI service boundary; not a Business |
| `portfolio-console` | private owner/operator control tower | not the user-facing Portal |
| `ai-reward-router` | product/experiment workspace | consult canonical registry/contract before assigning Business identity |
| `padiem-lab` | laboratory/experimental workspace | workspace existence does not imply Business identity |
| `personal-edition` | B1 | canonical number remains registry-owned |

The table deliberately avoids embedding current PR numbers, CI state, deployment SHA, or live readiness. Those facts age quickly and belong in current source, issue/PR evidence, deployment records, or the Portfolio Console.

## External and reference-backed products

Some canonical or portfolio products remain in external repositories or `reference/` workspaces. Do not create duplicate `apps/` placeholders solely to make the local tree look complete.

Canonical authorities:

- `../docs/portfolio/BUSINESS_REGISTRY.md`
- `../docs/portfolio/BUSINESS_EXPANSION_LINEAGE.md`
- `../docs/portfolio/EXTERNAL_PORTFOLIO_PROJECTS.md`

## AI product architecture

AI-consuming products should not each recreate a complete AI stack.

Default cross-runtime path:

```text
Product / Business adapter
 -> IP-ENGINE
 -> IP-CORE
 -> B14
 -> Provider / Model
```

`IP-CONTROL` supplies cross-cutting identity/tenant/entitlement/usage/audit and neutral declarations where integrated. Proposed `IP-SIDECAR` is the reusable embedded shell/runtime layer for host-integrated AI surfaces; B53 Padiem Sidecar is the separate commercial product.

See `../docs/internal-platform/AI_ADOPTION_PLAYBOOK.md` before adding generic AI runtime code to a product workspace.

## Workspace boundary

A product runtime may contain its own:

```text
apps/<product>/
├─ README.md
├─ product or architecture contracts
├─ pyproject.toml or equivalent package manifest
├─ app/ or src/
├─ templates/static assets
├─ tests/
├─ scripts/
├─ migrations/
└─ product-local fixtures
```

Product-specific domain meaning, persistence and UX remain local. Shared generic AI semantics are promoted only through an accepted shared contract, not merely because two products happen to contain similar code.

## Shared identity and authorization

Shared authentication proves identity only. A Business remains responsible for product admission, roles, record authorization, revocation/deletion and product-local data boundaries unless an accepted Control Plane/shared contract explicitly owns that concern.

An authenticated account must not automatically gain access to every product.

## Registry maintenance

When creating, renumbering or reclassifying a workspace:

1. check `BUSINESS_REGISTRY.md` and Internal Platform registry for conflicts;
2. decide whether the target is a Business, Internal Platform component, product adapter, reference workspace or laboratory workspace;
3. define source authority and ownership boundary;
4. update the appropriate canonical registry in a reviewed PR;
5. update this stable workspace index only if the source identity changes;
6. keep volatile implementation/deployment status outside this file.
