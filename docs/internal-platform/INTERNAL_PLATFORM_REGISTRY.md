# Internal Platform Registry

```text
DOC_STATUS = CANONICAL_REGISTRY
OWNER = Padiem platform architecture
SCOPE = Internal Platform identity, source authority and dependency boundaries
LAST_VERIFIED = 2026-09-08
SUPERSEDES = NONE
```

## Registry

| ID | Canonical name | Source authority | Runtime role | Lifecycle | Primary dependency |
|---|---|---|---|---|---|
| `IP-CORE` | Padiem AI Core | `packages/padiem-ai-core/**` | reusable AI contracts and product-neutral semantics | active source | B14 execution boundary |
| `IP-ENGINE` | Padiem AI Engine | `apps/padiem-ai-engine/**` | trusted cross-runtime service/API projection of Core | active source | IP-CORE, B14 through accepted composition |
| `IP-CONTROL` | Padiem Control Plane | `packages/padiem-control-plane/**` | identity/subject/tenant/entitlement/usage/audit and neutral declarations | active source | product/runtime integrations |
| `IP-SIDECAR` | Padiem Embedded AI Runtime | source authority not declared active by this document | reusable embedded shell/host bridge/runtime presentation | **PROPOSED** | IP-ENGINE → IP-CORE → B14 |

## External numbered execution dependency

```text
B14 = Korean AI Platform / General AI Router Platform
```

B14 remains a Business and is **not** renumbered as an Internal Platform component. It is the canonical inference execution dependency for Padiem products and Internal Platform composition.

B14 owns:

- Provider/model registry and catalog
- inference credential binding/handling
- executable route validation
- provider adapter/upstream transport
- actual model invocation and normalized execution result
- B14-level route/fallback/retry/cost/availability policy

## IP-CORE

```text
SOURCE = packages/padiem-ai-core/
```

Owns reusable, product-neutral semantics including accepted portions of:

- execution and streaming contracts
- bounded multimodal execution semantics
- grounding/search/evidence
- context permission/knowledge boundary
- retrieval and memory/RAG semantics
- Tool/Connector contracts and authorization
- Skill contracts/registry/activation
- Agent and orchestration semantics
- safe error/metadata/conformance contracts

Does not own product UI/domain state, Provider catalog/credentials, or a second model router.

## IP-ENGINE

```text
SOURCE = apps/padiem-ai-engine/
```

Owns:

- internal trusted service boundary
- caller identity/service authorization at the service edge
- wire projection of accepted Core semantics
- cross-runtime execution/stream/orchestration surfaces
- truthful capability/contract manifest

Does not redefine Core semantics and does not own public product UX or Provider/model routing.

## IP-CONTROL

```text
SOURCE = packages/padiem-control-plane/
```

Owns or is the neutral home for cross-product authority such as:

- canonical subject/identity bridge contracts
- tenant/workspace authority where accepted
- entitlement/usage/credits/subscription/audit contracts where accepted
- connector/OAuth authority components assigned to Control Plane
- neutral product declarations shared by more than one product

Current example:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
```

This declares Padiem Plus/Pro/Max route identities. It does not execute the route; B14 remains final executability authority.

## IP-SIDECAR

```text
CANONICAL_NAME = Padiem Embedded AI Runtime
COMMERCIAL_PRODUCT = B53 Padiem Sidecar
STATUS = PROPOSED
```

Target ownership:

- reusable embedded panel/drawer/inline/mobile shell primitives
- host page context/event bridge
- browser-safe streaming lifecycle projection
- evidence/citation presentation primitives
- action proposal/confirmation presentation primitives
- bootstrap/version/integration diagnostics
- host-safe failure/disable behavior

Must not own:

- B53 pricing/onboarding/customer packaging
- host/product domain meaning
- IP-ENGINE machine/service authority
- IP-CORE AI semantics
- B14 Provider/model routing or secrets
- IP-CONTROL tenant/entitlement/usage truth

This registry entry documents the target identity only; it does not claim source/runtime/Production activation.

## Consumer rule

Every product AI integration should identify itself as one of:

```text
DIRECT_CORE_CONSUMER      # same-runtime and explicitly approved
ENGINE_CONSUMER           # default cross-runtime path
SIDECAR_CONSUMER          # embedded host UI path after IP-SIDECAR activation
B14_PRODUCT               # B14's own product UI/execution workspace
```

Product adapters remain product-owned in every case.

## Registry change policy

Any change to an Internal Platform ID, source authority, or ownership boundary requires:

1. architecture review;
2. overlap check against existing Core/Engine/Control/B14 ownership;
3. update to `PADIEM_AI_VERTICAL_STACK.md` if topology changes;
4. update to `AI_PRODUCT_CONSUMER_MATRIX.md` if consumer relationships change;
5. no Business number creation solely to represent shared infrastructure.
