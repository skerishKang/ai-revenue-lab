# Padiem AI Adoption Playbook

Purpose: give every Business/product a repeatable path for adding AI without rebuilding generic runtime, transport, or provider infrastructure.

## 1. Default decision sequence

Before writing AI code for a Business, classify the requested capability.

```text
PRODUCT_ADAPTER
REUSE_CORE
EXTEND_CORE
ENGINE_TRANSPORT
CONTROL_PLANE
B14_EXECUTION
DO_NOT_SHARE
```

### PRODUCT_ADAPTER
Keep domain meaning in the product.

Examples:
- fan/artist/member semantics;
- StoryMemory locator/book semantics;
- product-specific output presentation;
- product-specific save/persistence behavior.

### REUSE_CORE
Use an existing IP-CORE capability when the need is generic AI runtime semantics.

Examples include the existing Core execution, Evidence, grounding, retrieval/memory, Web, Tool, streaming, context-permission, and orchestration foundations.

### EXTEND_CORE
Extend IP-CORE only when a proven reusable generic gap exists and more than one product could reasonably benefit from the capability.

Do not extend Core merely to encode one Business's domain vocabulary.

### ENGINE_TRANSPORT
Use IP-ENGINE for cross-runtime/service-boundary needs:

- Service Binding transport;
- trusted first-party caller identity;
- execute/stream/orchestration wire boundaries;
- hosting Core for external/cross-runtime product adapters.

### CONTROL_PLANE
Use or extend IP-CONTROL for reusable platform control/policy contracts when that state is not product-local authorization.

### B14_EXECUTION
Provider/model selection, routing, fallback/retry policy, provider adapters, and provider credentials remain B14 authority.

### DO_NOT_SHARE
Keep genuinely product-specific implementation in the product instead of creating a premature shared abstraction.

## 2. Default topology for cross-runtime products

```text
Business/Product UI
        |
        v
same-origin server Product adapter
        |
        v
IP-ENGINE
        |
        v
IP-CORE
        |
        v
B14 Korean AI Platform
        |
        v
Provider/model
```

Hard defaults:

```text
PRODUCT_DIRECT_PROVIDER = NO
PRODUCT_PROVIDER_SECRET = NO
PRODUCT_DIRECT_B14 = NO unless explicitly governed as a B14 client boundary
EXTERNAL_PRODUCT_DIRECT_CORE = NO
GENERIC_CORE_SEMANTICS_DUPLICATED_IN_PRODUCT = NO
```

## 3. Same-runtime/library exception

Some products inside `ai-revenue-lab` may be approved to consume `packages/padiem-ai-core` as an in-process package rather than crossing the Engine Worker boundary.

That is an architecture choice, not a shortcut. It must still preserve:

- Core ownership of generic AI semantics;
- B14 ownership of provider/model routing;
- product ownership of domain semantics;
- no provider secret in browser/product static assets.

External repositories and independent Cloudflare products should default to IP-ENGINE.

## 4. New Business AI integration checklist

### A. Product contract

Define:

- user intent;
- product-owned domain fields;
- bounded input/output contract;
- explicit persistence/save behavior;
- product-specific safety/presentation behavior.

### B. Reuse audit

Check `IP-CORE` before implementing:

- execution;
- Evidence/grounding;
- Web/research;
- retrieval/memory;
- Tool runtime;
- streaming;
- context permission;
- orchestration.

If the capability already exists, reuse it.

### C. Transport audit

For a cross-runtime product, identify:

- IP-ENGINE Service Binding or approved ingress path;
- independent caller identity;
- independent high-entropy credential;
- allowed application ID;
- fail-closed behavior when binding/credential is absent.

Never copy another product's credential.

### D. B14 execution audit

Confirm the product does not own:

- provider API keys;
- provider base URLs;
- model selection tables;
- provider fallback;
- provider retry policy.

### E. Verification

Prove in order:

1. zero-network/fake contract tests;
2. Engine/Core/B14 boundary tests;
3. preview/staging identity and binding;
4. one bounded private runtime canary when authorized;
5. product output parity;
6. rollback evidence;
7. only then Production activation.

## 5. Cross-product reusability gate

Before adding a generic-looking feature to a Business, ask:

```text
COULD_ANOTHER_PADIEM_PRODUCT_USE_THIS = YES / NO
COULD_B61_USE_THIS = YES / NO
COULD_B62_USE_THIS = YES / NO
```

If YES and the capability is not a thin Product adapter, adjudicate IP-CORE/IP-ENGINE/IP-CONTROL ownership before burying it in the first consumer.

## 6. Example — LoveBud Scout

```text
LoveBud fan-domain intent/output = PRODUCT_ADAPTER
completed AI execution = IP-ENGINE -> IP-CORE -> B14
provider/model routing = B14_EXECUTION
future generic web/research projection = IP-ENGINE + existing IP-CORE Web/Research
LoveTree save semantics = PRODUCT_ADAPTER
```

LoveBud therefore does not duplicate Core Web Runtime, provider routing, or another product's Engine credential.

## 7. Platform discoverability

Use the Portfolio Console `Internal Platform` view or `INTERNAL_PLATFORM_REGISTRY.md` to locate the component before starting a new architecture lane.

Canonical prefixes for new shared-platform work:

```text
[IP-CORE]
[IP-ENGINE]
[IP-CONTROL]
```

Refs #1707.
