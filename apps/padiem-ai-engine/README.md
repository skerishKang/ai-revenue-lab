# IP-ENGINE · Padiem AI Engine

Padiem AI Engine is the trusted **cross-runtime service boundary** for reusable Padiem AI capabilities.

It is an Internal Platform component, not a numbered Business.

```text
PLATFORM_ID = IP-ENGINE
CANONICAL_SOURCE = apps/padiem-ai-engine/**
BUSINESS_NUMBER = NONE
```

Canonical cross-layer architecture:

`../../docs/architecture/PADIEM_AI_VERTICAL_STACK.md`

## Role

```text
Product / Business
  -> Product Adapter
  -> Padiem AI Engine
  -> Padiem AI Core
  -> B14 Router Platform
  -> Provider / Model
```

Engine exposes accepted Core capabilities across process/runtime boundaries through trusted, bounded and versioned internal contracts.

Engine owns:

- trusted first-party caller/service identity enforcement;
- internal execute/stream/orchestration transport;
- continuation/cancel/resume service boundaries where the current contract manifest permits them;
- versioned wire projection of Core semantics;
- safe public-to-product error/event projection at the service boundary;
- capability/contract manifest truth for Engine-exposed routes;
- cross-runtime compatibility and service composition.

Engine does **not** own:

- product UX or product/domain semantics;
- generic AI reasoning/policy that belongs to Core;
- provider/model catalog, routing, fallback or inference credentials;
- canonical user/tenant/entitlement/billing truth;
- arbitrary public-browser machine credentials.

## Core relationship

IP-CORE owns reusable AI semantics. IP-ENGINE transports/projects those semantics.

```text
CORE CAPABILITY EXISTS
!=
ENGINE PROJECTION AVAILABLE
```

A Core primitive can exist while its Engine projection remains deferred or unavailable. Engine route/feature status must follow the current contract manifest and tests rather than documentation assumptions.

## B14 relationship

B14 remains the General AI Router Platform and external model execution authority.

Engine must not become a second router or embed a competing provider/model registry. Product/model route declarations are resolved through the accepted product/Core/B14 contracts; exact provider/model executability remains B14 authority.

## Control Plane relationship

IP-CONTROL supplies canonical subject/tenant/entitlement/usage/audit truth where a service contract requires it. Engine validates/consumes trusted projections; it does not recreate account/billing truth.

## Tool / Connector relationship

Reusable Tool/Connector semantics belong to Core. Engine may expose accepted Tool/Connector execution across runtimes after the relevant composition/binding is real.

```text
Core Tool/Connector source exists
!= Engine binding configured
!= Production connector active
```

Product-local connector UI is not Engine authority, and Engine must not expose raw connector credentials to products or models.

## Public/browser boundary

Engine is an internal service boundary. Products normally expose same-origin/product APIs to browsers and call Engine from trusted server-side code/service bindings.

A browser-facing product must not obtain machine/service credentials merely because an Engine endpoint exists.

## Runtime truth

The source under `app/**`, `worker.py`, tests and the current contract manifest are authoritative for route/capability availability.

Use this status distinction:

```text
SOURCE_PRESENT
CONTRACT_AVAILABLE
BOUND_CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

Do not collapse these states.

## Development / verification

Run the relevant Engine test suite from this workspace. Exact commands may evolve with `pyproject.toml` and CI; current repository source/CI is stronger authority than old issue runbooks.

Production activation/deployment remains separately gated and is never authorized by documentation changes alone.