# Padiem AI Engine · IP-ENGINE

Padiem AI Engine is Padiem's trusted **cross-runtime service boundary** for exposing accepted Padiem AI Core semantics to first-party products and runtimes.

Canonical architecture:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/internal-platform/engine/README.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`

## Boundary

```text
Product / Business adapter
        │
        ▼
Padiem AI Engine · IP-ENGINE
        │
        ▼
Padiem AI Core · IP-CORE
        │
        ▼
Business 14 · Korean AI Platform
        │
        ▼
Provider / Model
```

Engine owns internal service/wire projection, trusted caller identity at the service boundary, and cross-runtime exposure of accepted Core execution/orchestration semantics. It does not own product UX, product domain semantics, a competing Core policy layer, Provider/model catalog, or inference credentials.

## Source layout

```text
apps/padiem-ai-engine/
├─ app/                 # services, wire projections, capability/composition modules
├─ clients/             # first-party client contracts/adapters
├─ ingress/             # bounded ingress/service integration
├─ migrations/          # Engine-owned persistence migrations where applicable
├─ scripts/             # operational/test helpers
├─ tests/               # contract and behavior tests
├─ worker.py            # Cloudflare Worker composition entrypoint
├─ worker_identity.py   # trusted caller/service identity boundary
├─ pyproject.toml
└─ wrangler.toml
```

## Availability is manifest-driven

Engine has accumulated many service modules. A Python file existing on `main` is not enough to claim that a capability is available to a caller or active in Production.

```text
SOURCE_PRESENT
!= MANIFEST_AVAILABLE
!= COMPOSITION_BOUND
!= DEPENDENCY_READY
!= PRODUCTION_ACTIVE
```

For an exact current capability decision, inspect the merged capability/contract manifest, composition/worker code and tests for that revision. Dated architecture tables and issue reports are evidence snapshots.

## Ownership rules

Engine may:

- project Core request/result/event contracts across runtimes;
- enforce trusted service/caller boundary contracts;
- expose accepted execution, streaming, orchestration, continuation or shared-runtime surfaces when the current manifest/composition marks them available;
- normalize wire-level failures without leaking secrets/private payloads.

Engine must not:

- reimplement generic Tool/Skill/Agent/Memory/Evidence semantics already owned by Core;
- select arbitrary Providers/models as a second router;
- expose Provider secrets to products/browsers;
- absorb StoryMemory, Chat, Claw or other product-domain state;
- report a source-only capability as live.

## Relationship to Control Plane

Padiem Control Plane (`IP-CONTROL`) is a cross-cutting authority for canonical identity/subject/tenant/entitlement/usage/audit contracts where integrated. Engine may consume those authorities at trusted boundaries but does not replace them.

## Testing

Run the current Engine test suite appropriate to the changed slice from this workspace. Tests and source prove implementation behavior; Production activation remains a separate deployment/binding claim.
