<!-- B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->
> **B14 역할 최신 원칙(2026-10-10):** [원제작사 모델·서빙 제공업체·변형 모델의 공식 사양 및 B14 실행 권한](B14_MODEL_PROVIDER_EXECUTION_AUTHORITY_2026-10-10.md)을 우선 확인합니다. **B14는 정확히 사용자가 선택한 모델을 해당 업체의 공식 API로 실행**하며, temperature/토큰/리즈닝을 임의 지정하거나 옵션을 조용히 바꾸지 않습니다. 원본 모델의 공식 사양과 실제 API 제공업체의 계약은 별도 증빙합니다. 과거 코드·평가 수치는 이 원칙의 구현 증명이 아닙니다.
<!-- /B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->

# Padiem AI Vertical Stack

```text
DOC_STATUS = CANONICAL
OWNER = Padiem platform architecture
SCOPE = shared AI platform layers, product adapters, routing/provider ownership
LAST_VERIFIED = 2026-10-07
SUPERSEDES = fragmented layer descriptions only; historical evidence remains preserved
```

## 1. Purpose

Padiem은 하나의 거대한 AI 애플리케이션이 아니라, **공용 AI 플랫폼 계층 + 독립 제품/도메인 어댑터** 구조로 운영합니다. 이 문서는 AI Engine, AI Core, Control Plane, Chat, Claw, Sidecar, StoryMemory와 B14 Router/Provider 관계를 한 장의 권위로 통일합니다.

핵심 원칙은 다음과 같습니다.

```text
PRODUCTS OWN DOMAIN + UX.
IP-SIDECAR OWNS REUSABLE EMBEDDED SHELL/CONTEXT/EVENT PRIMITIVES.
IP-CORE OWNS REUSABLE AI SEMANTICS.
IP-ENGINE OWNS CROSS-RUNTIME SERVICE PROJECTION.
B14 OWNS MODEL/PROVIDER EXECUTION.
IP-CONTROL OWNS CROSS-CUTTING IDENTITY/ENTITLEMENT/USAGE/AUDIT TRUTH.
```

## 2. Canonical topology

### 2.1 Standalone / product AI path

