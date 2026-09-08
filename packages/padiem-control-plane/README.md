# Padiem Control Plane · IP-CONTROL

Padiem Control Plane is the shared **cross-cutting authority layer** for identity/subject/tenant/entitlement/usage/audit concerns and neutral cross-product declarations assigned to it. It is not Padiem's model execution router.

Canonical architecture:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/internal-platform/control-plane/README.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`

## Boundary

```text
                    Padiem Control Plane · IP-CONTROL
          identity / tenant / entitlement / usage / audit
              + neutral cross-product declarations
             │              │              │
          Product         Engine          B14
```

Control Plane is cross-cutting. It should not be modeled as a mandatory model-execution hop between Core and B14.

## Current source authority

```text
packages/padiem-control-plane/**
```

The package contains accepted identity/OAuth/connector authority components and neutral shared declarations. Exact runtime availability must be verified from the current source/composition that consumes them.

## Padiem product-tier declaration

A key current shared declaration is:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
```

It declares the current Padiem Plus/Pro/Max product-tier route identities and product policy. It does **not** become the Provider/model execution plane.

```text
Control Plane product-tier declaration
        │
        ▼
B14 catalog / executability validation
        │
        ▼
B14 Provider/model execution
```

Current declaration invariants include:

```text
AUTO_PROVIDER_SELECTION = NO
AUTO_MODEL_SELECTION = NO
USER_VISIBLE_AUTO_LABEL = NO
SILENT_FALLBACK = NO
```

For exact model IDs and current executable/hold state, read the current `product_tier_routes.py` and current B14 catalog rather than copying volatile route lists into unrelated docs.

## Owns / may host by accepted contract

- canonical subject/identity bridges
- tenant/workspace authority
- entitlement
- usage / credits / subscription
- audit
- connector/OAuth authority pieces assigned to Control Plane
- neutral declarations consumed by multiple products

## Does not own

- B14 Provider/model catalog and inference execution
- product conversation/history/domain persistence
- Padiem AI Core generic AI semantics
- Padiem AI Engine transport semantics
- raw secrets in browser/product-visible state

## Security and truth rules

- distinguish secret values from binding/reference identifiers;
- do not expose raw Provider or OAuth secrets in public/product contracts;
- identity/entitlement authority does not imply Provider-route authority;
- declaration does not imply executability;
- source presence does not imply Production activation.

## Testing

Use package-local tests plus the relevant product/B14 parity or integration checks when changing a shared contract. A neutral declaration change must not silently fork consumers into different product truth.
