# Padiem Internal Platform

Status: canonical management layer for shared Padiem platform components.

This directory exists so shared AI infrastructure can be found, governed and reused without pretending that an internal platform component is a numbered Business.

## Canonical component IDs

| Internal Platform ID | Canonical name | Source authority | Runtime state | Business number |
|---|---|---|---|---|
| `IP-CORE` | Padiem AI Core | `packages/padiem-ai-core/` | shared runtime library | NONE |
| `IP-ENGINE` | Padiem AI Engine | `apps/padiem-ai-engine/` | internal cross-runtime service | NONE |
| `IP-CONTROL` | Padiem Control Plane | `packages/padiem-control-plane/` | shared control/policy package | NONE |
| `IP-SIDECAR` | Padiem Embedded AI Runtime | `packages/padiem-embedded-runtime/` | S2 minimal contract source-present; non-production | NONE |

These IDs are management identifiers only. They do not alter source paths, package names, Worker names, Business numbering or deployment identities.

## Default AI integration topology

```text
Product / Business adapter
        |
        +--> IP-SIDECAR — reusable embedded shell/context/event primitives when needed
        |
        v
IP-ENGINE — cross-runtime service identity / transport
        |
        v
IP-CORE — shared AI contracts and runtimes
        |
        v
B14 Korean AI Platform — provider/model/routing/execution authority
        |
        v
Provider / Model

IP-CONTROL = cross-cutting canonical identity / tenant / entitlement / usage / audit authority
```

For same-runtime/library consumers inside an approved architecture, direct package reuse of `IP-CORE` may be appropriate. Cross-runtime or external products should use `IP-ENGINE` rather than reimplementing transport, service identity or provider access.

`IP-SIDECAR` is not a shortcut around Engine/Core. Its current S2 source provides embedded shell/context/event/bootstrap primitives only; it has no real Engine transport, Provider calls or Production activation.

## Business vs Internal Platform

The canonical Business registry remains `docs/portfolio/BUSINESS_REGISTRY.md`.

Internal Platform components are deliberately not assigned B-numbers. B14 remains a numbered Business because it is the Korean AI execution platform and provider/model/routing authority. B53 Padiem Sidecar remains the commercial product and primary consumer of `IP-SIDECAR`; it does not own the shared runtime.

## Documents

- `INTERNAL_PLATFORM_REGISTRY.md` — authoritative Internal Platform catalog.
- `AI_ADOPTION_PLAYBOOK.md` — default reuse path for adding AI to a Business or product.
- `core/README.md` — IP-CORE locator and ownership summary.
- `engine/README.md` — IP-ENGINE locator and ownership summary.
- `control-plane/README.md` — IP-CONTROL locator and ownership summary.
- `sidecar/README.md` — IP-SIDECAR current S2 source/runtime-contract state and ownership boundary.

## Governance rule

When a new generic capability is discovered, ask in order:

1. Is it product-specific? Keep it in the product adapter.
2. Is it a reusable browser-safe embedded shell/context/event/presentation primitive? Use `IP-SIDECAR`.
3. Is it reusable AI runtime semantics? Reuse or extend `IP-CORE`.
4. Is it cross-runtime service transport, identity or execution hosting? Use or extend `IP-ENGINE`.
5. Is it platform policy/control-plane state? Adjudicate `IP-CONTROL` ownership.
6. Is it provider/model/routing/credential authority? Keep it under B14.

Do not create a second copy of a generic capability in a Business merely because that Business is the first consumer to need it.

Refs #1707 #1739 #2135.
