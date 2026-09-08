# Documentation Authority Model

```text
DOC_STATUS = CANONICAL_GOVERNANCE
OWNER = repository documentation governance
SCOPE = authority, freshness, supersession and snapshot rules for repository documentation
LAST_VERIFIED = 2026-09-08
SUPERSEDES = implicit document precedence
```

## 1. Problem

이 저장소는 제품 계약, 현재 README, ADR, 운영 runbook, 이슈별 설계 문서, 배포 증거, 과거 Phase 문서가 같은 `docs/` 트리 안에 누적되어 있습니다. 따라서 **최신 파일처럼 보이는 문서**와 **현재 실행 권위**가 항상 같은 것은 아닙니다.

문서 통일의 목적은 모든 파일을 하나의 거대한 문서로 합치는 것이 아니라, 각 문서의 역할과 우선순위를 명확히 하는 것입니다.

## 2. Document statuses

새 문서 또는 주요 개정 문서는 가능하면 다음 중 하나를 명시합니다.

| Status | Meaning |
|---|---|
| `CANONICAL` | 안정적인 현재 아키텍처/규칙의 권위 |
| `CANONICAL_REGISTRY` | ID/번호/소유권 mapping의 단일 권위 |
| `CANONICAL_COMPONENT_GUIDE` | component 경계/사용법에 대한 현재 guide |
| `CURRENT_PRODUCT` | 제품의 현재 제품 계약/README |
| `RUNBOOK` | 현재 운영 절차 |
| `ADR` | 채택된 결정과 이유; 역사적 결정은 보존 |
| `EVIDENCE_SNAPSHOT` | 특정 날짜/SHA/issue/deploy 상태에 대한 증거 |
| `HISTORICAL` | 현재 권위를 의도하지 않는 과거 단계 문서 |
| `PROPOSED_*` | 아직 formal activation/acceptance가 끝나지 않은 설계 |

## 3. Default precedence

동일한 사실이 충돌할 때 일반 원칙:

```text
1. current merged source / executable contract / runtime manifest
2. canonical registry / canonical architecture
3. current component or product README / product contract
4. accepted ADR
5. current runbook
6. dated or issue-specific evidence snapshot
7. historical issue / PR / phase document
```

예외적으로 각 도메인의 명시적 registry가 최우선인 항목이 있습니다.

- Business 번호 → `docs/portfolio/BUSINESS_REGISTRY.md`
- Internal Platform identity/source → `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- AI platform topology → `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- Provider/model executability → current B14 source/catalog
- Padiem tier declaration → current `product_tier_routes.py`
- Engine capability availability → current Engine manifest/composition
- Production deployment state → exact deployment/readback evidence

## 4. Stable vs volatile facts

### Stable facts suitable for canonical docs

- which layer owns a class of capability
- product vs platform identity
- source authority path
- cross-layer dependency direction
- security/non-ownership invariants
- registry identifiers

### Volatile facts that should stay close to source/evidence

- exact current main SHA
- open PR/Issue counts
- current CI run state
- active Production deployment SHA
- current endpoint/binding readiness
- provider free-tier availability
- exact model catalog membership
- transient credential readiness

Canonical docs may link to these facts but should avoid duplicating them in many places.

## 5. Snapshot recognition

다음 특징이 있으면 기본적으로 snapshot으로 취급합니다.

- 파일명에 issue 번호가 포함됨: `_2089`, `_2058`, `_1908`
- 날짜가 포함됨: `_20260831`
- `audit base`, `head SHA`, `deployment id`가 본문에 고정됨
- 특정 PR/incident/phase의 acceptance evidence를 기록함

Snapshot을 삭제하거나 최신 사실로 억지 수정하지 않습니다. 대신 canonical 문서에서 현재 권위를 안내하고, 필요한 경우 snapshot 상단에 다음과 같은 배너를 추가합니다.

```text
DOC_STATUS = EVIDENCE_SNAPSHOT
CURRENT_AUTHORITY = <canonical doc/source>
```

## 6. Component README rule

Component README는 다음만 소유합니다.

- component purpose/boundary
- local run/test instructions
- module/source map
- component-specific security and failure behavior
- accepted integration surface

다음은 중앙 canonical 문서를 링크하고 복제하지 않습니다.

- 전체 Padiem AI vertical architecture
- Business numbering
- shared layer identity
- 다른 제품의 detailed state
- volatile Provider/model availability

## 7. Product README rule

Product README는 제품 UX/domain/state와 shared layer **consumer relationship**을 설명합니다.

Product README가 하면 안 되는 것:

- Core generic semantics 재정의
- Engine authority 재정의
- Control Plane identity/entitlement 재정의
- B14 Provider/router authority 재정의
- 오래된 모델 route를 현재 실행 사실처럼 고정

## 8. Source readiness and Production claims

모든 문서에 공통 적용:

```text
CODE_ON_MAIN
!= RUNTIME_BOUND
!= PROVIDER_READY
!= DEPLOYED
!= PRODUCTION_ACCEPTED
```

UI control, route module, manifest entry 또는 test가 존재해도 실제 Production 활성화가 별도로 증명되지 않으면 `Production active`라고 쓰지 않습니다.

## 9. Change policy

문서 변경 유형별 요구:

### Architecture ownership change

반드시 함께 검토:

- `PADIEM_AI_VERTICAL_STACK.md`
- Internal Platform registry
- AI Product Consumer Matrix
- affected component/product README

### Implementation-only change

가능하면 component README와 executable contract/test만 갱신합니다. 중앙 topology는 소유권이 바뀌지 않으면 그대로 둡니다.

### Historical evidence correction

원본 증거 의미를 보존합니다. 사실 오류는 correction note로 남기고 snapshot 전체를 현재 문서처럼 다시 쓰지 않습니다.

## 10. Naming rules

- `Padiem AI Core` = `IP-CORE`
- `Padiem AI Engine` = `IP-ENGINE`
- `Padiem Control Plane` = `IP-CONTROL`
- `Padiem Embedded AI Runtime` = `IP-SIDECAR` proposed identity
- `Padiem Sidecar` = B53 commercial product
- `Padiem Claw` = B54 working product identity; canonical source `apps/korean-ai-code-agent/**`
- `Padiem Chat` = B62
- `Korean AI Platform` = B14, general AI Router Platform
- Router = B14 internal execution capability, not a separate Business/platform identity

## 11. Review checklist

문서 PR 리뷰 시 확인합니다.

```text
AUTHORITY_IDENTIFIED = YES
DOC_STATUS_CLEAR = YES
DUPLICATE_VOLATILE_TRUTH = NO
PRODUCT_DOMAIN_IN_SHARED_PLATFORM_DOC = BOUNDED
PROVIDER_ROUTING_OWNER = B14
BUSINESS_AND_INTERNAL_PLATFORM_IDS_NOT_MIXED = YES
SOURCE_PRESENT_EQ_PRODUCTION_ACTIVE = NO
HISTORICAL_EVIDENCE_PRESERVED = YES
```
