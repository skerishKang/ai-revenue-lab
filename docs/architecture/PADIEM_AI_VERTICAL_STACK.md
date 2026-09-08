# Padiem AI Vertical Stack — Canonical Architecture

Status: **CURRENT CROSS-LAYER AUTHORITY**  
Effective: 2026-09-08  
Repository: `skerishKang/ai-revenue-lab`

## 1. Purpose

Padiem's AI assets are not a collection of unrelated backends. They form a vertically integrated stack that is reused by multiple products while preserving clear ownership boundaries.

The goal is to let a product obtain AI capability without recreating shared execution, orchestration, routing, provider credentials, identity, connectors, evidence, or memory semantics locally.

## 2. Canonical topology

### Cross-runtime default

```text
User / Customer
      |
      v
Padiem Product / Business
      |
      v
Product Adapter
      |
      v
IP-ENGINE · Padiem AI Engine
trusted cross-runtime service boundary
      |
      v
IP-CORE · Padiem AI Core
shared AI contracts + semantics + runtimes
      |
      v
B14 · General AI Router Platform
provider/model routing + execution authority
      |
      v
Provider / Model
```

### Cross-cutting control plane

```text
IP-CONTROL · Padiem Control Plane
identity · subject · tenant/workspace · entitlement
usage/credits/billing · shared audit/security truth
```

IP-CONTROL is cross-cutting authority. It is not required to appear as a sequential network hop in every model request.

### Embedded delivery where applicable

```text
Host website/app
   -> B53 Padiem Sidecar / Customer Adapter
   -> IP-SIDECAR · Padiem Embedded AI Runtime
   -> IP-ENGINE
   -> IP-CORE
   -> B14
   -> Provider / Model
```

`IP-SIDECAR` is the reusable embedded-delivery layer. Its existence/planning does not move host/product domain semantics out of the Product Adapter.

### Explicit same-runtime exception

A same-runtime/library consumer may use:

```text
Product -> Product Adapter -> IP-CORE -> B14 -> Provider/Model
```

only when an accepted architecture explicitly permits it. This is a deployment/composition optimization, not a different ownership model. Cross-runtime products and reusable service consumers should use IP-ENGINE.

## 3. Layer ownership

| Layer | Canonical role | Owns | Must not become |
|---|---|---|---|
| Product / Business | Customer/product experience | domain state, UX, product persistence, product-specific policies, Product Adapter | generic AI runtime, provider router, shared account authority |
| IP-SIDECAR | Embedded delivery runtime | reusable panel/shell/context bridge/bootstrap/public-safe embedded runtime primitives | product domain model, AI policy engine, provider router |
| IP-ENGINE | Cross-runtime AI service | trusted caller identity, execute/stream/orchestrate transport, versioned wire projection, safe runtime exposure of Core capabilities | second Core, product UX, provider router |
| IP-CORE | Shared AI semantics | execution contracts, grounding/evidence, Web/Research, context permission, Tool/Connector, Memory/RAG, Skill, Agent, approval/recovery/orchestration semantics | product UI/domain model, provider/model registry |
| B14 | General AI Router Platform | model/provider catalog, provider adapters, inference credentials/references, route selection/policy, availability/retirement validation, external model invocation, route execution evidence | product memory/domain state, product UI, Control Plane |
| IP-CONTROL | Shared control plane | canonical identity/subject, tenant/workspace/membership, entitlement, usage/credits/billing, shared audit/security truth, trusted credential/OAuth control services where explicitly owned | AI reasoning semantics, provider/model execution, product history |
| Provider / Model | External execution | actual upstream model/service behavior | Padiem product authority |

## 4. B14 Router Platform and Padiem Routing Profile

B14's original business purpose remains a **general AI Router Platform**. Padiem is the first concrete product/customer routing profile.

Current Padiem Profile v1 is intentionally explicit because the owner has already selected the required routes:

```text
Padiem Plus
  -> provider_id = kilo
  -> model_id = kilo/poolside-laguna-s-2.1-free

Padiem Pro
  -> provider_id = kilo
  -> model_id = kilo/nvidia-nemotron-3-ultra-550b-a55b-free

Padiem Max
  -> HOLD
```

Current profile rules:

```text
PADIEM_PROFILE_V1_AUTO_ROUTING = NO
PADIEM_USER_VISIBLE_AUTO = NO
PADIEM_SILENT_FALLBACK = NO
```

These are **Padiem Profile v1 constraints**, not a global deletion of B14's router mission.

Valid future B14 capabilities include:

- generic automatic route selection;
- capability-aware routing;
- cost/latency/availability-aware optimization;
- bounded policy-controlled fallback/retry;
- BYOK and platform-managed credential references;
- OpenAI-compatible/direct provider adapters;
- customer/product-specific routing profiles;
- operator/admin routing management.

When Padiem later requests automatic optimization, a later Padiem profile may explicitly opt into accepted B14 router policies.

Current product-tier declaration source:

`packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py`

This file **declares the Padiem product mapping**. It does not replace B14 as final executability and provider/model dispatch authority.

## 5. Connector ownership

Connectors are part of the shared AI/tool platform when their semantics are reusable.

Canonical direction:

```text
Product connector UX / product intent
   -> Product Adapter
   -> IP-ENGINE cross-runtime projection when needed
   -> IP-CORE Tool/Connector/Approval semantics
   -> trusted connector adapter/binding
   -> external service
```

Rules:

- Product UI may display/connect/select connectors but does not create a second generic Tool/Connector runtime.
- Core owns reusable Tool/Connector authorization, side-effect and approval semantics.
- Engine projects accepted shared connector/tool capabilities across runtimes.
- Control Plane or another explicitly assigned trusted credential authority may own OAuth/credential lifecycle; raw secrets never become Product Adapter or model context authority.
- External sends/writes remain approval/policy gated according to the owning shared contract.
- Provider/model routing remains B14; Gmail/Drive/Telegram/Discord/etc. are connectors, not model Providers.

