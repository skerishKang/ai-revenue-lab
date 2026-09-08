# IP-CORE · Padiem AI Core

Padiem AI Core is Padiem's shared, product-neutral AI semantics/runtime layer.

```text
PLATFORM_ID = IP-CORE
CANONICAL_SOURCE = packages/padiem-ai-core/**
BUSINESS_NUMBER = NONE
```

Cross-layer authority: `../../docs/architecture/PADIEM_AI_VERTICAL_STACK.md`  
Layer boundary: `BOUNDARY.md`

## Canonical architecture

Cross-runtime default:

```text
Padiem Product / Business
  -> Product Adapter
  -> IP-ENGINE · Padiem AI Engine
  -> IP-CORE · Padiem AI Core
  -> B14 · General AI Router Platform
  -> Provider / Model
```

An accepted same-runtime/library consumer may use:

```text
Product -> Product Adapter -> IP-CORE -> B14 -> Provider/Model
```

That exception is a composition choice, not a change in ownership.

IP-CONTROL / Padiem Control Plane supplies cross-cutting canonical identity/tenant/entitlement/usage/audit truth where required.

## Core ownership

Core owns reusable AI semantics and bounded execution contracts. Current source includes shared primitives in these capability families:

- execution and streaming;
- multimodal request semantics;
- context permission / knowledge-boundary handling;
- Web / Research / grounding / source quality;
- Evidence / citation / verification / claim assessment;
- Tool Runtime and Tool Registry;
- Connector Registry and reusable connector/tool authorization semantics;
- Memory / RAG read/write/context semantics;
- Skill package/registry/activation semantics;
- Agent definition/planning/approval/delegation/recovery;
- orchestration and normalized execution events;
- execution context, timeout/cancellation/idempotency semantics;
- shared adapter/conformance boundaries.

The existence of a Core primitive does not imply that every Engine projection or Production binding is available.

## What Core does not own

Core must not become:

- a product UI or product-domain model;
- a cross-runtime service gateway that competes with IP-ENGINE;
- a provider/model registry or Router Platform;
- a credential vault exposed to products/models;
- canonical identity/tenant/entitlement/billing authority;
- a product-specific persistence schema.

Products may narrow shared policy through a bounded Product Adapter but cannot disable mandatory fail-closed rules or create a competing generic implementation.

## B14 execution boundary

Core contains bounded B14 execution/streaming contracts and clients so shared execution semantics can reach the model layer. These are **transport/execution contracts, not route authority**.

B14 owns:

- provider/model catalog;
- provider adapters;
- inference credential references;
- route selection/policy;
- retirement/availability/executability checks;
- actual external model invocation;
- provider-specific failure normalization below the shared boundary.

Current Padiem Routing Profile v1 is declared outside Core in:

`packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py`

Current product mapping:

```text
Padiem Plus -> kilo/poolside-laguna-s-2.1-free
Padiem Pro  -> kilo/nvidia-nemotron-3-ultra-550b-a55b-free
Padiem Max  -> HOLD
```

Core must not turn an omitted product model into a silent implicit route. The current no-Auto policy is Padiem-profile-specific; B14's generic future autorouter remains a valid Router Platform capability.

## Engine relationship

IP-ENGINE is the trusted cross-runtime projection of Core.

```text
CORE CAPABILITY IMPLEMENTED
!= ENGINE CONTRACT AVAILABLE
!= ENGINE BINDING CONFIGURED
!= PRODUCTION ACTIVE
```

Use `apps/padiem-ai-engine/**`, its tests and current contract manifest for Engine availability truth.

## Tool / Connector boundary

Reusable Tool and Connector semantics belong to Core:

```text
trusted registered tool/connector
  -> authorization / scope / ownership check
  -> approval / external-authorization check
  -> bounded handler execution
  -> normalized result/evidence
```

Products own connector UX and product-specific intent. Cross-runtime execution is projected through Engine where accepted. OAuth/credential lifecycle belongs to the explicitly assigned trusted control/credential authority; raw secret values never enter Core public contracts or model context.

## Memory / RAG boundary

Core owns product-neutral memory/retrieval permission, receipts, idempotency, ranking/context assembly and fail-closed semantics.

Products/storage adapters still own:

- actual persistence;
- domain-specific storage and locators;
- product-specific candidate generation;
- user-facing memory UX.

For example, StoryMemory owns its reading locator/progress/spoiler semantics; Core consumes normalized bounded candidates/permissions rather than absorbing the StoryMemory domain model.

## Agent / Skill / orchestration boundary

Core owns reusable Agent, Skill, Tool, approval/recovery/delegation and orchestration semantics. Padiem Claw and Padiem Chat consume these capabilities through product adapters/surfaces; they must not implement a second generic agent/runtime authority.

A Claw task/run/workspace/sandbox lifecycle is B54 product semantics, not the generic Core Agent lifecycle.

## Evidence / Web / Research boundary

Core owns shared evidence provenance, relevance/source quality, grounding, citation/verification and reusable research semantics. Products own domain-specific queries, presentation, product copy and allowed domain context.

Web/connector/provider credentials remain trusted server configuration. Tests using mock transports do not prove live provider availability.

## Security invariants

- no caller/system text may mint provider, tool, connector, identity or approval authority;
- provider/connector secret values are not returned to products/models;
- raw upstream/provider errors are normalized;
- private corpus/context bytes are not exposed through diagnostics;
- hidden retry/fallback is not introduced above B14 policy;
- product adapters may narrow authority, never widen it beyond the shared contract.

## Status vocabulary

Use explicit states:

```text
IMPLEMENTED_CORE_PRIMITIVE
INTEGRATED_CONSUMER_PATH
ENGINE_PROJECTION_AVAILABLE | ENGINE_PROJECTION_DEFERRED
CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

No earlier state implies a later one.

## Product adoption examples

- **B62 Padiem Chat** — owns general chat/product UX; consumes Core/Engine/B14.
- **B54 Padiem Claw** — owns business-agent workflow/product semantics; consumes shared Agent/Skill/Tool/Connector/Memory semantics.
- **B61 StoryMemory** — owns reading/corpus/domain semantics; consumes shared context/evidence/memory/model execution.
- **B53 Padiem Sidecar** — embedded product consuming the shared stack through IP-SIDECAR/IP-ENGINE when that runtime is applicable.
- **B30 / 400 AI Finder and other products** — should reuse shared Web/Research/Evidence rather than fork it.

## Historical documentation

`docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md` is a useful 2026-09-01 capability snapshot but contains older route/status assumptions. Current cross-layer authority is `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`.

Older `P01` issue/file names remain historical program lineage. The current platform layer names are IP-CORE and IP-ENGINE.

## Tests

Run the current package test suite and the repository CI appropriate to the changed capability. Exact current source/CI is stronger authority than old issue-specific commands.

Source merge is not Production activation, and documentation changes authorize no deploy/secret/provider/database mutation.