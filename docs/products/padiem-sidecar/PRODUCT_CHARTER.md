# Padiem Sidecar Product Charter

## Mission

Padiem Sidecar turns Padiem's shared AI platform into an installable product surface for existing websites and applications.

The host keeps its own product identity and domain logic. Sidecar adds a contextual AI workspace without making the host own model routing, AI runtime infrastructure or shared agent/search/memory semantics.

## Primary customer problem

Organizations want useful AI inside the product their users already use, but repeatedly rebuilding chat UI, search, context, streaming, files, evidence, memory, tools, model routing and operational controls per site is expensive and inconsistent.

Padiem Sidecar solves that repeated integration problem.

## Product thesis

```text
Existing host product
+ bounded product adapter
+ shared Sidecar runtime
+ Padiem Engine/Core/B14
= contextual embedded AI without rebuilding the host
```

## Primary users

- product owners adding AI to an existing website/app;
- organizations that need a branded AI assistant without operating model infrastructure;
- internal Padiem Businesses that need a reusable AI panel/runtime;
- integration teams building customer-specific adapters;
- end users who want AI in the context of the page/workflow they are already using.

## Initial proof set

The product thesis is supported by recurring first-party patterns in:

- B30 / 400 AI Finder;
- B61 / StoryMemory;
- B23 / LoveBud.

These are reference consumers, not permission to merge their domain semantics into B53.

## Product principles

1. **Host-preserving** — Sidecar augments an existing product; it does not require redesigning the host.
2. **Contextual** — current-page and trusted host state should be usable through explicit contracts.
3. **Platform-backed** — shared intelligence comes from IP-ENGINE/IP-CORE/B14, not duplicated product code.
4. **Domain-adapted** — each Business/customer keeps domain semantics in a bounded adapter.
5. **Action-aware** — read-only assistance comes first; writes/actions require explicit capability and approval policy.
6. **Tenant-isolated** — customer data, memory, tools and credentials never cross tenant boundaries.
7. **Host-safe failure** — Sidecar can fail or be disabled without breaking/mutating the host product.
8. **Progressive capability** — Basic chat/search can ship before advanced tools/agents.
9. **Observable** — integration health, version, runtime errors and usage are diagnosable without secret leakage.
10. **Commercially packageable** — a repeatable onboarding and operating model must replace bespoke one-off integration.

## Product scope

B53 owns:

- commercial Sidecar product identity;
- onboarding/configuration/admin experience;
- installation/distribution experience;
- branding and presentation configuration;
- product packaging and support;
- adapter selection/configuration;
- customer-facing health and integration diagnostics.

B53 does not own:

- Provider/model registry or credentials;
- generic AI execution policy;
- generic Memory/RAG/Tool/Agent semantics;
- shared execution transport;
- canonical identity/entitlement/billing truth;
- customer-specific domain logic that belongs in an adapter.

## Product relationships

```text
B62 Padiem Chat = standalone general AI experience
B54 Padiem Claw = agent/computer/code product
B53 Padiem Sidecar = embedded AI product
B14 = provider/model/routing platform
```

## Commercial outcome

The target outcome is a repeatable SaaS/integration product where a customer can register a host, configure allowed AI capabilities, preview the Sidecar, install it through a bounded integration contract, and operate it with observable version/health/usage controls.

## Current status

```text
PRODUCT_FRAMED = YES
RUNTIME_PRODUCT = NOT_YET_BUILT
EXTERNAL_CUSTOMER_READY = NO
FIRST_PARTY_REUSE_EVIDENCE = YES
PRODUCTION_MUTATION = NO
```

Refs #1722 #1723