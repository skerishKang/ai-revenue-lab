# Padiem Internal Platform

```text
DOC_STATUS = CANONICAL
OWNER = Padiem platform architecture
SCOPE = shared non-Business platform components and their relationships
LAST_VERIFIED = 2026-09-08
SUPERSEDES = ad-hoc internal-platform descriptions in issue threads
```

Padiem의 공용 AI 기술 계층은 Business 번호와 분리된 **Internal Platform**으로 관리합니다.

## Canonical IDs

```text
IP-CORE     = Padiem AI Core
IP-ENGINE   = Padiem AI Engine
IP-CONTROL  = Padiem Control Plane
IP-SIDECAR  = Padiem Embedded AI Runtime   [PROPOSED / activation separately gated]
```

B14 Korean AI Platform은 Internal Platform ID가 아니라 **Business 14**이며, Provider/model 실행 권위를 소유합니다.

## Default composition

```text
Product / Business adapter
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

`IP-CONTROL`은 identity, tenant, entitlement, usage, credits/subscription, audit 및 중립적 cross-product declaration을 담당하는 cross-cutting authority입니다.

Embedded AI 제품은 필요할 때 다음 구조를 사용합니다.

```text
Host
  -> Product/Customer Adapter
  -> B53 Padiem Sidecar product layer
  -> IP-SIDECAR
  -> IP-ENGINE
  -> IP-CORE
  -> B14
```

## Documents

- [`INTERNAL_PLATFORM_REGISTRY.md`](INTERNAL_PLATFORM_REGISTRY.md) — ID, source, ownership, lifecycle
- [`AI_ADOPTION_PLAYBOOK.md`](AI_ADOPTION_PLAYBOOK.md) — 제품이 AI 기능을 붙일 때의 기본 결정 절차
- [`core/README.md`](core/README.md) — IP-CORE component guide
- [`engine/README.md`](engine/README.md) — IP-ENGINE component guide
- [`control-plane/README.md`](control-plane/README.md) — IP-CONTROL component guide
- [`sidecar/README.md`](sidecar/README.md) — IP-SIDECAR proposed boundary
- [`../architecture/PADIEM_AI_VERTICAL_STACK.md`](../architecture/PADIEM_AI_VERTICAL_STACK.md) — 전체 수직 계층

## Rules

1. Internal Platform ID를 Business 번호 registry에 넣지 않습니다.
2. 제품/Business는 domain semantics와 UX를 소유하고, 공용 AI 의미론을 복제하지 않습니다.
3. Provider/model catalog, inference credentials, exact execution은 B14에 남깁니다.
4. cross-runtime 소비는 IP-ENGINE을 기본 경계로 사용합니다.
5. same-runtime/library direct Core reuse는 명시적으로 허용된 경우만 사용합니다.
6. source 존재는 Production activation을 의미하지 않습니다.
7. IP-SIDECAR는 formal registration/source/runtime activation이 별도 증거로 확인되기 전까지 proposed 상태로 취급합니다.
