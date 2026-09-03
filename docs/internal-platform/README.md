# Padiem Internal Platform

Status: canonical management layer for shared Padiem platform components.

This directory exists so shared AI infrastructure can be found, governed, and reused without pretending that an internal platform component is a numbered Business.

## Canonical component IDs

| Internal Platform ID | Canonical name | Source authority | Business number |
|---|---|---|---|
| `IP-CORE` | Padiem AI Core | `packages/padiem-ai-core/` | NONE |
| `IP-ENGINE` | Padiem AI Engine | `apps/padiem-ai-engine/` | NONE |
| `IP-CONTROL` | Padiem Control Plane | `packages/padiem-control-plane/` | NONE |

These IDs are management identifiers only. They do not alter source paths, package names, Worker names, Business numbering, or deployment identities.

## Why this layer exists

AI Revenue Lab contains many numbered Businesses and external products that use AI. Shared capabilities must therefore be easier to discover than ad-hoc repository searches and historical Issue-number archaeology.

The Internal Platform layer provides one place to answer:

- where a shared capability lives;
- which component owns it;
- which products consume it;
- which platform dependency it has;
- which current Issue/PR is changing it;
- whether a new Business should reuse Core, extend Core, use Engine transport, or keep logic product-local.

## Default AI integration topology

```text
Product / Business adapter
        |
        v
IP-ENGINE — cross-runtime service identity / transport
        |
        v
IP-CORE — shared AI contracts and runtimes
        |
        v
B14 Korean AI Platform — provider/model/routing authority
        |
        v
Provider / model
```

For same-runtime/library consumers inside an approved architecture, direct package reuse of `IP-CORE` may be appropriate. Cross-runtime or external products should use `IP-ENGINE` rather than reimplementing transport, service identity, or provider access.

## Business vs Internal Platform

The canonical Business registry remains `docs/portfolio/BUSINESS_REGISTRY.md`.

Internal Platform components are deliberately not assigned B-numbers. B14 remains a numbered Business because it is the Korean AI execution platform and the provider/model/routing authority. Internal Platform records reference B14 as a dependency where appropriate.

## Documents

- `INTERNAL_PLATFORM_REGISTRY.md` — authoritative Internal Platform catalog.
- `AI_ADOPTION_PLAYBOOK.md` — default reuse path for adding AI to a Business or product.
- `core/README.md` — IP-CORE locator and ownership summary.
- `engine/README.md` — IP-ENGINE locator and ownership summary.
- `control-plane/README.md` — IP-CONTROL locator and ownership summary.

## Governance rule

When a new generic capability is discovered, ask in order:

1. Is it product-specific? Keep it in the product adapter.
2. Is it reusable AI runtime semantics? Reuse or extend `IP-CORE`.
3. Is it cross-runtime service transport, identity, or execution hosting? Use or extend `IP-ENGINE`.
4. Is it platform policy/control-plane state? Adjudicate `IP-CONTROL` ownership.
5. Is it provider/model/routing/credential authority? Keep it under B14.

Do not create a second copy of a generic capability in a Business merely because the Business is the first consumer to need it.

Refs #1707.
