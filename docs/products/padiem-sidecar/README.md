# B53 · Padiem Sidecar

Padiem Sidecar is the commercial embedded-AI product that brings Padiem's shared AI platform into an existing website or application without requiring the host product to rebuild its AI backend.

## Canonical identity

```text
Business: B53
Product: Padiem Sidecar
Korean: 파디엠 사이드카
Previous B53 identity: Embedded AI SDK
Previous identity disposition: retained as the integration/installation layer
Product decision: #1722
S0 documentation authority: #1723
```

Historical visual evidence remains under `reference/business-53-embedded-ai-sdk-v1/` and is not deleted or renamed by this program.

## Product promise

> Add a bounded AI workspace to an existing host product so users can ask, search, summarize, translate, analyze, use evidence, work with files, and later invoke approved host actions from the context they are already viewing.

The default presentation is an embedded right-side panel/drawer, but the product contract also allows inline or mobile-native presentation through the same shared runtime contract.

## Platform topology

```text
Host website/app
  -> B53 Padiem Sidecar product + customer configuration
  -> Product/Customer Adapter
  -> IP-SIDECAR (proposed shared embedded runtime)
  -> IP-ENGINE
  -> IP-CORE
  -> B14 Korean AI Platform
  -> Provider / Model
```

Shared Control Plane remains the authority for canonical tenant/account identity, entitlement, usage, billing and shared audit policy.

## Why B53 now

The same embedded-AI pattern is already visible in multiple products:

- B30 / 400 AI Finder: target site or faithful clone + right-side AI search/navigation/browser-assist surface.
- B61 / StoryMemory: reading/content surface + contextual AI assistant.
- B23 / LoveBud: fan/LoveTree surface + Scout AI analysis/translation/research/memory flow.

B62 Padiem Chat remains the standalone general AI frontdoor. B54 Padiem Claw remains the agent/computer/code product. Sidecar is the embedded distribution product.

## Canonical documents

- [Product Charter](PRODUCT_CHARTER.md)
- [Product Requirements](PRODUCT_REQUIREMENTS.md)
- [Architecture](ARCHITECTURE.md)
- [Ownership Boundaries](OWNERSHIP_BOUNDARIES.md)
- [Embed and Host Integration](EMBED_AND_HOST_INTEGRATION.md)
- [Tenancy, Security and Privacy](TENANCY_SECURITY_AND_PRIVACY.md)
- [Operations Runbook](OPERATIONS_RUNBOOK.md)
- [Release and Rollback](RELEASE_AND_ROLLBACK.md)
- [Reliability and Incidents](RELIABILITY_AND_INCIDENTS.md)
- [Customer Onboarding](CUSTOMER_ONBOARDING.md)
- [Pricing and Commercialization](PRICING_AND_COMMERCIALIZATION.md)
- [Adoption and Reuse Matrix](ADOPTION_AND_REUSE_MATRIX.md)
- [Roadmap](ROADMAP.md)

## Standing rules

```text
B53_IS_COMMERCIAL_PRODUCT = YES
GENERIC_EMBED_RUNTIME_BELONGS_TO_INTERNAL_PLATFORM = YES
DIRECT_PROVIDER_OWNERSHIP_IN_B53 = NO
CORE_SEMANTICS_REIMPLEMENTED_IN_B53 = NO
ENGINE_TRANSPORT_REIMPLEMENTED_IN_B53 = NO
CONTROL_PLANE_TRUTH_REIMPLEMENTED_IN_B53 = NO
PRODUCT_SPECIFIC_DOMAIN_SEMANTICS_STAY_IN_ADAPTER = YES
```

## Current phase

```text
S0 = PRODUCT CONSOLIDATION + DOCUMENTATION
LIVE_SIDECAR_RUNTIME = NOT YET AUTHORIZED
IP_SIDECAR_REGISTRATION = DEPENDS ON #1707 / PR #1713
PRODUCTION_MUTATION = NO
```

Refs #1722 #1723 #313 #315 #1707