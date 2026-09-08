# Padiem Internal Platform Registry

Status: canonical Internal Platform catalog.

This registry is the authoritative catalog for shared Padiem platform components that are **not numbered Businesses**. Business-number authority remains `docs/portfolio/BUSINESS_REGISTRY.md`.

## 1. Registry rules

Every Internal Platform entry records a stable `IP-*` identifier, canonical name, source path, runtime/deployment class where applicable, ownership and non-ownership boundaries, dependencies, consumers, current platform state, and authority documents.

Internal Platform IDs must never collide with or masquerade as Business numbers.

## 2. Canonical components

### IP-CORE — Padiem AI Core

```text
ID = IP-CORE
CANONICAL_NAME = Padiem AI Core
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = packages/padiem-ai-core/
BUSINESS_NUMBER = NONE
RUNTIME_CLASS = shared Python package / AI runtime library
AUTHORITY_DOC = packages/padiem-ai-core/BOUNDARY.md
```

Owns shared, product-neutral AI contracts and runtime semantics, including established execution, grounding/evidence, streaming, Tool, Web/Research, retrieval/memory, context-permission and orchestration foundations.

Does not own product-domain semantics, provider/model selection policy, provider credentials, product-specific UI/persistence, or cross-runtime Cloudflare service identity.

Primary execution dependency: B14 Korean AI Platform.

### IP-ENGINE — Padiem AI Engine

```text
ID = IP-ENGINE
CANONICAL_NAME = Padiem AI Engine
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = apps/padiem-ai-engine/
BUSINESS_NUMBER = NONE
RUNTIME_CLASS = Cloudflare Worker / internal service boundary
WORKER = padiem-ai-engine
```

Owns the cross-runtime service boundary around Core, including accepted execute/stream/orchestration transport surfaces, Service Binding hosting, first-party caller identity/authentication and runtime composition exposed to trusted product adapters.

Does not own product/fandom/book/chat semantics, Core generic AI semantics, B14 provider/model routing authority, or product credentials/browser-visible secrets.

Dependencies: `IP-CORE` and B14 Korean AI Platform.

### IP-CONTROL — Padiem Control Plane

```text
ID = IP-CONTROL
CANONICAL_NAME = Padiem Control Plane
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = packages/padiem-control-plane/
BUSINESS_NUMBER = NONE
RUNTIME_CLASS = shared control-plane / policy package
```

Owns reusable platform control-plane contracts and accepted governance state that should not be buried in one product implementation, including canonical identity/tenant/entitlement/usage/audit contracts where explicitly composed.

It does not become the owner of product-local authorization, records, UI, Core runtime semantics, Engine service identity or B14 provider credentials merely because it participates in platform policy.

### IP-SIDECAR — Padiem Embedded AI Runtime

```text
ID = IP-SIDECAR
CANONICAL_NAME = Padiem Embedded AI Runtime
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = packages/padiem-embedded-runtime/
SOURCE_PRESENT = YES
S2_MINIMAL_RUNTIME_CONTRACT = LANDED
BUSINESS_NUMBER = NONE
RUNTIME_CLASS = reusable embedded shell/context/event/presentation/bootstrap primitives
ENGINE_CONNECTIVITY = NO
LIVE_PROVIDER_EXECUTION = NO
PRODUCTION_ACTIVE = NO
PRIMARY_COMMERCIAL_PRODUCT = B53 Padiem Sidecar
AUTHORITY_DOC = docs/internal-platform/sidecar/README.md
```

Owns reusable browser-safe embedded primitives only: shell lifecycle, bounded bootstrap/config, host-context envelopes, public-safe event projection, presentation/bootstrap defaults and the host adapter integration contract.

Does not own product-domain semantics, Engine service identity/transport, Core AI semantics, B14 provider routing/credentials, Control Plane authority or browser-visible secrets.

Ownership chain:

```text
Host/Product Adapter
  -> IP-SIDECAR
  -> IP-ENGINE
  -> IP-CORE
  -> B14
  -> Provider / Model

IP-CONTROL = cross-cutting canonical identity / tenant / entitlement / usage / billing / audit authority
```

B53 remains a numbered Business and is the primary commercial consumer, not the owner, of IP-SIDECAR. The S2 package is source-present and testable but intentionally has no real Engine transport or Production activation yet.

Refs #1739 #2135.

## 3. Execution dependency that remains a Business

### B14 — Korean AI Platform

B14 is **not** reclassified as an Internal Platform component.

```text
BUSINESS = B14
NAME = Korean AI Platform
SOURCE = apps/korean-ai-platform/
ROLE = provider access / Router Core / provider adapter / model execution authority
```

Internal Platform records reference B14 where model execution is required. B14 remains in the canonical Business registry and retains its Business identity.

## 4. Default product adoption path

```text
Business / product domain intent
        |
        v
Product adapter
        |
        +--> IP-SIDECAR when an embedded host surface needs reusable shell/context/event primitives
        |
        v
IP-ENGINE           cross-runtime transport and service identity
        |
        v
IP-CORE             reusable AI contracts/runtimes
        |
        v
B14                 provider/model/routing/execution authority
        |
        v
Provider / Model

IP-CONTROL = cross-cutting accepted platform control authority
```

A same-runtime package consumer may reuse IP-CORE directly when that architecture is explicitly accepted. External and cross-runtime products should not bypass IP-ENGINE merely for convenience. IP-SIDECAR must not be used as a substitute for Engine or Core.

## 5. Current discovery shortcuts

| Need | Look here first |
|---|---|
| Shared AI runtime capability | `IP-CORE` / `packages/padiem-ai-core/` |
| Service Binding, caller identity, Engine wire | `IP-ENGINE` / `apps/padiem-ai-engine/` |
| Platform control/policy contracts | `IP-CONTROL` / `packages/padiem-control-plane/` |
| Embedded host shell/context/event primitives | `IP-SIDECAR` / `packages/padiem-embedded-runtime/` |
| Provider/model/router behavior | B14 / `apps/korean-ai-platform/` |
| Product-specific behavior | the product/Business workspace |

## 6. Issue naming convention

New platform Issues should prefer canonical prefixes:

```text
[IP-CORE] ...
[IP-ENGINE] ...
[IP-CONTROL] ...
[IP-SIDECAR] ...
```

Historical prefixes such as `[P01/Core]`, `[P01/Engine]`, `[Padiem AI Core]` and `[Padiem AI Engine]` remain valid historical references but are aliases, not competing component identities.

## 7. Source-path governance

This registry is a discoverability/governance layer. It does not authorize arbitrary relocation of established sources:

```text
packages/padiem-ai-core/
apps/padiem-ai-engine/
packages/padiem-control-plane/
packages/padiem-embedded-runtime/
```

Existing build, import, CI, Worker and deployment paths remain authoritative unless a separate migration is explicitly approved.

Refs #1707 #1698 #1739 #2135.
