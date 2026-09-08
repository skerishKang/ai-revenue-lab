# Padiem AI Product Consumer Matrix

```text
DOC_STATUS = CANONICAL_PRODUCT_MATRIX
OWNER = Padiem platform architecture + product owners
SCOPE = how Padiem products consume shared AI layers without transferring domain ownership
LAST_VERIFIED = 2026-09-08
SUPERSEDES = fragmented product-to-platform relationship descriptions only
```

이 문서는 제품이 **어떤 공용 AI 계층을 소비하는지**를 보여줍니다. 제품의 세부 기능 상태나 Production 활성화 여부를 나타내는 live dashboard가 아닙니다.

## Matrix

| Product / surface | Product-owned domain/UX | IP-SIDECAR | IP-ENGINE | IP-CORE | IP-CONTROL | B14 | Notes |
|---|---|---|---|---|---|---|---|
| **B62 Padiem Chat** | chat UX, conversations, Projects, attachments, Saved Outputs, product modes | not architectural owner | approved cross-runtime/orchestration path | execution, grounding, evidence and shared semantics | identity/approval/entitlement paths where composed; tier declaration consumer | actual model execution | standalone general AI front door |
| **B54 Padiem Claw / KAgent** | task/run/workspace/repository/GitHub product flow | not owner | target/default cross-runtime agent/orchestration boundary | Agent/Tool/Skill/approval/recovery/orchestration reuse | identity/entitlement/usage/audit where integrated | model execution | current product docs must distinguish network-free preview from real activation |
| **B61 StoryMemory** | Reader, locator grammar, progress, knowledge ceiling, spoiler/no-future semantics, annotations, product retrieval adapter | candidate consumer when formally activated | accepted cross-runtime AI path | retrieval permission, context boundary, evidence/execution semantics | account/entitlement authority where integrated | model execution | Bible/classic-work locator meaning stays in B61 |
| **B53 Padiem Sidecar** | commercial product, onboarding, install UX, packaging/customer journey | primary commercial distribution relationship to proposed IP-SIDECAR | downstream execution boundary | downstream shared semantics | tenant/entitlement/usage/audit | model execution | B53 product != IP-SIDECAR runtime |
| **B14 Korean AI Platform** | Korean-first platform workspace and B14 product UX | no | may be downstream execution dependency, not product adapter | consumes/aligns shared execution contracts where composed | neutral Padiem tier declarations may feed B14 validation | **owner** | Provider/model/router/credentials/execution authority |
| **Living Learning** | learning-domain UX/state | not required by default | according to runtime composition | accepted selected Core consumer paths | as integrated | model execution | product semantics remain local |
| **B30 / 400 AI Finder** | product search/domain UX | candidate first-party consumer | target downstream | target shared semantics | as integrated | model execution | IP-SIDECAR candidate from current architecture planning |
| **B23 / LoveBud** | LoveBud product/domain UX | candidate first-party consumer | target downstream | target shared semantics | as integrated | model execution | IP-SIDECAR candidate; product domain remains external/local authority |

`candidate` / `target`는 architecture reuse 후보라는 뜻이며 source/runtime/Production 활성화를 뜻하지 않습니다.

## B62 · Padiem Chat

Canonical product source:

```text
apps/padiem-chat/**
```

Current ownership:

- user-facing chat/product UI
- conversation continuity/history
- Projects/project context
- ephemeral attachment UX and product validation
- Saved Outputs and local copy/download presentation
- product TaskMode/profile presentation

Shared dependencies:

```text
Chat product state
 -> product adapter
 -> Core execution/grounding semantics
 -> Engine when cross-runtime service boundary is needed
 -> B14 execution
```

Plus/Pro/Max route identities are declared through the neutral Control Plane contract. Chat must not carry a competing Provider/model registry.

## B54 · Padiem Claw

Canonical source:

```text
apps/korean-ai-code-agent/**
```

B54 owns repository/task/run/workspace/GitHub product semantics. Shared Agent/Tool/Skill/approval/recovery/orchestration semantics belong to Core and their cross-runtime projection belongs to Engine.

A deterministic/mock B14 adapter or product preview does not prove a live provider call.

## B61 · StoryMemory / Bible

B61 keeps reading-domain meaning local:

```text
current_work
current_locator
furthest_read_progress
knowledge_ceiling
Bible/classic-work locator grammar
annotation/bookmark/note semantics
current/prior/future classification
spoiler/no-future UX
```

Shared pipeline:

```text
StoryMemory domain retrieval
 -> bounded product-neutral candidates
 -> Core retrieval/permission/context/evidence
 -> Engine cross-runtime projection
 -> B14 model execution
```

The public conformance authority is `docs/architecture/PADIEM_AI_RETRIEVAL_CONSUMER_CONFORMANCE_v1.md`. Private StoryMemory corpus/source does not need to be moved into this repository to establish platform ownership.

## B53 · Padiem Sidecar and IP-SIDECAR

These identities must never be collapsed in documentation.

```text
B53 = commercial product
IP-SIDECAR = reusable embedded runtime candidate
```

Product/customer-specific adapters remain outside IP-SIDECAR. Generic reasoning, Tool, Skill, Agent, Memory and Evidence semantics remain Core-owned.

## B14 · execution authority

Every consumer reaches Provider/model execution through B14 rather than inventing a product-local router.

Current Padiem product tier declarations are sourced from:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
```

Current executability/catalog authority remains:

```text
apps/korean-ai-platform/app/pilot/**
```

## New product onboarding

새 AI 제품은 이 matrix에 추가하기 전에 다음을 명시합니다.

```text
PRODUCT_DOMAIN_OWNER = ...
AI_CONSUMER_MODE = DIRECT_CORE_CONSUMER | ENGINE_CONSUMER | SIDECAR_CONSUMER | B14_PRODUCT
SHARED_CAPABILITIES_REUSED = ...
PRODUCT_ADAPTER = ...
PROVIDER_ROUTING_OWNER = B14
PRODUCTION_ACTIVATION_EVIDENCE = separate
```

새 제품 때문에 platform topology가 바뀐다면 먼저 `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`와 Internal Platform registry를 갱신합니다.