```text
Padiem product / Business
(Chat, Claw, B66 Padiem Quote, StoryMemory, Living Learning, future products)
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
IP-SIDECAR · Padiem Embedded AI Runtime
S2 minimal runtime contract source-present / non-production
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
- **IP-SIDECAR**: 여러 제품이 재사용할 수 있는 embedded shell/context/event/bootstrap runtime primitives

현재 `packages/padiem-embedded-runtime/`에 S2 minimal runtime contract가 존재합니다. 다만 이것은 **source-present / non-production** 상태이며 real Engine transport, live Provider execution, OAuth, Production deployment를 제공하지 않습니다. Source presence를 Production activation으로 해석해서는 안 됩니다.

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
| Embedded shell | IP-SIDECAR | reusable shell lifecycle, browser-safe bootstrap, host-context envelope, public-safe event projection, host adapter integration contract | product domain meaning, Core semantics, Engine machine auth/transport, B14 routing/credentials |
| Service boundary | IP-ENGINE | trusted caller/service boundary, wire projection, cross-runtime execution/orchestration exposure | product UX, generic semantic authority, Provider/model routing |
| Shared semantics | IP-CORE | execution, evidence, grounding, permission, retrieval/memory semantics, Tool/Skill/Agent/orchestration contracts | product domain schema, product UI, Provider catalog/credentials |
| Execution plane | B14 | Provider/model registry, user-chosen exact route verification, official-provider API parameter fidelity, inference credentials, upstream execution; retry/fallback only under separately Owner-approved route policy | product memory/domain state, product UX, Control Plane identity truth |
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

### B66 · Padiem Quote

B66 is a standalone quotation product. It owns quotation-specific UX/state, Saved Quote Skill lifecycle, source-derived quotation onboarding, document-fidelity certification, quotation history/presentation and optional editable outputs.

Canonical source-derived lifecycle:

```text
source quotation
-> analysis
-> Canonical Quote Template candidate
-> reproduction against reference facts
-> certification
-> certified repeat execution
```

B66 reuses QuoteCore/shared calculation semantics and approved Padiem identity/storage/Engine/Core/B14 capabilities where applicable. It does not become a second Provider/model registry or a second quotation-calculation authority.

The current CGI reference template is certified within its declared scope. That does not yet prove a generic analyzer/compiler; #3595 remains the generalization/certification authority until a materially different second template proves the compiler path.

Canonical B66 documentation: `docs/products/b66/`.

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

B53 is the commercial embedded-AI product. It does not own generic Core/Engine/B14 semantics. Reusable embedded shell/context/event/bootstrap primitives belong to IP-SIDECAR.

Current shared-runtime state:

```text
SOURCE = packages/padiem-embedded-runtime/
S2_MINIMAL_RUNTIME_CONTRACT = LANDED
ENGINE_CONNECTIVITY = NO
LIVE_PROVIDER_EXECUTION = NO
PRODUCTION_ACTIVE = NO
```

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
- IP-SIDECAR bootstrap/context must remain browser-safe and must not carry raw secrets
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

Documentation must therefore avoid phrases such as "live" or "available" solely because a class, endpoint, package or UI control exists on `main`.

For IP-SIDECAR specifically, S2 currently proves source/contract presence only; it does not prove Engine transport or Production activation.

## 8A. 전체 PADIEM AI 제품 통합 운영 계약 (2026-10-14 Owner 지시)

**이 섹션은 기존 수직 스택의 제품 간 연결 지침이지 새 공통플랫폼·새 인증기관·즉시 출시 선언이 아닙니다.** 개별 소스 이관은 [#2409](https://github.com/skerishKang/ai-revenue-lab/issues/2409)의 단계별 소유권 검토를 유지하며 한 번에 옮기지 않습니다. [#1743](https://github.com/skerishKang/ai-revenue-lab/issues/1743)의 공통 Engine 기능도 실제 호출/배포 검증에 따라 점진적으로 소비합니다.

**단일 계정·공통 내부 환경, 제품별 대외 경험:** Chat·Claw·B66 등 PADIEM의 모든 제품은 기존 PADIEM 회원 계정과 공통 Identity/Control Plane·Core·Engine·B14·Broker·Windows Connector 기술 기반을 재사용합니다. 고객에게 B66만 별도 회원가입·재로그인·커넥터 재설치를 요구하지 않습니다. 외부의 브랜드·도메인·화면·메뉴·업무 기능은 제품별로 다르게 제공할 수 있으며, AI 모델 선택·기능 권한·사용량·요금도 제품별로 달라질 수 있습니다(실제 모델/이용조건은 별도 확인·결정 필요). **공통 로그인은 모든 제품의 자료나 다른 고객사의 PC·파일 접근을 자동 허용하지 않습니다.**

### 통합 범위와 단일 소유권

| 계층 / 고객 경험 | 통합에 재사용할 기존 권위 | 분리해야 하는 것 | 실제 연결 수용 |
| --- | --- | --- | --- |
| PADIEM Chat (B62) | Core 지침·검색 의미론, Engine의 승인된 실행 경로, B14 사용자 지정 모델, Control Plane 계정 | 대화/프로젝트/파일 및 기록을 다른 제품에 자동 공개하지 않음 | 기존 Chat 운영 배포·별도 제품 실사용 증거 |
| PADIEM Claw (B54/P01) | 동일 플랫폼 모델 권한과 Engine/P01 실행·도구·지속·복구 경계, 기존 Chat/Claw UI | 모델 응답만으로 로컬 PC·WRITE 권한 발급 금지 | [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936) |
| B66 AI 견적 | 공통 PADIEM 회원 계정·인증, Core/Engine/B14의 허용된 기술, 견적 계산·형식 보존 계약, 동일한 Connector/Broker | **대외 견적 제품의 브랜드·화면·메뉴·업무 기능은 별도**. 고객사·워크스페이스·대화·원본 양식·견적·라이브러리 접근 권한과 제품별 모델·사용량 정책은 서버에서 검증. 이메일 문자열만으로 교차 고객사 자료 권한을 부여하지 않음 | [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316) |
| IP-ENGINE / IP-CORE / B14 | 재사용 의미론 / 신뢰 경계·서비스 투영 / 모델·제공자 실행 각각 단일 소유 | 제2 Provider 라우터, 중복 Engine, 브라우저 API 키, 별도 제품별 공통 프롬프트 복제 금지 | [#1743](https://github.com/skerishKang/ai-revenue-lab/issues/1743), [#4465](https://github.com/skerishKang/ai-revenue-lab/issues/4465) |
| PADIEM Control Plane + Windows Connector | 하나의 PADIEM 계정·검증된 identity/tenant/entitlement, 기존 Broker 장치 사실, 하나의 설치 프로그램과 등록된 기기 연결 | 동일 PC의 제품별 작업·파일·고객사 접근 권한은 서버에서 따로 검사. 제품마다 추가 설치·재로그인·독립 기기 등록을 기본 절차로 요구하지 않으며, 권한 없는 실행은 허용하지 않음 | [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139), [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) |
| 고객 홈·운영 관리자 | 하나의 PADIEM 계정으로 이용 가능한 제품의 진입점과 기존 운영용 Control Plane | 제품별 대외 화면·메뉴는 구분하고 계정별 제공 제품·모델·기능·사용량 권한을 확인. 고객 홈 진입만으로 다른 고객사 자료나 미허가 제품 기능을 열지 않음; Portfolio Console을 고객 홈으로 전환 금지 | [#4428](https://github.com/skerishKang/ai-revenue-lab/issues/4428) |
| 그 밖의 PADIEM AI 제품 (B61 StoryMemory, B53 Sidecar, 음성·향후 서비스) | 필요한 Core/Engine/B14·Control Plane 계약을 기존 제품 어댑터로 소비 | 제품별 저작권·도메인·파일/개인정보 및 사용권한. 소스 존재만으로 출시/모델 연결 주장 금지 | 각 제품의 기존 개별 수용 이슈 |

**통합의 의미는 하나의 PADIEM 회원 계정과 공통 내부 환경을 재사용하면서 외부 제품 경험을 구별하는 것입니다.** B66은 견적 전용 화면·업무 흐름을 유지하지만 회원가입·로그인·PC 설치 기반은 별도로 만들지 않습니다. 같은 계정이어도 고객사·워크스페이스·제품별 대화·원본 문서·견적·기기·작업 접근 권한은 기존 서버 권위에서 검증하고, 자료를 한 DB나 고객 화면에 무조건 합치지 않습니다. 하나의 커넥터 설치/기기 연결은 재사용하되 해당 제품의 권한 없는 파일 READ/WRITE·도구 실행은 허용하지 않습니다.

### 기본 자동 실행과 추후 선택적 승인 기능

- **기본 UX: 자동 진행.** 로그인된 사용자가 이미 허가된 작업을 요청했다면 매 단계마다 새 승인 팝업을 요구하지 않고, 현재 검증된 제품 권한·업무 범위·기기 권한 안에서 실행합니다. 기존 인증·권한·모델 선택·고객정보 보호를 건너뛰는 무조건적 보안 허용 정책은 아닙니다.
- **기존 강제 안전 절차는 유지.** 최초 PC 등록/연결 동의, 기존 공통 로그인 세션과 각 제품의 검증된 인증 연결, 도구/파일 WRITE의 유효한 실행 권한, QuoteCore 계산·실제 저장/덮어쓰기/발급에 필요한 사용자 확인, Engine이 발급하는 WAITING_APPROVAL의 검증된 복구·거부 경계는 자동 허가로 치환하지 않습니다. AI 모델의 단순한 응답은 P01 승인 증거가 아닙니다.
- **중급 사용자 이상 대상 ‘실행 전 세부 승인/확인 방식 선택’은 미래 UX 후보로만 표시.** 이 지시는 기술 사용 숙련도에 관한 것으로, 현재 Plus/Pro/Max 구독·회원 등급을 새로 제한하거나 자동 변환하는 정책이 아닙니다. **이번 작업에서 설정 화면, 계정별 승인 모드 저장, 새 승인 API, 새 팝업/중단 게이트를 구현하지 않습니다.** 별도 범위와 실제 필요성이 결정될 때만 구현합니다.
- **기존 Engine 내부 승인 처리 코드는 유지**하되 사용자가 모든 일반 작업을 승인하도록 하는 기본 흐름으로 노출하지 않습니다. 승인 테스트만을 위해 운영 모델 호출이나 고객 데이터를 변경하지 않습니다.
- Chat·Claw·B66의 모델 선택·제공 기능·사용량·요금은 제품별로 다르게 적용할 수 있지만, 공통 B14 모델 등록/라우팅과 서버의 제품별 entitlement·사용량 권위를 재사용합니다. 실제 적용 전 승인된 모델 ID·기존 이용조건을 확인하고 임의로 모델/요금/권한을 신설하지 않습니다. 공통 사전지침([#4465](https://github.com/skerishKang/ai-revenue-lab/issues/4465))은 Core/Engine의 한 군데에서 관리하고, 실제 최신 웹검색 실행과 단순 날짜 주입을 동일시하지 않습니다. 임의 유료 모델 변경, 무허가 Provider fallback, 비공개 견적서의 검색 업로드는 금지입니다.

### 연결 순서 및 상태 판정

1. 기존 모델/identity/검색/Connector **공통 계약을 재사용**하고 현재 제품별 호출 지점을 정확히 연결합니다. B66 또는 Claw가 이미 쓰는 흐름을 한 번에 새 Engine으로 이전하지 않습니다.
2. 기존 소유 PR을 우선 완료·병합하여 **B66 대화·견적 고객 UI [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316), 공통 사전지침 [#4465](https://github.com/skerishKang/ai-revenue-lab/issues/4465), 단일 Windows Connector [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139), PADIEM 고객 홈 [#4428](https://github.com/skerishKang/ai-revenue-lab/issues/4428)**을 각 제품의 기존 인증·권한 경계 안에 연결합니다. 동일 파일을 타 팀과 동시에 수정하거나 중복 이슈·워크플로를 만들지 않습니다.
3. 각 제품에서 단 하나의 대표 통합 여정으로 **source / merged / deployed / owner-authenticated E2E**를 구분하여 확인합니다. 이미 증명한 검증을 반복하지 않으며 모델 호출·Production 변경은 실제 승인·기존 보호 절차를 따릅니다.
4. PADIEM 단일 회원 계정을 전 제품의 로그인 출발점으로 사용하되, 외부 브랜드·도메인·화면·기능 및 제품별 모델·사용량·요금·데이터 접근 권한은 별도 계약에 따라 적용합니다. 고객 재가입·별도 로그인·커넥터 중복 설치를 전제로 구현하지 않으며, 미구현 항목은 ‘통합 완료’로 표시하지 않습니다.

**진척 판정 (문서 반영 시점):** 공통 수직 스택은 기존에 정의되어 있지만 PADIEM_ALL_PRODUCT_LIVE_INTEGRATION=NOT_PROVEN; 개별 제품 연결과 운영 검증을 위의 기존 이슈에 누적합니다. DEFAULT_WORKFLOW=AUTOMATIC_WITHIN_EXISTING_GRANTS; ADVANCED_APPROVAL_UX=DEFERRED_NOT_IMPLEMENTED; PADIEM_ACCOUNT_ONE=OWNER_CONFIRMED_IMPLEMENTATION_NOT_PROVEN; PRODUCT_MODEL_USAGE_SCOPE=PRODUCT_SPECIFIC; NEW_SHARED_PLATFORM=NO.

---

## 9. Current canonical references

- `docs/README.md`
- `docs/internal-platform/README.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`
- `docs/internal-platform/sidecar/README.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`
- `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`
- `docs/architecture/PADIEM_AI_RETRIEVAL_CONSUMER_CONFORMANCE_v1.md`
- `packages/padiem-ai-core/README.md`
- `packages/padiem-embedded-runtime/README.md`
- `apps/korean-ai-platform/README.md`
- `apps/padiem-chat/README.md`
- `apps/korean-ai-code-agent/README.md`
- `docs/products/b66/README.md`

When those documents disagree on volatile status, current merged source and executable contract win; when they disagree on stable ownership, this architecture + the relevant canonical registry should be reconciled before new feature work proceeds.
