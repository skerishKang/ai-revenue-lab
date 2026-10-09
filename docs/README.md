# Padiem / AI Revenue Lab Documentation

```text
DOC_STATUS = CANONICAL_ENTRYPOINT
OWNER = repository documentation governance
LAST_VERIFIED = 2026-10-09
```

`docs/` is the entrypoint for **current documentation authority**. Dated audits, issue-specific designs, phase documents and Git history remain evidence; file existence alone does not make them current architecture or runtime truth.

## 문서 탐색 — 하나의 사실 원천 참조

| 구분 | 공식 진입점 | 역할 |
|---|---|---|
| 공통 | [공통 정책 및 아키텍처](common/README.md) | 기존 권위 문서로 연결 |
| 단계별 | [기획·개발·검증·배포·운영](lifecycle/README.md) | 단계별 승인·증거 기준 |
| 사업별 | [사업 문서](businesses/README.md) | Business Registry 및 각 제품 문서 |
| 모델 | [모델 공식 진입점](models/README.md) | 소유자 결정, B14 등록, 제품 라우트 및 실행 증거 구분 |
| 역사 | [역사 기록](history/README.md) | 과거 스냅샷과 현재 사실 구분 |
| 증거 | [증거 유형 및 검증 자료](evidence/README.md) | 검증 기준과 과거 기록의 출처 구분 |

**원칙:** 변동성 높은 모델 ID·등록 상태·Production SHA는 여러 제품 README에 복사하지 않습니다. 실제 원천이 변경되면 참조 문서가 이를 연결합니다. 기존 [문서 권위 규칙](governance/DOCUMENTATION_AUTHORITY_MODEL.md)은 그대로 유지합니다.

## 현재 개발·운영 상태의 단일 진입점

아래 GitHub 이슈는 **현재 작업/해결 여부를 확인하는 변동 정보**의 권위입니다. 이 인덱스는 날짜별 main SHA, 모델 목록, CI 통과 개수 또는 Production 가용성을 복제하지 않습니다.

