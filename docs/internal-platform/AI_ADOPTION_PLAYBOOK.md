# Padiem AI Adoption Playbook

```text
DOC_STATUS = CANONICAL_PLAYBOOK
OWNER = Padiem platform architecture
SCOPE = how a product adopts shared AI capabilities without duplicating platform layers
LAST_VERIFIED = 2026-09-08
SUPERSEDES = ad-hoc product-specific ownership decisions where they conflict
```

## 1. Start with the product boundary

새 AI 기능을 만들기 전에 먼저 제품이 소유할 부분을 적습니다.

```text
PRODUCT_DOMAIN_STATE = ...
PRODUCT_UX = ...
PRODUCT_PERSISTENCE = ...
PRODUCT_ADAPTER = ...
```

그 다음 generic AI 의미론을 제품 내부에서 새로 만들지 않고 아래 분류를 적용합니다.

## 2. Classification

| Classification | Use when | Canonical owner |
|---|---|---|
| `REUSE_CORE` | 이미 존재하는 공용 AI semantics를 사용할 수 있음 | IP-CORE |
| `EXTEND_CORE` | 두 제품 이상에 재사용 가능한 generic semantic이 실제로 빠져 있음 | IP-CORE |
| `ENGINE_TRANSPORT` | Core semantic은 있으나 cross-runtime exposure가 없음 | IP-ENGINE |
| `B14_EXECUTION` | Provider/model/catalog/route/credential/upstream execution 문제 | B14 |
| `CONTROL_PLANE` | identity/tenant/entitlement/usage/audit 또는 neutral declaration 문제 | IP-CONTROL |
| `PRODUCT_ADAPTER` | domain state를 shared contract로 투영하거나 UI로 표시 | Product/Business |
| `IP_SIDECAR` | 여러 host 제품이 재사용할 embedded shell/host bridge 문제 | IP-SIDECAR after formal activation |
| `DO_NOT_SHARE` | 제품 고유 의미/UX로 남겨야 함 | Product/Business |

## 3. Default architecture

Cross-runtime 제품의 기본값:

```text
Product
 -> Product Adapter
 -> IP-ENGINE
 -> IP-CORE
 -> B14
 -> Provider/Model
```

Same-runtime/library 통합은 architecture가 허용하는 경우에만:

```text
Product
 -> Product Adapter
 -> IP-CORE
 -> B14
```

Embedded surface는 IP-SIDECAR가 실제 등록/구현된 경우:

```text
Host/Product
 -> Adapter
 -> IP-SIDECAR
 -> IP-ENGINE
 -> IP-CORE
 -> B14
```

## 4. Decision questions

다음 순서로 판단합니다.

1. 이 기능은 사용자/도메인 의미인가? → Product.
2. 여러 제품에 동일한 의미로 재사용 가능한 AI semantics인가? → 기존 Core 검색 후 REUSE/EXTEND.
3. Core에는 있는데 다른 runtime에서 호출해야 하는가? → Engine projection.
4. Provider/model/route/credential 문제인가? → B14.
5. identity/tenant/entitlement/usage/audit 또는 neutral cross-product declaration인가? → Control Plane.
6. 웹사이트 안의 공용 embedded shell/host bridge인가? → IP-SIDECAR 후보.
7. 위 어느 것도 아니면 제품에 남기고 성급하게 공유 계층으로 올리지 않습니다.

## 5. Required pre-implementation note

AI 관련 이슈/PR에는 최소한 다음을 기록합니다.

```text
CAPABILITY_OWNER = PRODUCT | IP-CORE | IP-ENGINE | IP-CONTROL | IP-SIDECAR | B14
CAPABILITY_CLASS = REUSE_CORE | EXTEND_CORE | ENGINE_TRANSPORT | B14_EXECUTION | CONTROL_PLANE | PRODUCT_ADAPTER | IP_SIDECAR | DO_NOT_SHARE
REUSE_AUDIT = <existing files/issues/contracts checked>
OVERLAP_WITH = <existing owner or NONE>
CONTRACT_IMPACT = NONE | BACKWARD_COMPATIBLE | BREAKING
PRODUCT_SPECIFIC_SEMANTICS_IN_CORE = 0
GENERIC_CORE_DUPLICATION_IN_PRODUCT = 0
PROVIDER_ROUTING_DUPLICATION = 0
```

## 6. Examples

### Padiem Chat

- composer/sidebar/history/Projects/Saved Outputs → `PRODUCT_ADAPTER` / `DO_NOT_SHARE`
- execution/grounding/evidence → `REUSE_CORE`
- orchestration cross-runtime bridge → `ENGINE_TRANSPORT`
- Plus/Pro/Max declaration → `CONTROL_PLANE`
- actual model executability → `B14_EXECUTION`

### Padiem Claw

- repository task/run/GitHub workflow → product
- reusable Agent/Tool/Skill/approval/recovery semantics → Core
- cross-runtime agent/orchestration projection → Engine
- model execution → B14

### StoryMemory / Bible

- Bible/classic-work locator grammar, progress, knowledge ceiling, annotations, spoiler UX → `DO_NOT_SHARE` / product domain
- generic retrieval permission/evidence/context gating → `REUSE_CORE`
- cross-runtime execution → Engine
- model invocation → B14

### Padiem Sidecar

- commercial onboarding/pricing/install journey → B53 product
- generic panel/shell/host event bridge → IP-SIDECAR candidate
- reasoning/Tool/Memory/Agent semantics → Core, not Sidecar
- cross-runtime execution → Engine
- Provider/model → B14

## 7. Anti-patterns

다음은 금지합니다.

```text
Product-specific model router
Product-owned raw Provider secrets
Engine-owned competing AI policy
Core-owned product locator/domain schema
B14 directly reading product memory/domain DB
Sidecar iframe shortcut that turns Chat into the architecture
Control Plane becoming a model execution gateway without explicit redesign
Source-present == Production-active claims
```

## 8. Promotion rule

두 제품에 비슷한 코드가 있다는 이유만으로 공용화하지 않습니다. Generic contract가 실제로 동일하고, 제품별 의미를 제거한 뒤에도 독립적으로 설명 가능한 경우에만 shared layer로 승격합니다.

승격 전 확인:

- second-consumer evidence
- compatibility contract
- failure/security semantics
- owner and lifecycle
- test/conformance path
- rollback/migration impact

## 9. Documentation rule

새 기능이 소유권 경계를 바꾸면 구현 PR과 함께 다음 중 관련 문서를 갱신합니다.

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`

단순 구현 상태 변화는 중앙 topology 문서를 자주 수정하지 않고 component README/manifest와 현재 source를 갱신합니다.
