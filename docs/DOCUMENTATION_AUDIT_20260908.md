# Documentation Audit — 2026-09-08

```text
DOC_STATUS = EVIDENCE_SNAPSHOT
OWNER = repository documentation governance
AUDIT_SCOPE = Padiem AI vertical stack + AI-consuming product documentation
AUDIT_BASE = 62fa7addaf663fc6b51420f13954035eee76d50b
MUTATION_SCOPE = documentation only
PRODUCTION_MUTATION = NO
```

## 1. Audit objective

AI Engine, Core, Control Plane, B14 Router/Provider, Padiem Chat, Padiem Claw, Sidecar/embedded runtime, StoryMemory/Bible 및 기타 AI 소비 제품의 문서가 서로 다른 시점과 이슈에서 누적되어 있어 다음 문제가 발생했습니다.

- stable architecture와 dated audit snapshot이 같은 위치에서 동일 권위처럼 보임
- component README가 현재 source보다 뒤처진 부분이 있음
- Internal Platform과 Business 번호 체계가 중앙 docs entrypoint에서 분리되어 있지 않음
- B53 Sidecar와 IP-SIDECAR의 구분이 issue에만 존재함
- StoryMemory/Bible의 product-domain boundary가 중앙 consumer 문서에서 찾기 어려움
- B14 Router를 전체 수직계열 안에서 한 번에 이해할 중앙 구조 문서가 부족함

## 2. Inventory findings

### Repository-level documentation

Existing root authority included:

- `README.md`
- `AGENTS.md`
- `apps/README.md`
- `docs/architecture/**`
- `docs/product/**`
- `docs/portfolio/**`
- `docs/operations/**`
- `docs/governance/AI_OPERATING_MODEL.md`

Before this audit, `docs/README.md` and `docs/internal-platform/**` did not exist on the audited base.

### Shared platform source authorities

```text
IP-CORE    = packages/padiem-ai-core/**
IP-ENGINE  = apps/padiem-ai-engine/**
IP-CONTROL = packages/padiem-control-plane/**
B14        = apps/korean-ai-platform/**
```

Findings:

- Core has a detailed top-level README.
- B14 has a current top-level README and current Padiem route policy.
- Engine had no top-level README at `apps/padiem-ai-engine/README.md`.
- Control Plane had no top-level README at `packages/padiem-control-plane/README.md`.

## 3. Confirmed architecture truth

The audited source and accepted architecture converge on:

```text
Product/domain adapter
 -> IP-ENGINE for cross-runtime access
 -> IP-CORE shared AI semantics
 -> B14 Provider/model execution
 -> Provider/Model
```

Control Plane is cross-cutting authority for identity/tenant/entitlement/usage/audit and neutral cross-product declarations.

Same-runtime direct Core reuse is allowed only when explicitly accepted by architecture.

## 4. Confirmed route/document drift

### Padiem Chat README drift

`apps/padiem-chat/README.md` on the audit base still states that LOW/MEDIUM/HIGH profiles are unassigned and Provider/model selection is deferred.

Current merged source contradicts that statement:

```text
apps/padiem-chat/app/model_policy.py
 -> consumes padiem_control_plane.product_tier_routes
 -> Plus = Laguna
 -> Pro = Nemotron
 -> Max = HOLD
 -> default general chat = Pro
```

Current declaration authority:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
```

Current policy encoded there:

```text
AUTO_PROVIDER_SELECTION = NO
AUTO_MODEL_SELECTION = NO
USER_VISIBLE_AUTO_LABEL = NO
SILENT_FALLBACK = NO
```

Disposition: **README_RECONCILIATION_REQUIRED**.

### Capability ownership registry snapshot drift

`docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md` is highly valuable as a detailed ownership inventory but includes an audit base from 2026-09-01 and runtime/product route status rows that can age.

Disposition:

```text
KEEP = YES
ROLE = DETAILED_OWNERSHIP_REGISTRY + AUDIT_SNAPSHOT
ADD_CURRENT_AUTHORITY_POINTER = YES
DO_NOT_DELETE_HISTORICAL_EVIDENCE = YES
```

### Root and apps README volatility

Root `README.md` and `apps/README.md` contain portfolio/workspace status details, including old PR/state references. Those documents should remain useful for portfolio/workspace discovery but should not be treated as live operational dashboards.

Disposition: add a current documentation/platform entrypoint and reduce future volatile status duplication.

## 5. Sidecar clarification

Accepted issue architecture distinguishes:

```text
B53 Padiem Sidecar
= commercial product / customer journey / packaging

