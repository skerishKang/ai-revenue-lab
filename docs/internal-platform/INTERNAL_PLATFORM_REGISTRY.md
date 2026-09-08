# Padiem Internal Platform Registry

Status: canonical after review/merge of Issue #1707.

This registry is the authoritative catalog for shared Padiem platform components that are **not numbered Businesses**.

## 1. Registry rules

Every Internal Platform entry records:

- stable `IP-*` identifier;
- canonical name;
- repository and source path;
- runtime/deployment class where applicable;
- owned responsibilities;
- explicit non-ownership boundaries;
- dependencies;
- known consumers/integrations;
- current platform work;
- authority documents.

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

Owns shared, product-neutral AI contracts and runtime semantics, including the established execution, grounding, streaming, Tool, Web, Evidence, retrieval/memory, context-permission, and orchestration foundations present in the package.

Does not own:

- LoveBud/B61/B62 or other product semantics;
- provider/model selection policy;
- provider credentials;
- product-specific UI/persistence;
- cross-runtime Cloudflare service identity.

Primary dependency: B14 Korean AI Platform for provider/model execution authority.

### IP-ENGINE — Padiem AI Engine

```text
ID = IP-ENGINE
CANONICAL_NAME = Padiem AI Engine
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = apps/padiem-ai-engine/
BUSINESS_NUMBER = NONE
RUNTIME_CLASS = Cloudflare Worker / internal service boundary
WORKER = padiem-ai-engine
CURRENT_PLATFORM_WORK = #1698 multi-caller service identity registry
```

Owns the cross-runtime service boundary around Core, including internal execute/stream/orchestration transport surfaces, Service Binding hosting, first-party caller identity/authentication, and runtime composition exposed to trusted product adapters.

Does not own:

- product/fandom/book/chat semantics;
- Core's generic AI semantics;
- B14 provider/model routing authority;
- product credentials or browser-visible secrets.

Known integration authority includes B61 StoryMemory. LoveBud Scout has a merged Engine transport source integration and is awaiting independent runtime identity/binding activation after #1698.

Dependencies:

- `IP-CORE`;
- B14 Korean AI Platform.

### IP-CONTROL — Padiem Control Plane

```text
ID = IP-CONTROL
CANONICAL_NAME = Padiem Control Plane
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = packages/padiem-control-plane/
BUSINESS_NUMBER = NONE
RUNTIME_CLASS = shared control-plane/policy package
```

Owns reusable platform control-plane contracts and governance state that should not be buried in one product implementation.

It does not become the owner of product-local authorization, records, UI, or B14 provider credentials merely because it participates in platform policy.

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
Business/product domain intent
        |
        v
Product adapter
        |
        v
IP-ENGINE           cross-runtime transport and service identity
        |
        v
IP-CORE             reusable AI contracts/runtimes
        |
        v
B14                 provider/model/routing authority
        |
        v
Provider/model
```

A same-runtime package consumer may reuse IP-CORE directly when that architecture is explicitly accepted. External and cross-runtime products should not bypass IP-ENGINE merely for convenience.

## 5. Current discovery shortcuts

| Need | Look here first |
|---|---|
| Shared AI runtime capability | `IP-CORE` / `packages/padiem-ai-core/` |
| Service Binding, caller identity, Engine wire | `IP-ENGINE` / `apps/padiem-ai-engine/` |
| Platform control/policy contracts | `IP-CONTROL` / `packages/padiem-control-plane/` |
| Provider/model/router behavior | B14 / `apps/korean-ai-platform/` |
| Product-specific behavior | the product/Business workspace |

## 6. Issue naming convention

New platform Issues should prefer canonical prefixes:

```text
[IP-CORE] ...
[IP-ENGINE] ...
[IP-CONTROL] ...
```

Historical prefixes such as `[P01/Core]`, `[P01/Engine]`, `[Padiem AI Core]`, and `[Padiem AI Engine]` remain valid historical references but are aliases, not competing component identities.

## 7. No source relocation

This registry is a discoverability/governance layer. It does not authorize moving:

```text
packages/padiem-ai-core/
apps/padiem-ai-engine/
packages/padiem-control-plane/
```

Existing build, import, CI, Worker, and deployment paths remain authoritative unless a separate migration is explicitly approved.

Refs #1707 #1698.
