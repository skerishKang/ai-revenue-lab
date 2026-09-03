# Padiem Sidecar Architecture

## Target topology

```text
Host website / app
        │
        ├─ host page + product session
        │
        ▼
B53 Padiem Sidecar product layer
        │
        ├─ customer configuration
        ├─ install/bootstrap
        ├─ branding / plan / admin
        └─ product adapter selection
        │
        ▼
Product / Customer Adapter
        │
        ▼
IP-SIDECAR  (proposed shared embedded runtime)
        │
        ▼
IP-ENGINE
        │
        ▼
IP-CORE
        │
        ▼
B14 Korean AI Platform
        │
        ▼
Provider / Model
```

Shared Control Plane is a parallel authority for tenant/account identity, entitlement, usage/billing truth and shared audit policy.

## Component responsibilities

### B53 product layer

Owns customer-visible SaaS/product concerns: onboarding, installation, configuration, branding, plan presentation, integration health and support.

### Product/customer adapter

Owns domain meaning and the conversion between host state and generic Sidecar/Engine/Core contracts.

Examples:

- `LoveBud`: artist/fandom/LoveTree semantics;
- `StoryMemory`: reading-boundary/spoiler/annotation semantics;
- `400 AI Finder`: site navigation/notice/application semantics.

### IP-SIDECAR

Planned generic embedded runtime. Owns reusable UI/runtime primitives, not customer domain semantics.

### IP-ENGINE

Owns trusted cross-runtime service identity and execution transport.

### IP-CORE

Owns shared AI execution, Evidence, grounding, retrieval/memory, tools, agents/skills and web/research semantics.

### B14

Owns Provider/model registry, credentials, routing, fallback and actual model execution.

### Control Plane

Owns canonical tenant/account identity, entitlement, authoritative usage/billing and shared audit/security policy.

## Trust boundaries

```text
Browser / host DOM              = untrusted context by default
Trusted host server projection  = may carry product authority within an explicit adapter contract
Sidecar public config           = non-secret, bounded
Sidecar server config           = trusted product configuration
Engine service identity         = server-only
Provider credentials            = B14-only
```

No browser-provided field may widen model/provider, tenant, billing, action or tool authority.

## Request flow

1. Host loads the Sidecar bootstrap using a public Sidecar identifier.
2. Trusted Sidecar backend resolves tenant/site configuration.
3. Host/browser supplies bounded page/context evidence.
4. Product adapter normalizes domain intent/context.
5. IP-SIDECAR creates the generic embedded execution request/projection.
6. IP-ENGINE authenticates the service caller and executes through Core.
7. Core applies shared evidence/research/memory/tool semantics.
8. B14 selects/executes the approved model/provider route.
9. Normalized events/results return through Engine/Core.
10. Sidecar renders only public-safe product projections.

## Action flow

Read assistance and host mutations are separate contracts.

```text
AI suggestion
  -> Sidecar action proposal
  -> product/customer adapter validates capability
  -> trusted policy / approval
  -> exact host action adapter
  -> bounded result
```

The model cannot invoke arbitrary host functions or URLs.

## Deployment model direction

The preferred architecture separates:

- versioned Sidecar frontend assets/bootstrap;
- trusted Sidecar service/config endpoint;
- existing shared Engine/Core/B14 runtimes;
- customer host product deployment.

Exact CDN/Worker/project names are deferred until implementation authority exists.

## Version contract

Each integration should eventually carry:

```text
sidecar_public_id
sidecar_runtime_version
adapter_id
adapter_version
host_integration_version
configuration_version
```

A version mismatch fails visibly and safely rather than silently changing host behavior.

## No-shortcut rules

```text
IFRAME_B62_AS_PLATFORM = NO
DIRECT_B53_TO_PROVIDER = NO
DIRECT_BROWSER_TO_ENGINE_MACHINE_AUTH = NO
PRODUCT_SPECIFIC_LOGIC_IN_IP_SIDECAR = NO
CORE_LOGIC_DUPLICATED_IN_SIDECAR = NO
```

Refs #1722 #1723 #1707 #1698