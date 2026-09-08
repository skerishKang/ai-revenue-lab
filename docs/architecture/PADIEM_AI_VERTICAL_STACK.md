# Padiem AI Vertical Stack

```text
DOC_STATUS = CANONICAL
OWNER = Padiem platform architecture
SCOPE = shared AI platform layers, product adapters, routing/provider ownership
LAST_VERIFIED = 2026-09-08
SUPERSEDES = fragmented layer descriptions only; historical evidence remains preserved
```

## 1. Purpose

Padiem은 하나의 거대한 AI 애플리케이션이 아니라, **공용 AI 플랫폼 계층 + 독립 제품/도메인 어댑터** 구조로 운영합니다. 이 문서는 AI Engine, AI Core, Control Plane, Chat, Claw, Sidecar, StoryMemory와 B14 Router/Provider 관계를 한 장의 권위로 통일합니다.

핵심 원칙은 다음과 같습니다.

```text
PRODUCTS OWN DOMAIN + UX.
IP-CORE OWNS REUSABLE AI SEMANTICS.
IP-ENGINE OWNS CROSS-RUNTIME SERVICE PROJECTION.
B14 OWNS MODEL/PROVIDER EXECUTION.
IP-CONTROL OWNS CROSS-CUTTING IDENTITY/ENTITLEMENT/USAGE/AUDIT TRUTH.
```

## 2. Canonical topology

### 2.1 Standalone / product AI path

```text
Padiem product / Business
(Chat, Claw, StoryMemory, Living Learning, future products)
        │
        │ product/domain adapter
        ▼
IP-ENGINE · Padiem AI Engine
cross-runtime trusted service boundary
        │
        ▼
IP-CORE · Padiem AI Core
shared execution / evidence / grounding / memory / tool / skill / agent semantics
        │
        ▼
B14 · Korean AI Platform
provider/model catalog + route validation + credentials + actual execution
        │
        ▼
Provider / Model
```

명시적으로 허용된 same-runtime/library consumer는 IP-ENGINE을 거치지 않고 IP-CORE를 직접 소비할 수 있습니다. 그러나 공용 의미론을 제품 안에 복제할 수 있다는 뜻은 아닙니다.

### 2.2 Embedded AI / Sidecar path

```text
Host website/app
        │
        ▼
Business / Customer Adapter
        │
        ▼
B53 Padiem Sidecar product layer
        │
        ▼
IP-SIDECAR · Padiem Embedded AI Runtime   [PROPOSED / separately registered]
        │
        ▼
IP-ENGINE
        │
        ▼
IP-CORE
        │
        ▼
B14
        │
        ▼
Provider / Model
```

`B53 Padiem Sidecar`와 `IP-SIDECAR`는 같은 것이 아닙니다.

- **B53**: 상업 제품, 설치/온보딩/패키징/고객 여정
- **IP-SIDECAR**: 여러 제품이 재사용할 수 있는 embedded AI shell/runtime 후보

IP-SIDECAR의 formal registry/source activation은 별도 승인 상태를 따라야 하며, 이 문서만으로 live runtime을 주장하지 않습니다.

### 2.3 Control Plane is cross-cutting

Control Plane은 모델 실행 스택의 한 단계라기보다 모든 계층에 걸친 **권위 평면**입니다.

```text
                    IP-CONTROL · Padiem Control Plane
        ┌──────────────────────────────────────────────────────┐
        │ identity / subject / tenant / entitlement / usage   │
        │ credits/subscription/audit + neutral declarations   │
        └──────────────────────────────────────────────────────┘
             │             │              │             │
          Product       Engine          Core           B14
```

현재 Padiem Plus/Pro/Max의 중립적 product-tier **declaration**도 Control Plane package가 소유합니다. 다만 그 route가 실제 실행 가능한지에 대한 최종 권위는 B14 catalog입니다.

## 3. Layer ownership

| Layer | Canonical ID / product | Owns | Must not own |
|---|---|---|---|
| Product/Business | B61/B62/B54/etc. | UX, domain state, product persistence, product adapter, presentation | generic AI runtime semantics, Provider credentials, generic model router |
| Embedded shell | IP-SIDECAR (proposed) | reusable panel/shell, host-context bridge, browser-safe stream/event presentation | product domain meaning, Core semantics, Engine machine auth, B14 routing |
| Service boundary | IP-ENGINE | trusted caller/service boundary, wire projection, cross-runtime execution/orchestration exposure | product UX, generic semantic authority, Provider/model routing |
| Shared semantics | IP-CORE | execution, evidence, grounding, permission, retrieval/memory semantics, Tool/Skill/Agent/orchestration contracts | product domain schema, product UI, Provider catalog/credentials |
| Execution plane | B14 | Provider/model registry, exact route validation/selection, inference credentials, upstream execution, execution-level retry/fallback policy | product memory/domain state, product UX, Control Plane identity truth |
| Cross-cutting authority | IP-CONTROL | identity, canonical subject/tenant, entitlement, usage/credits/subscription/audit, neutral cross-product declarations | model Provider execution, product conversation state |
| External execution | Provider/Model | upstream model capability | Padiem product policy |

## 4. B14 Router and Provider rule