## 6. Product adoption matrix

### B62 — Padiem Chat

```text
Padiem Chat
  -> Product Adapter / current same-runtime Core composition where accepted
  -> IP-ENGINE for orchestration/cross-runtime service paths
  -> IP-CORE
  -> B14
  -> Provider/Model
```

B62 owns general chat UX, conversations/history, Projects, attachment presentation, Saved Outputs, Chat/Claw shell surfaces, and product tier/mode presentation. It does not own generic Agent/Tool/Skill/Memory semantics or provider/model routing.

Current user-visible model tiers are Padiem Plus / Pro / Max, with the v1 explicit routes defined above.

### B54 — Padiem Claw

```text
Padiem Claw
  -> Claw Product Adapter / task-run-workspace semantics
  -> IP-ENGINE when shared execution crosses runtimes
  -> IP-CORE Agent/Skill/Tool/Approval/Memory/Evidence semantics
  -> B14
  -> Provider/Model
```

Claw owns business workflow/product semantics such as task/run/repository/sandbox product lifecycle, document/workflow UX, product-specific diff/test/review and approved external-workflow presentation. It must not become another generic Agent runtime, connector runtime, provider registry or router.

### B53 — Padiem Sidecar

B53 is the commercial embedded-AI delivery product. Its target stack is:

```text
Host
  -> B53 Padiem Sidecar / Customer Adapter
  -> IP-SIDECAR
  -> IP-ENGINE
  -> IP-CORE
  -> B14
  -> Provider/Model
```

B53 owns customer onboarding/configuration/commercial packaging and product-specific adapter selection. IP-SIDECAR owns reusable embedded technical primitives. Do not iframe or duplicate B62 as the shared runtime.

### B61 — StoryMemory / Bible-reading AI product

B61 owns reader/library UX, corpus/edition/domain locator semantics, reading progress, annotations, spoiler/knowledge-ceiling specialization and the StoryMemory Product Adapter.

```text
StoryMemory Product Adapter
  -> IP-ENGINE / accepted shared service path
  -> IP-CORE evidence/context/memory/retrieval semantics
  -> B14
  -> Provider/Model
```

StoryMemory application source remains under its established **private package/worktree + Drive authority**. `ai-revenue-lab` is the public issue/portfolio/shared-platform contract authority for B61; it is not authority to publish private StoryMemory runtime bytes.

### B30 / 400 AI Finder and other AI-consuming products

Products that need Web/Research, Evidence, Tool, Memory, Agent, Skill or model execution should reuse the same stack through a bounded Product Adapter. A missing Engine projection is not permission to build a second generic runtime inside the product.

## 7. Source paths

| Layer/product | Current repository path / authority |
|---|---|
| IP-CORE | `packages/padiem-ai-core/**` |
| IP-ENGINE | `apps/padiem-ai-engine/**` |
| IP-CONTROL | `packages/padiem-control-plane/**` |
| B14 | `apps/korean-ai-platform/**` |
| B62 Padiem Chat | `apps/padiem-chat/**` |
| B54 Padiem Claw | `apps/korean-ai-code-agent/**` |
| IP-SIDECAR | shared embedded-runtime identity/roadmap; do not claim a live runtime merely from architecture docs |
| B61 StoryMemory | private source authority + public portfolio/contract coordination in this repository |

## 8. Terminology normalization

Canonical terms:

```text
IP-CORE    / Padiem AI Core
IP-ENGINE  / Padiem AI Engine
IP-CONTROL / Padiem Control Plane
IP-SIDECAR / Padiem Embedded AI Runtime
B14        / Korean AI Platform / General AI Router Platform
B54        / Padiem Claw
B62        / Padiem Chat
B53        / Padiem Sidecar
B61        / StoryMemory
```

`P01` remains valid as historical program/issue lineage and in existing filenames. It is not a separate runtime layer beside IP-CORE/IP-ENGINE.

Use **Control Plane**, not `Control Panel`, for the shared authority layer.

## 9. Availability and deployment truth

Layer ownership and runtime availability are separate.

```text
CONTRACT_DEFINED
SOURCE_IMPLEMENTED
ENGINE_PROJECTED
CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

Do not infer a later state from an earlier one.

Examples:

- a Core capability can exist while its Engine projection is deferred;
- an Engine route can exist in source while a Production binding is absent;
- a Padiem route can be declared while B14 rejects it as retired/unregistered;
- a connector can have UI and contracts while OAuth/runtime activation is absent;
- a product can be deployed while a particular shared AI capability remains unavailable.

Exact Production claims require current deployment/version/readback evidence.

## 10. Anti-duplication rule

Before adding generic AI logic to a Product, classify it:

```text
PRODUCT_ADAPTER
REUSE_CORE
EXTEND_CORE
ENGINE_TRANSPORT
B14_EXECUTION
CONTROL_PLANE
SIDECAR_RUNTIME
DO_NOT_SHARE
```

If the capability is reusable across products, implement it in the owning shared layer rather than creating another product-local authority.

## 11. Related current authority

- `../../packages/padiem-ai-core/README.md`
- `../../apps/padiem-ai-engine/README.md`
- `../../packages/padiem-control-plane/README.md`
- `../../apps/korean-ai-platform/README.md`
- `../../apps/padiem-chat/README.md`
- `../../apps/korean-ai-code-agent/docs/00_SOURCE_OF_TRUTH.md`
- `../internal-platform/README.md`

Historical capability inventory remains available in `PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`, but this document controls current cross-layer topology and the current Padiem routing-profile interpretation.