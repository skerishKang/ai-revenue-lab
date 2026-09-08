# Padiem / AI Revenue Lab Documentation

`docs/`의 목적은 **현재 시스템의 권위(authority)를 한 곳에서 찾게 하는 것**입니다. 이 저장소에는 제품 문서, 운영 문서, 아키텍처 감사 기록, 이슈별 설계 스냅샷이 함께 누적되어 있으므로, 파일이 존재한다는 이유만으로 모두 같은 수준의 현재 권위를 갖는 것으로 해석하면 안 됩니다.

## 1. 가장 먼저 읽을 문서

Padiem AI 수직계열 구조를 이해할 때는 아래 순서로 읽습니다.

1. [`architecture/PADIEM_AI_VERTICAL_STACK.md`](architecture/PADIEM_AI_VERTICAL_STACK.md) — 제품부터 Provider/Model까지의 현재 계층과 소유권
2. [`internal-platform/README.md`](internal-platform/README.md) — IP-CORE / IP-ENGINE / IP-CONTROL 및 IP-SIDECAR 관계
3. [`internal-platform/AI_ADOPTION_PLAYBOOK.md`](internal-platform/AI_ADOPTION_PLAYBOOK.md) — 새 제품이 AI를 붙일 때 재사용/확장/제품 어댑터를 고르는 규칙
4. [`product/AI_PRODUCT_CONSUMER_MATRIX.md`](product/AI_PRODUCT_CONSUMER_MATRIX.md) — Chat, Claw, StoryMemory, Sidecar 등 AI 소비 제품의 위치
5. [`governance/DOCUMENTATION_AUTHORITY_MODEL.md`](governance/DOCUMENTATION_AUTHORITY_MODEL.md) — 어떤 문서를 현재 권위로 볼지 판단하는 규칙

현재 문서 정리 기준과 발견된 드리프트는 [`DOCUMENTATION_AUDIT_20260908.md`](DOCUMENTATION_AUDIT_20260908.md)에 기록합니다.

## 2. Padiem AI 계층의 핵심 규칙

```text
Product / Business domain + UX
        │
        ├─ optional IP-SIDECAR presentation/runtime layer
        │
        ▼
IP-ENGINE  = cross-runtime trusted service boundary
        │
        ▼
IP-CORE    = reusable AI semantics/contracts/runtime
        │
        ▼
B14        = provider/model catalog, routing, credentials, execution
        │
        ▼
Provider / Model

IP-CONTROL = identity / tenant / entitlement / usage / audit and neutral
             product declarations; cross-cutting authority, not a model router
```

동일 런타임에서 명시적으로 허용된 제품은 IP-CORE를 직접 라이브러리로 사용할 수 있습니다. 외부/교차 런타임 제품은 IP-ENGINE 경계를 기본으로 사용합니다. 제품은 Provider credential 또는 공용 모델 라우팅 권위를 다시 만들지 않습니다.

B14의 Router는 별도 제품/플랫폼 계층이 아니라 **B14 내부 실행 능력**입니다.

## 3. 문서 분류

### Canonical architecture / registry

현재 구조와 소유권을 정의합니다. 실행 상태처럼 자주 바뀌는 사실은 코드/manifest에서 검증하고, 문서에는 안정적인 경계와 참조점을 기록합니다.

- `architecture/PADIEM_AI_VERTICAL_STACK.md`
- `internal-platform/README.md`
- `internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- `product/AI_PRODUCT_CONSUMER_MATRIX.md`
- `portfolio/BUSINESS_REGISTRY.md` — Business 번호 권위

### Component / product documentation

각 소스 경로의 사용법·제품 동작·로컬 테스트·제품 특수 의미를 설명합니다.

- `packages/padiem-ai-core/README.md`
- `apps/korean-ai-platform/README.md`
- `apps/padiem-chat/README.md`
- `apps/korean-ai-code-agent/README.md`
- 제품별 README / PRODUCT_CONTRACT / runbook

컴포넌트 README는 중앙 플랫폼 소유권을 재정의하지 않고 중앙 문서로 링크해야 합니다.

### Operations / governance

- `operations/` — 개발, 배포, 증거, 자격증명, 복구 등 운용 규칙
- `governance/` — AI 운영 모델과 문서 권위 규칙
- `decisions/` — ADR. 결정 이유와 당시 선택을 보존

### Product / portfolio / commercial

- `product/` — 제품 계약 및 제품군 문서
- `portfolio/` — Business 번호·계보·외부 프로젝트·사업 후보
- `commercial/` — 제안서·고객 문서·상업 패키지

### Historical / evidence snapshots

이슈 번호, 특정 SHA, 날짜, 특정 배포/감사 시점을 제목이나 본문에 고정한 문서는 기본적으로 **증거 스냅샷**입니다. 예:

- `B54_..._2089.md`
- `..._20260831.md`
- 과거 Phase 0/1/2/3 문서

이 문서들은 삭제하지 않되 현재 아키텍처를 덮어쓰지 않습니다.

## 4. 권위 우선순위

현재 사실이 충돌할 때 다음 순서를 기본으로 사용합니다.

```text
1. current merged source / executable contract / manifest
2. canonical architecture + registry documents
3. current component/product README and product contract
4. accepted ADR
5. dated or issue-specific audit/evidence document
6. historical issue/PR discussion
```

단, Business 번호는 `portfolio/BUSINESS_REGISTRY.md`처럼 별도 소유권이 명시된 registry가 최우선입니다. Production 활성화 여부는 소스 존재만으로 추론하지 않고 실제 배포/바인딩/환경 증거를 확인합니다.

## 5. 문서 작성 규칙

새 canonical 문서는 가능하면 다음 메타데이터를 머리에 둡니다.

```text
DOC_STATUS = CANONICAL | CURRENT_PRODUCT | RUNBOOK | ADR | EVIDENCE_SNAPSHOT | HISTORICAL
OWNER = <platform/product/domain>
SCOPE = <what this document owns>
LAST_VERIFIED = YYYY-MM-DD
SUPERSEDES = <path or NONE>
```

그리고 다음을 지킵니다.

- Provider/model 목록과 Production 상태 같은 휘발성 사실은 한 곳에서만 소유합니다.
- 제품 README는 중앙 플랫폼 경계를 복사하지 말고 링크합니다.
- 이슈 번호가 붙은 설계 문서는 canonical로 명시하지 않는 한 snapshot으로 취급합니다.
- Core, Engine, Control Plane, B14, Chat, Claw, Sidecar, StoryMemory 사이의 소유권을 제품별로 다시 정의하지 않습니다.
- 외부/비공개 저장소 제품은 존재하지 않는 내부 경로를 만들어내지 않고 registry/matrix에 외부 권위로 기록합니다.
- `CODE_ON_MAIN`과 `PRODUCTION_ACTIVE`를 같은 의미로 사용하지 않습니다.

## 6. 저장소 문서의 목표 상태

문서 정리 완료 후에는 다음 질문을 한 파일 탐색만으로 답할 수 있어야 합니다.

- 이 기능의 제품 소유자는 누구인가?
- 공용 AI 의미론은 Core인가, Engine인가?
- Provider/model/credential 권위는 어디인가?
- Control Plane은 무엇을 소유하는가?
- Sidecar는 제품인가, 공용 런타임인가?
- StoryMemory의 Bible/고전 locator 같은 도메인 의미는 어디에 남는가?
- Padiem Chat/Claw가 공용 계층을 어디까지 소비하는가?
- 현재 문서와 과거 감사 문서가 충돌하면 무엇을 믿어야 하는가?

이 entrypoint가 그 탐색의 시작점입니다.
