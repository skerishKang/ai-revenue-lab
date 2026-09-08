# Product Documentation Index

Product documents describe Business/product promises, customer journeys, product-specific state and commercialization. They **specialize** the shared Padiem AI stack; they do not redefine shared AI-layer ownership.

Current cross-layer authority:

`../architecture/PADIEM_AI_VERTICAL_STACK.md`

## Product-document rule

A product may own:

- product UX and customer journey;
- domain semantics;
- product-local persistence/state;
- product-specific Product Adapter;
- product-specific commercial/operations rules.

A product document must not silently claim ownership of:

- reusable AI semantics -> IP-CORE;
- cross-runtime AI service projection -> IP-ENGINE;
- provider/model routing and inference -> B14;
- canonical identity/tenant/entitlement/usage/billing truth -> IP-CONTROL;
- reusable embedded runtime primitives -> IP-SIDECAR where applicable.

## Padiem AI product relationships

```text
B62 Padiem Chat   = standalone general AI/chat/workspace product
B54 Padiem Claw   = agent/business-work product
B53 Padiem Sidecar= commercial embedded-AI delivery product
B61 StoryMemory   = reading/memory AI product (private application-source authority)
B30 400 AI Finder = AI/search product consuming shared Web/Research/Evidence
```

These products remain independent Business/product boundaries while reusing the shared stack.

## Snapshot / historical packs

Issue-numbered product packs and dated status tables are often point-in-time evidence. Their product thesis may remain useful, but volatile assertions such as `IN PROGRESS`, exact PR numbers, route mappings, provider availability, or Production readiness must be revalidated against current authority.

In particular:

- `B54_PADIEM_CLAW_CANONICAL_PRODUCT_PACK_1399.md` is a **2026-09-07 product/operations snapshot**. Current B54 identity comes from `../../apps/korean-ai-code-agent/docs/00_SOURCE_OF_TRUTH.md`; current cross-layer architecture comes from `../architecture/PADIEM_AI_VERTICAL_STACK.md`.
- `B60_PRODUCT_IA_AND_B14_HANDOFF_ARCHITECTURE.md` remains a B60 product/handoff document; B14's current Router Platform/Padiem-profile authority is in `../../apps/korean-ai-platform/README.md` and its current charter.

## Runtime truth

Product docs cannot turn a feature into a live capability. Distinguish:

```text
PRODUCT_DESIGNED
SOURCE_PRESENT
SHARED_CONTRACT_AVAILABLE
CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

Exact deployment/readback evidence is required for Production claims.