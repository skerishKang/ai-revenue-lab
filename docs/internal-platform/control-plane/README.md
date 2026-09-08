# IP-CONTROL · Padiem Control Plane

```text
DOC_STATUS = CANONICAL_COMPONENT_GUIDE
PLATFORM_ID = IP-CONTROL
SOURCE = packages/padiem-control-plane/**
LAST_VERIFIED = 2026-09-08
```

Padiem Control Plane은 여러 제품/runtime에 걸친 **중립적 권위와 운영 상태**를 소유하는 shared control layer입니다. 모델 실행/router 자체가 아닙니다.

## Owns / target authority

accepted contracts에 따라 다음 범주의 canonical truth를 둡니다.

- canonical subject / identity bridge
- tenant/workspace authority
- entitlement
- usage / credits / subscription
- audit
- connector/OAuth authority components assigned to Control Plane
- 둘 이상의 제품이 공유해야 하는 neutral declarations

현재 중요한 예:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
```

이 파일은 Padiem Plus/Pro/Max의 제품 route를 **선언**합니다. 실제 Provider/model catalog 검증과 실행은 B14가 소유합니다.

## Does not own

- Provider/model inference execution
- B14 provider credentials as product-visible secrets
- Core AI semantics
- Engine transport semantics
- product conversation/history/domain persistence

## Cross-cutting relationship

```text
                 IP-CONTROL
 identity / tenant / entitlement / usage / audit / neutral declarations
        │             │              │             │
     Product        Engine          Core           B14
```

Control Plane은 일반적으로 실행 call-chain 안에서 단순히 한 단계 아래로 흐르는 서비스로 이해하지 않습니다. 필요한 authority를 각 runtime에 제공하는 cross-cutting plane입니다.

## Security rule

- raw secrets를 browser/product state에 투영하지 않습니다.
- credential binding/reference와 secret value를 구분합니다.
- identity와 entitlement는 model routing과 독립된 authority입니다.
- product-tier declaration이 존재해도 B14 executability gate를 우회하지 않습니다.

Central authority:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