B14는 **Korean AI Platform / general AI Router Platform**이며 Router는 B14 내부 capability입니다. 별도 `Router Business`나 별도 Provider authority를 만들지 않습니다.

```text
Product tier/profile declaration
        │
        ▼
Control Plane neutral declaration
        │
        ▼
B14 catalog/executability gate
        │
        ▼
B14 provider adapter + credential reference
        │
        ▼
Provider / Model
```

현재 Padiem v1 제품 정책은 explicit route를 사용하고 user-visible Auto/silent fallback을 사용하지 않습니다. 장기적으로 B14 자체의 generic autorouter capability를 개발할 수 있지만, 그 capability는 제품의 명시적 route policy와 구분되어야 합니다.

현재 tier/route 사실은 다음 source를 우선합니다.

- declaration: `packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py`
- execution/catalog: `apps/korean-ai-platform/app/pilot/**`
- B14 product charter: `apps/korean-ai-platform/README.md`

## 5. Product positions

### B62 · Padiem Chat

Owns:

- general AI chat UX
- conversation/history/Projects/Saved Outputs
- attachment/product presentation
- product TaskMode/profile presentation
- product-local context adapter

Consumes:

- IP-CORE execution/grounding/evidence semantics
- IP-ENGINE for approved cross-runtime/orchestration paths
- IP-CONTROL for canonical identity/approval/entitlement paths where composed
- B14 for actual model execution

Chat must not become a second Provider/model registry.

### B54 · Padiem Claw / KAgent

Owns:

- task/run/workspace/repository/GitHub product flow
- product-visible run projection
- sandbox/resource request semantics that are product-specific

Consumes or targets reuse of:

- IP-CORE Agent/Tool/Skill/approval/recovery/orchestration semantics
- IP-ENGINE trusted cross-runtime boundary
- B14 model execution
- IP-CONTROL identity/entitlement/usage/audit where integrated

KAgent source path is `apps/korean-ai-code-agent/**`. Current product docs must distinguish deterministic/mock preview from real model/runtime activation.

### B61 · StoryMemory (including Bible/classic-work domain)

B61 owns:

- reader UX
- locator grammar/order
- reading progress / knowledge ceiling
- spoiler/no-future product behavior
- annotations and product-local persistence
- StoryMemory retrieval/domain adapter

B61 does **not** move Bible/classic-work locators or reading-domain semantics into Core/Engine. Core owns generic permission/retrieval/evidence semantics; Engine projects them across runtimes; B14 performs model execution.

The accepted public conformance record is `PADIEM_AI_RETRIEVAL_CONSUMER_CONFORMANCE_v1.md`; StoryMemory private source/corpus may remain outside this repository.

### B53 · Padiem Sidecar

B53 is the commercial embedded-AI product. It does not own generic Core/Engine/B14 semantics. Reusable embedded shell/runtime primitives belong to the proposed IP-SIDECAR layer once formally registered/implemented.

### Other products

Living Learning and future Businesses may consume the same shared layers through bounded adapters. A product-specific need is not promoted merely because a second product also uses AI; promotion requires a generic contract and ownership review.

## 6. Capability classification before implementation

Every new AI capability should be classified before code is written.

```text
REUSE_CORE       = existing Core semantic can be consumed
EXTEND_CORE      = generic reusable semantic is missing
ENGINE_TRANSPORT = Core semantic exists but cross-runtime projection is missing
B14_EXECUTION    = provider/model/catalog/route/execution concern
PRODUCT_ADAPTER  = domain/product mapping or presentation
IP_SIDECAR       = reusable embedded shell/host bridge concern
CONTROL_PLANE    = identity/tenant/entitlement/usage/audit concern
DO_NOT_SHARE     = intentionally product-specific
```

If two layers both appear to own the same generic policy, implementation stops until ownership is resolved.

## 7. Credentials and secrets

Credential type matters.

- inference Provider/model credentials: **B14 trusted execution boundary**
- identity/tenant/connector authorization metadata: **Control Plane or trusted connector runtime according to that connector contract**
- Core web/tool connector server credentials may exist inside the trusted runtime that owns that capability, but never transfer model-routing authority to Core
- browser/product state must not contain raw Provider secrets

A product may carry a credential binding/reference identifier only when the relevant shared contract permits it; it does not own the secret value.

## 8. Source readiness vs runtime activation

The platform uses this distinction everywhere:

```text
SOURCE_PRESENT
!= CONTRACT_AVAILABLE
!= BINDING_CONFIGURED
!= PROVIDER_READY
!= PRODUCTION_ACTIVE
```

Documentation must therefore avoid phrases such as "live" or "available" solely because a class, endpoint or UI control exists on `main`.

## 9. Current canonical references

- `docs/README.md`
- `docs/internal-platform/README.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`
- `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md` — detailed capability inventory/audit; runtime status rows are snapshot-oriented
- `docs/architecture/PADIEM_AI_RETRIEVAL_CONSUMER_CONFORMANCE_v1.md`
- `packages/padiem-ai-core/README.md`
- `apps/korean-ai-platform/README.md`
- `apps/padiem-chat/README.md`
- `apps/korean-ai-code-agent/README.md`

When those documents disagree on volatile status, current merged source and executable contract win; when they disagree on stable ownership, this architecture + the relevant canonical registry should be reconciled before new feature work proceeds.
