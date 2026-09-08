# IP-SIDECAR · Padiem Embedded AI Runtime

```text
DOC_STATUS = PROPOSED_COMPONENT_GUIDE
PLATFORM_ID = IP-SIDECAR
CANONICAL_NAME = Padiem Embedded AI Runtime
COMMERCIAL_PRODUCT = B53 Padiem Sidecar
SOURCE_AUTHORITY = NOT ACTIVATED BY THIS DOCUMENT
LAST_VERIFIED = 2026-09-08
```

IP-SIDECAR는 여러 first-party 제품과 외부 host에 재사용할 수 있는 **embedded AI presentation/runtime layer 후보**입니다. B53 Padiem Sidecar와 구분합니다.

## Distinction

```text
B53 Padiem Sidecar
= commercial product, packaging, customer onboarding, install journey, pricing

IP-SIDECAR
= reusable panel/shell + host bridge + browser-safe AI runtime presentation
```

## Target topology

```text
Host website/app
 -> Business/Customer Adapter
 -> B53 product layer when applicable
 -> IP-SIDECAR
 -> IP-ENGINE
 -> IP-CORE
 -> B14
 -> Provider/Model
```

## Target reusable ownership

- right-side drawer/panel, inline/mobile shell primitives
- host-context bridge
- bounded host ↔ AI event bridge
- public non-secret bootstrap/version projection
- streaming lifecycle presentation
- Evidence/citation presentation primitives
- action proposal/confirmation presentation primitives
- branding/theme token application
- integration health/compatibility diagnostics
- host-safe disable/failure behavior

## Explicit non-ownership

- product/customer domain semantics
- generic Tool/Skill/Agent/Memory/reasoning semantics
- Engine trusted machine/service auth
- Provider/model routing and secrets
- Control Plane tenant/entitlement/usage authority
- Claw task/run/sandbox semantics
- StoryMemory locator/progress/spoiler semantics

## Current status rule

Issue-level architecture has defined the intended identity and boundary, but this document does not claim a live source/runtime/Production activation. Until formal registry/source/runtime evidence exists:

```text
IP_SIDECAR_STATUS = PROPOSED
LIVE_RUNTIME_CLAIM = NO
PRODUCTION_CLAIM = NO
```

First-party candidates discussed in current architecture include B30 / 400 AI Finder, B61 / StoryMemory and B23 / LoveBud. Adoption requires a bounded product adapter and must not move each product's domain model into IP-SIDECAR.
