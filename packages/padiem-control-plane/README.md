# IP-CONTROL · Padiem Control Plane

Padiem Control Plane is the shared authority for account/control state used across Padiem products and internal AI services.

It is an Internal Platform component, not a numbered Business.

```text
PLATFORM_ID = IP-CONTROL
CANONICAL_SOURCE = packages/padiem-control-plane/**
BUSINESS_NUMBER = NONE
```

Canonical cross-layer architecture:

`../../docs/architecture/PADIEM_AI_VERTICAL_STACK.md`

## Role

IP-CONTROL is cross-cutting authority. It is not a mandatory sequential hop in every AI request.

It owns or hosts the canonical shared contracts/services for areas such as:

- canonical identity/subject mapping;
- tenant/workspace/membership truth;
- entitlement/subscription truth;
- authoritative usage/credits/billing state where implemented;
- shared audit/security-event truth;
- trusted control-plane credential/OAuth lifecycle services where explicitly assigned;
- neutral product/profile declarations that must be consumed consistently by multiple products.

It does **not** own:

- reusable AI reasoning/execution semantics (IP-CORE);
- cross-runtime AI transport (IP-ENGINE);
- model/provider routing or external inference (B14);
- product chat/history/domain UX or product-local persistence;
- connector/business workflow semantics merely because OAuth/control state is involved.

## Padiem routing-profile declaration

`padiem_control_plane.product_tier_routes` is the neutral shared declaration source for the current Padiem Plus/Pro/Max mapping.

Current profile v1:

```text
Padiem Plus -> kilo/poolside-laguna-s-2.1-free
Padiem Pro  -> kilo/nvidia-nemotron-3-ultra-550b-a55b-free
Padiem Max  -> HOLD

PADIEM_PROFILE_V1_AUTO_ROUTING = NO
PADIEM_USER_VISIBLE_AUTO = NO
PADIEM_SILENT_FALLBACK = NO
```

This contract **declares product intent**. It does not become a Provider registry or execution router.

```text
Padiem profile declaration
  -> B14 catalog/executability validation
  -> exact provider/model dispatch
```

B14 remains final execution authority and may reject a declared route if it is retired, unregistered, unavailable, capability-incompatible, or not credential-ready.

The explicit v1 policy is specific to Padiem's current request. B14's general Router Platform may implement automatic optimization later, and a later Padiem profile may explicitly opt into it.

## Identity boundary

Products may keep product-local owner keys/history identifiers where required, but canonical cross-product subject/account authority must not be recreated independently by Chat, Claw, Engine, Core or another product.

Browser-asserted account/workspace/entitlement values are not canonical authority without a trusted server-side bridge.

## OAuth / credential boundary

Control-plane source may contain trusted OAuth/credential lifecycle components. Source presence does not prove Production client configuration, durable binding, secret installation or live connector readiness.

Raw credential values must never appear in product contracts, browser state, model context, issue bodies, committed docs or safe logs.

A credential being present does not itself select an AI route or authorize an external side effect.

## Runtime truth

Use current source/tests plus exact deployment/configuration evidence to distinguish:

```text
CONTRACT_DEFINED
SOURCE_PRESENT
DURABLE_BINDING_PRESENT
SECRET_CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

Documentation changes authorize none of the later states.