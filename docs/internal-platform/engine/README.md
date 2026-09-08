# IP-ENGINE · Padiem AI Engine

```text
DOC_STATUS = CANONICAL_COMPONENT_GUIDE
PLATFORM_ID = IP-ENGINE
SOURCE = apps/padiem-ai-engine/**
LAST_VERIFIED = 2026-09-08
```

Padiem AI Engine은 IP-CORE의 공용 의미론을 다른 runtime/product가 안전하게 사용할 수 있도록 노출하는 **trusted cross-runtime service boundary**입니다.

## Owns

- first-party caller/service identity boundary
- internal wire/service projection
- cross-runtime execution and streaming surfaces
- orchestration/service continuation projection where the current manifest marks it available
- capability/contract manifest and truthful availability reporting
- transport-level request/response projection and safe failure boundary

## Does not own

- Core의 generic AI semantics
- 제품 UX/domain state
- Provider/model catalog or inference credentials
- B14 route selection authority
- Control Plane's canonical identity/tenant/entitlement truth

## Canonical flow

```text
Product / Adapter
 -> IP-ENGINE
 -> IP-CORE
 -> B14
 -> Provider / Model
```

## Availability rule

Engine source contains multiple services/projections. A module existing in `apps/padiem-ai-engine/app/**` does not by itself prove that the corresponding route/binding is active.

```text
SOURCE_PRESENT != MANIFEST_AVAILABLE != BINDING_READY != PRODUCTION_ACTIVE
```

For exact current capability status, inspect the merged Engine capability/contract manifest and composition code. Historical issue/architecture tables are evidence snapshots, not live availability registries.

## Source entrypoints

- `apps/padiem-ai-engine/app/**` — service/runtime composition and projections
- `apps/padiem-ai-engine/worker.py` — Worker composition entrypoint
- `apps/padiem-ai-engine/worker_identity.py` — trusted caller/service identity boundary
- `apps/padiem-ai-engine/tests/**` — contract and behavior evidence

Central ownership authority:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
