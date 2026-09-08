# IP-CORE · Padiem AI Core — Current Boundary & Ownership

Status: **CURRENT LAYER BOUNDARY**

Cross-layer authority:

`../../docs/architecture/PADIEM_AI_VERTICAL_STACK.md`

This document replaces the older point-in-time boundary text that grouped Engine with B14 and described `b14/auto` as the Padiem product default. Those statements are historical and are no longer current architecture authority.

## Identity

```text
PLATFORM_ID = IP-CORE
NAME = Padiem AI Core
CANONICAL_SOURCE = packages/padiem-ai-core/**
BUSINESS_NUMBER = NONE
```

Local worktrees such as `E:\padiem-ai-core` are development workspaces only. The repository authority remains `skerishKang/ai-revenue-lab`.

## Canonical topology

### Cross-runtime

```text
Padiem Product / Business
  -> Product Adapter
  -> IP-ENGINE · Padiem AI Engine
  -> IP-CORE · Padiem AI Core
  -> B14 · General AI Router Platform
  -> Provider / Model
```

### Explicit same-runtime/library integration

```text
Product
  -> Product Adapter
  -> IP-CORE
  -> B14
  -> Provider / Model
```

The same-runtime form is allowed only where an accepted architecture explicitly permits it. It does not change ownership and does not make a product a shared AI service.

IP-CONTROL / Padiem Control Plane is cross-cutting canonical identity/tenant/entitlement/usage/audit authority rather than a mandatory sequential model-request hop.

## Core owns

Padiem AI Core owns reusable, product-neutral AI semantics and bounded runtime contracts, including the accepted implementations for areas such as:

- execution and streaming contracts;
- context trust/permission and knowledge-boundary semantics;
- Evidence, grounding, source quality and Web/Research semantics;
- Tool and Connector authorization/side-effect semantics;
- Memory/RAG read/write/context semantics;
- Skill package/registry/activation semantics;
- Agent definition/planning/approval/delegation/recovery semantics;
- orchestration and normalized execution events;
- shared adapter/conformance and bounded fail-closed behavior.

Core may contain bounded clients/transports for B14, but those transports do not make Core a provider/model router.

## Core does not own

- product UI, product/domain state or product-local persistence;
- cross-runtime service identity/transport authority — IP-ENGINE owns that;
- provider/model registry, provider credentials, route selection, generic fallback or external model invocation — B14 owns that;
- canonical account/tenant/entitlement/billing truth — IP-CONTROL owns that;
- B54 Claw task/repository/sandbox/product workflow semantics;
- B61 StoryMemory reading/locator/spoiler/domain semantics;
- B62 Chat conversations/Projects/files/Saved Outputs/product UX;
- B53 Sidecar customer/product adapter semantics.

## B14 relationship

```text
IP-CORE
  -> normalized model execution request
  -> B14
  -> exact approved provider/model
```

B14 is the General AI Router Platform and final provider/model execution authority.

Current Padiem Routing Profile v1 is explicit:

```text
Plus -> kilo/poolside-laguna-s-2.1-free
Pro  -> kilo/nvidia-nemotron-3-ultra-550b-a55b-free
Max  -> HOLD
```

The profile declaration lives in `packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py`. Core does not own those product mappings and must not synthesize an implicit product route merely because a model identifier is omitted.

The current Padiem no-Auto rule is profile-specific. It does not delete B14's future generic autorouter capability.

## Engine relationship

IP-ENGINE exposes accepted Core capabilities across runtime/service boundaries.

```text
CORE CAPABILITY PRESENT
!= ENGINE PROJECTION AVAILABLE
!= PRODUCTION BINDING ACTIVE
```

Engine's current contract manifest and tests are the runtime authority for which projections are available/deferred/unavailable.

## Connector relationship

Reusable Tool/Connector semantics belong to Core. Product connector UX and business-domain intent remain product-owned; cross-runtime connector execution is projected through Engine when accepted.

Connector credential/OAuth lifecycle may belong to IP-CONTROL or another explicitly assigned trusted credential authority. Raw secrets never become Core public contracts or model-context authority.

## Security / secret boundary

- provider and connector secret values remain server-side;
- no raw secret appears in browser state, product route declarations, model context, safe logs or committed docs;
- Core transport errors are normalized rather than reflecting raw upstream bodies;
- user/model text cannot mint tool, connector, route, approval or identity authority;
- tests/mocks do not prove live Provider/connector readiness.

## Availability truth

Always distinguish:

```text
CORE_PRIMITIVE_IMPLEMENTED
ENGINE_PROJECTED
CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

Documentation changes do not authorize Production mutation.

## Historical note

Older P01-prefixed issues/files remain valid lineage for the program that built shared Core/Engine capabilities. `P01` is not a separate current platform layer. Canonical platform names are IP-CORE and IP-ENGINE.

The former `B14 AI Reward Router` naming remains invalid: B14 is Korean AI Platform / General AI Router Platform; B64 AI Reward Router is a separate product where still registered by current portfolio authority.