# Padiem AI Core · IP-CORE

```text
DOC_STATUS = CURRENT_COMPONENT
PLATFORM_ID = IP-CORE
CANONICAL_NAME = Padiem AI Core
CANONICAL_SOURCE = packages/padiem-ai-core/**
LAST_VERIFIED = 2026-09-08
```

IP-CORE is Padiem's shared, product-neutral AI semantic/runtime layer. It defines reusable AI contracts and bounded runtime semantics that multiple products can consume without duplicating generic policy inside each product.

Canonical references:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`
- `docs/internal-platform/README.md`
- `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`

## Ownership boundary

```text
Product / Business adapter
        │
        ├─ same-runtime direct Core reuse only when explicitly accepted
        │
        ▼
IP-ENGINE when cross-runtime service projection is required
        │
        ▼
IP-CORE shared AI semantics/runtime
        │
        ▼
B14 Provider/model execution
        │
        ▼
Provider / Model

IP-CONTROL = cross-cutting identity / tenant / entitlement / usage / audit
```

IP-CORE owns reusable semantics. IP-ENGINE owns service projection. B14 owns Provider/model catalog, inference credentials, executable routing and actual upstream execution. Products own domain state and UX.

## IP-CORE owns

Reusable, product-neutral contracts and semantics including:

- execution request/result and shared execution context semantics;
- completed, streaming and bounded multimodal execution facades;
- grounding, search-decision and evidence-oriented research primitives;
- context permission and knowledge-boundary enforcement;
- retrieval and memory/RAG semantics without product persistence ownership;
- Evidence, citation, verification and claim-assessment semantics;
- Tool and Connector contracts, authorization and lifecycle semantics;
- reusable Skill package/registry/activation semantics;
- Agent planning, approval, delegation, recovery and event semantics;
- orchestration runner/event semantics;
- cancellation, timeout, trace and idempotency semantics;
- adapter conformance and fail-closed shared policy.

## IP-CORE must not own

- product UI, conversation/history/project state or product persistence;
- StoryMemory locator grammar, reading progress, knowledge ceiling or spoiler semantics;
- Claw task/run/repository/workspace product semantics;
- Sidecar customer packaging or host-specific business-domain semantics;
- Provider/model catalog, Provider credentials or generic route execution authority;
- canonical tenant/entitlement/billing/usage/audit truth;
- browser-owned secrets or arbitrary upstream origins.

## Product relationship

### B62 Padiem Chat

Chat consumes shared execution/grounding/evidence semantics and may use IP-ENGINE for accepted cross-runtime paths. Chat owns the general chat UX, conversation continuity, Projects, attachments, Saved Outputs and product modes.

### B54 Padiem Claw

Claw consumes shared Agent/Tool/Skill/approval/recovery/orchestration semantics. Claw owns task/run/repository/workspace/GitHub product flow.

### B61 StoryMemory

StoryMemory may consume generic retrieval/permission/context/evidence semantics. Bible/classic-work locator meaning, reading progress, knowledge ceiling and spoiler/no-future behavior remain B61-owned.

### B53 Padiem Sidecar / IP-SIDECAR

Generic reasoning, Tool, Skill, Agent, Memory and Evidence semantics remain IP-CORE-owned. Reusable embedded presentation/runtime primitives belong to IP-SIDECAR once formally activated; B53 remains the commercial product.

## Provider/model routing relationship

IP-CORE does not own Padiem Plus/Pro/Max route truth and does not maintain a competing Provider/model registry.

Current shared product-tier declaration authority:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
```

Current product policy is expressed as Plus/Pro/Max. Historical LOW/MEDIUM/HIGH profile wording is not current B62 route authority.

B14 remains final executability and execution authority:

```text
IP-CONTROL declaration
 -> B14 catalog/executability gate
 -> B14 provider adapter
 -> Provider / Model
```

## Source readiness vs activation

Core documentation distinguishes implementation from deployment:

```text
SOURCE_PRESENT
!= CONTRACT_AVAILABLE_TO_A_CONSUMER
!= ENGINE_PROJECTION_READY
!= PRODUCT_BINDING_READY
!= PROVIDER_READY
!= PRODUCTION_ACTIVE
```

A merged Core primitive or passing unit test does not itself prove a live product, Provider, connector, secret, database or Production binding.

## Security invariants

- product/user content cannot grant itself Tool, Connector, Skill or approval authority;
- raw Provider secrets remain below the trusted B14 execution boundary;
- trusted server-side connector credentials never move into browser/product state;
- untrusted retrieved/attached content is data, not instruction authority;
- product adapters may narrow shared policy but must not silently disable mandatory fail-closed behavior;
- diagnostic projections remain bounded and do not expose private payloads or hidden policy text.

## Historical detail

The pre-unification Core README, including the detailed module-by-module runtime inventory as of 2026-09-01, is preserved at:

```text
docs/history/2026-09-01/PADIEM_AI_CORE_README.snapshot.md
```

That snapshot is implementation evidence, not current ownership authority. For current architecture use this README and the canonical capability ownership registry.