IP-SIDECAR · Padiem Embedded AI Runtime
= reusable embedded technical runtime candidate
```

Target topology:

```text
Host
 -> Product/Customer Adapter
 -> B53 when applicable
 -> IP-SIDECAR
 -> IP-ENGINE
 -> IP-CORE
 -> B14
```

IP-SIDECAR source/runtime/Production activation is not inferred from issue design alone.

## 6. StoryMemory / Bible clarification

B61 StoryMemory remains a product/domain owner for:

- Reader UX
- Bible/classic-work locator grammar/order
- reading progress and knowledge ceiling
- annotations/bookmarks/notes
- spoiler/no-future specialization
- StoryMemory-specific retrieval/domain adapter

Shared layers own generic behavior only:

- Core: retrieval permission, bounded context, evidence, shared execution semantics
- Engine: cross-runtime projection
- B14: Provider/model execution
- Control Plane: shared identity/entitlement/audit authority where integrated

`docs/architecture/PADIEM_AI_RETRIEVAL_CONSUMER_CONFORMANCE_v1.md` already records B61 as an accepted reference consumer and explicitly keeps Bible/classic-work domain meaning outside Core.

## 7. Documents introduced by this audit branch

This branch establishes the following central structure:

```text
docs/README.md
docs/architecture/PADIEM_AI_VERTICAL_STACK.md
docs/internal-platform/README.md
docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md
docs/internal-platform/AI_ADOPTION_PLAYBOOK.md
docs/internal-platform/core/README.md
docs/internal-platform/engine/README.md
docs/internal-platform/control-plane/README.md
docs/internal-platform/sidecar/README.md
docs/product/AI_PRODUCT_CONSUMER_MATRIX.md
docs/governance/DOCUMENTATION_AUTHORITY_MODEL.md
```

The intended result is not to delete existing evidence, but to make the current authority discoverable before an engineer reads historical snapshots.

## 8. Remaining reconciliation list at audit time

```text
[REQUIRED] update apps/padiem-chat/README.md stale unassigned-tier statement
[REQUIRED] add Engine top-level README
[REQUIRED] add Control Plane top-level README
[REQUIRED] mark detailed capability registry as snapshot-aware and link current vertical stack
[RECOMMENDED] add root README pointer to docs/README.md + vertical stack
[RECOMMENDED] add apps/README.md warning that workspace status is not live operational authority
[RECOMMENDED] future pass: classify dated/issue-numbered docs with snapshot metadata without deleting them
[RECOMMENDED] future pass: Sidecar B53 full product docs under its accepted product-doc path when #1723 is executed
```

## 9. Non-actions

```text
RUNTIME_SOURCE_CHANGE = 0
PROVIDER_ROUTE_CHANGE = 0
CREDENTIAL_CHANGE = 0
DATABASE_CHANGE = 0
WORKFLOW_CHANGE = 0
DEPLOYMENT = NO
PRODUCTION_MUTATION = 0
HISTORICAL_DOC_DELETION = 0
```

## 10. Exit criterion before issue reprioritization

문서 정리 후 이슈를 다시 볼 때 모든 open AI issue는 먼저 다음 질문에 답해야 합니다.

```text
OWNER_LAYER = ?
REUSE_EXISTING_SHARED_CAPABILITY = ?
PRODUCT_ADAPTER_ONLY = ?
ENGINE_PROJECTION_NEEDED = ?
B14_EXECUTION_CHANGE = ?
CONTROL_PLANE_CHANGE = ?
DOC_AUTHORITY_TO_UPDATE = ?
```

이 기준으로 이슈를 재분류해야 Core/Engine/Chat/Claw/Sidecar/StoryMemory가 같은 기능을 병렬로 다시 만드는 일을 줄일 수 있습니다.