| 확인할 문제 | 실시간 실행/보안 권위 |
|---|---|
| Padiem Golden Path FINISH-FIRST, LOCAL별 현재 소유권 | [#3523](https://github.com/skerishKang/ai-revenue-lab/issues/3523) |
| Claw 실제 답변·SSE/DOM 검증 및 남은 모델 응답 오류 | [#3382](https://github.com/skerishKang/ai-revenue-lab/issues/3382), [#3566](https://github.com/skerishKang/ai-revenue-lab/issues/3566) |
| Owner 모델 승인과 B14 실행 계약 | [모델 단일 인덱스](models/README.md), [Owner 정책](operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md) |
| Calendar 사용자별 READ 격리 설계 | [#2010](https://github.com/skerishKang/ai-revenue-lab/issues/2010) |
| Calendar READ 운영 활성화 보안 게이트 | [#2952 HARD HOLD](https://github.com/skerishKang/ai-revenue-lab/issues/2952) |
| Browser Control/Broker/Desktop 실제 제품 연결 상태 | [#3782](https://github.com/skerishKang/ai-revenue-lab/issues/3782), [브라우저 실행 ADR](architecture/PADIEM_BROWSER_EXECUTION_ADAPTER_DECISION_3782.md) |

증거 등급은 [문서 권위 모델](governance/DOCUMENTATION_AUTHORITY_MODEL.md)과 [개발 운영 정책](operations/AI_DEVELOPMENT_OPERATING_POLICY.md)을 따릅니다. **Merged source != 실제 모델 응답 != 인증된 사용자 E2E != Production 출시**입니다. GitHub의 오래된 이슈 본문/댓글·Draft PR·실험 문서는 현재 활성화 허가가 아닙니다.

## Start here

1. `architecture/PADIEM_AI_VERTICAL_STACK.md` — canonical product-to-Provider topology
2. `architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md` — stable capability ownership
3. `internal-platform/README.md` — Internal Platform overview
4. `internal-platform/INTERNAL_PLATFORM_REGISTRY.md` — IP-CORE / IP-ENGINE / IP-CONTROL / IP-SIDECAR identities
5. `internal-platform/AI_ADOPTION_PLAYBOOK.md` — reuse/extend/adapter classification
6. `product/AI_PRODUCT_CONSUMER_MATRIX.md` — product-to-platform relationships
7. `governance/DOCUMENTATION_AUTHORITY_MODEL.md` — document precedence/freshness
8. `governance/LEGACY_AI_TERMINOLOGY_MAP.md` — legacy terminology interpretation
9. `products/b66/README.md` — B66 Padiem Quote canonical product entrypoint
10. `operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md` — dated owner model selection vs runtime status

Audit trail:

- `DOCUMENTATION_AUDIT_20260908.md`
- `DOCUMENTATION_RECONCILIATION_COMPLETION_20260908.md`

## Canonical AI topology

```text
Product / Business domain + UX
        |
        +--> optional IP-SIDECAR embedded shell/context/event primitives
        |
        v
IP-ENGINE   cross-runtime trusted service boundary
        |
        v
IP-CORE     reusable AI semantics/contracts/runtime
        |
        v
B14         Provider/model catalog, routing, credentials and execution
        |
        v
Provider / Model

IP-CONTROL = cross-cutting identity / tenant / entitlement / usage / audit
             + neutral cross-product declarations
```

Same-runtime consumers may use IP-CORE directly only when architecture explicitly permits it. Products must not create a second generic Provider/model router or shared AI policy engine.

## Current component and product authority

```text
packages/padiem-ai-core/README.md           -> IP-CORE
apps/padiem-ai-engine/README.md             -> IP-ENGINE
packages/padiem-control-plane/README.md     -> IP-CONTROL
packages/padiem-embedded-runtime/README.md  -> IP-SIDECAR S2 source contract
docs/internal-platform/sidecar/README.md     -> IP-SIDECAR ownership/readiness
docs/products/padiem-sidecar/README.md       -> B53 Padiem Sidecar commercial product authority
apps/korean-ai-platform/README.md            -> B14 execution platform
apps/padiem-chat/README.md                   -> B62 Padiem Chat
apps/korean-ai-code-agent/README.md          -> B54 Padiem Claw
docs/products/b66/README.md                  -> B66 Padiem Quote
```

## Product boundary locks

- **B62 Padiem Chat** owns chat UX, conversations, Projects, attachments, Saved Outputs and product modes. Generic Tool/Skill/Agent/Memory/Evidence semantics remain IP-CORE-owned.
- **B54 Padiem Claw** owns task/run/repository/workspace/GitHub product flow. `P01` is historical terminology for the shared Core lineage; current canonical identity is `IP-CORE`.
- **B66 Padiem Quote** owns quotation UX/state, Saved Quote Skill, source-derived template onboarding, document-fidelity certification and quote presentation. Its canonical product docs are under `docs/products/b66/`; historical CGI renderer issues are evidence, not competing policy authority.
- **B61 StoryMemory** owns reader/domain semantics including locator grammar, progress, knowledge ceiling and spoiler/no-future behavior. Generic retrieval/permission/evidence remains IP-CORE-owned.
- **B53 Padiem Sidecar** is the commercial product whose product charter, requirements, architecture, operations, security and commercialization documents live under `docs/products/padiem-sidecar/`.
- **IP-SIDECAR** is the reusable embedded runtime layer consumed by B53 and future approved hosts. B53 and IP-SIDECAR are distinct authorities.
- **B14 Korean AI Platform** owns Provider/model registry, inference credentials, executable route validation/selection and actual model execution.

## IP-SIDECAR current state

```text
SOURCE = packages/padiem-embedded-runtime/
SOURCE_PRESENT = YES
S2_MINIMAL_RUNTIME_CONTRACT = LANDED
ENGINE_CONNECTIVITY = NO
LIVE_PROVIDER_EXECUTION = NO
PRODUCTION_ACTIVE = NO
```

S2 source presence proves only the bounded embedded runtime contract, not live Engine or Provider connectivity.

## Padiem model authority

Current model selections, excluded providers/models and customer naming are **not duplicated in this repository index**. Follow the [single model entrypoint](models/README.md), then the [owner decision ledger](operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md) and [owner approval policy](operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md) for the relevant decision.

- **Exact registration and capabilities:** current [B14 provider/catalog source](../apps/korean-ai-platform/app/pilot/catalog.py), [provider registration modules](../apps/korean-ai-platform/app/pilot/platform.py) and associated tests.
- **Product-tier declaration and HOLD state:** current [Control Plane product routes](../packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py).
- **Product consumers:** [B62](../apps/padiem-chat/README.md), [B54](../apps/korean-ai-code-agent/README.md), [B66](products/b66/README.md) each document their own boundaries, not another model roster.
- **Live readiness:** exact deployment, credential readiness, and protected E2E evidence; source registration alone never proves a usable Production route.

A model addition or retirement updates its actual owner-approved authority and B14/Control Plane source as applicable. This index is deliberately stable; do not paste a new model inventory or a model status snapshot here.

## Documentation authority order

When documents disagree:

```text
1. latest OWNER decision for which models may be offered (#3554 + dated ledger); merged source/executable contract for which route actually works
2. canonical architecture + registries
3. current component/product README and product contract
4. accepted ADR
5. dated audit/evidence record
6. historical issue/PR discussion
```

Business numbering remains governed by `portfolio/BUSINESS_REGISTRY.md`.

## Historical evidence

Pre-unification evidence is retained in two forms:

```text
history/2026-09-01/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.audit.md
  -> immutable pointer to the exact registry at audit commit f9ff7f81602138daa674811b9650bb7ffc86cf97

history/2026-09-01/PADIEM_AI_CORE_README.snapshot.md
history/2026-09-02/PADIEM_CLAW_README.snapshot.md
  -> preserved historical document snapshots
```

Historical evidence may contain stale identifiers and runtime status. It does not override current authority.

## Readiness rule

```text
SOURCE_PRESENT
!= CONTRACT_AVAILABLE
!= BINDING_CONFIGURED
!= PROVIDER_READY
!= DEPLOYED
!= PRODUCTION_ACCEPTED
```

A class, route, README, UI control or passing unit test does not by itself prove a live Provider, connector, secret, database, service binding or Production deployment.
