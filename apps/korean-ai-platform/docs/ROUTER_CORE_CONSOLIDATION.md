# Business 14 Router Core Consolidation

## Status

```text
PUBLIC PRODUCT: Business 14 · Korean AI Platform
INTERNAL MODULE: Router Core
FORMER INDEPENDENT BUSINESS: Business 54 · AI Model Router — superseded
FIRST-PARTY CLIENT: Business 54 · Korean AI Code Agent
```

Authority: Issue #371.

## Why Router Core belongs here

Model access and model selection form one customer product boundary.

A personal user should not need separate accounts or surfaces to:

1. register a Provider key or local endpoint;
2. inspect available models;
3. choose a model or policy;
4. send a request;
5. inspect usage, cost and route evidence;
6. retry or use a fallback.

Business 14 already owns the Provider registry, BYOK gateway, catalog, API, workspace and usage boundary. Router Core therefore remains an internal module of that same platform.

## Existing baseline

Current Business 14 multi-Provider behavior already provides:

- server-configured Provider registry;
- deterministic model-to-Provider mapping;
- aggregated model catalog;
- key isolation across Providers;
- fail-closed invalid-registry behavior;
- request-scoped BYOK;
- network-free mocked-upstream tests.

Router Core extends this baseline. It must not silently replace it.

## Router Core responsibilities

### Eligibility

- Provider enabled and healthy;
- model enabled and compatible;
- requested modality, context, tools and parameters supported;
- privacy, region and retention hard constraints satisfied;
- credentials or platform access available;
- local hardware route available when requested.

### Preferences

After hard constraints pass, Router Core may apply:

- quality evidence;
- cost target;
- latency target;
- throughput target;
- Korean-language preference;
- local-first preference;
- domestic-processing preference;
- BYOK preference;
- user-pinned Provider or model order.

### Outcomes

```text
manual route
primary route
ordered Provider fallback
allowed model fallback
route degraded
no safe route
user/human handoff
```

### Evidence

Every route decision should later expose bounded reason codes such as:

```text
USER_PINNED_MODEL
LOCAL_FIRST
DOMESTIC_REGION_REQUIRED
ZERO_DATA_RETENTION_REQUIRED
PROVIDER_UNAVAILABLE
MODEL_CAPABILITY_MISMATCH
LOWEST_COST_WITHIN_CONSTRAINTS
LOWEST_LATENCY_WITHIN_CONSTRAINTS
FALLBACK_PROVIDER_SELECTED
NO_SAFE_ROUTE
```

Estimated and measured evidence must remain distinguishable.

## Personal-first product behavior

The initial platform experience prioritizes:

- simple Korean setup;
- personal BYOK;
- local/OpenAI-compatible endpoints;
- transparent manual choice;
- optional automatic selection;
- understandable usage and route explanation;
- easy integration with personal developer tools.

Do not lead with enterprise procurement, approval ledgers or organization policy administration.

## Business 54 Code Agent integration

Business 54 should call Business 14 rather than implement its own Provider layer.

Potential agent request metadata:

```json
{
  "task_type": "code_edit",
  "stage": "build",
  "privacy": "repository_local_preferred",
  "local_first": true,
  "allow_external_fallback": false,
  "required_capabilities": ["code", "tool_reasoning"],
  "user_model": null
}
```

The final production schema requires a separate implementation issue and compatibility review. This example is not a committed API contract.

## Failure boundary

Router Core must fail closed when:

- registry configuration is invalid;
- no eligible route satisfies hard constraints;
- required credentials are missing;
- an unavailable Provider is the only candidate;
- fallback is prohibited;
- a local-only request would require external transmission.

Do not force a cheapest or highest-scored model through a hard privacy or capability boundary.

## Historical source

Former Business 54 Router Issues #314 and #316 and closed-unmerged PR #318 remain available as historical product and visual evidence. They do not define a separate current product.

## Current non-goals

This consolidation document does not implement:

- live automatic routing;
- Provider resale;
- credit billing;
- persistent personal accounts;
- universal model benchmarking;
- local GPU discovery;
- Business 54 agent runtime;
- Production migration.
