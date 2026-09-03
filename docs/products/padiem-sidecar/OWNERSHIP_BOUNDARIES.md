# Padiem Sidecar Ownership Boundaries

## Why this document exists

B53 succeeds only if it reuses the shared Padiem AI platform instead of becoming another monolith.

## Ownership matrix

| Capability | Owner |
|---|---|
| Sidecar commercial product/onboarding/admin | B53 |
| Customer/Business domain semantics | Product/Customer Adapter |
| Embedded panel/runtime primitives | IP-SIDECAR (planned) |
| Cross-runtime service auth/transport | IP-ENGINE |
| Evidence/grounding/web/research/memory/tool/agent semantics | IP-CORE |
| Provider/model/routing/fallback/credentials | B14 |
| Canonical tenant/account/entitlement/usage/billing/audit | Control Plane |
| Host product data/actions | Host product + explicit adapter |

## B53 may own

- product identity and pricing/package presentation;
- customer/site onboarding;
- install documentation and SDK distribution experience;
- branding/theme configuration;
- product plan configuration;
- integration-health presentation;
- adapter selection and version presentation;
- customer support/operator workflows;
- public product portal and examples.

## B53 must not own

- a second model/provider registry;
- Provider secrets;
- a second Engine caller protocol;
- generic Tool Runtime;
- generic Agent/Skill execution;
- generic Memory/RAG trust/ranking/write policy;
- a second Evidence/Grounding model;
- canonical account/billing/credit truth;
- arbitrary customer backend execution.

## Product adapter rule

Every integration gets a bounded adapter. The adapter converts host-specific concepts into generic platform contracts and back.

Adapter examples:

```text
LoveBudAdapter
StoryMemoryAdapter
AiFinderAdapter
CustomerCommerceAdapter
CustomerHospitalAdapter
```

An adapter may contain product meaning. It must not become a second Core or Provider layer.

## Reuse decision gate

Every Sidecar-related PR should answer:

```text
SIDECAR_REUSE_CHECK = PASS / FAIL
GENERIC_CAPABILITY_DISCOVERED = YES / NO
IF_GENERIC_OWNER = B53_PRODUCT / IP_SIDECAR / IP_ENGINE / IP_CORE / B14 / CONTROL_PLANE
PRODUCT_SPECIFIC_ADAPTER_ONLY = YES / NO
PROVIDER_ROUTING_DUPLICATED = NO
CORE_SEMANTICS_DUPLICATED = NO
ENGINE_TRANSPORT_DUPLICATED = NO
CONTROL_PLANE_TRUTH_DUPLICATED = NO
```

## First-party products

### B30 / 400 AI Finder

B30 keeps site/municipality knowledge and navigation semantics. Generic right-side AI shell, evidence presentation, host bridge and execution transport are candidates for Sidecar reuse.

### B61 / StoryMemory

B61 keeps reading/spoiler/annotation policy. Generic panel, streaming, evidence/file primitives and Engine/Core transport are Sidecar/platform candidates.

### B23 / LoveBud

LoveBud keeps fandom/artist/LoveTree/Memory product semantics. Generic panel/runtime/research/streaming/action-confirmation primitives are candidates for Sidecar/platform reuse.

### B62 / Padiem Chat

B62 is a standalone product. Sidecar may reuse UI/runtime primitives where appropriate but must not consume B62 as the AI backend.

### B54 / Padiem Claw

Claw owns task/run/sandbox/repository product semantics. Sidecar may render public-safe agent progress later but does not own agent execution.

## Escalation rule

If a feature is useful to two or more products and is not domain-specific, do not copy it again. Open an owner issue in the appropriate Internal Platform component and integrate it through a reviewed contract.

Refs #1722 #1723 #1224