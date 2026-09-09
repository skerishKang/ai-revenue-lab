# Padiem Sidecar Roadmap

## Status legend

```text
COMPLETE = accepted source/documentation foundation is merged
PARTIAL = bounded source exists but the full roadmap outcome is not live
BLOCKED = next step is explicitly gated by an upstream owner/runtime dependency
PLANNED = not yet started as an accepted implementation slice
```

## S0 — Product consolidation and documentation

Status: COMPLETE.

Delivered:

- B53 product identity consolidation;
- canonical docs/operations pack;
- Portfolio identity reconciliation;
- reuse/adoption matrix;
- no runtime or Production mutation.

## S1 — Internal Platform registration

Status: COMPLETE for shared runtime ownership/foundation.

```text
IP-SIDECAR = Padiem Embedded AI Runtime
```

The reusable embedded runtime is owned as an Internal Platform component, not a Business-number duplicate. See #1739 and the internal platform registry lineage.

## S2 — Reference host + panel/runtime primitives

Status: COMPLETE for deterministic/reference-host and shared runtime foundations.

Accepted work establishes reusable shell/runtime primitives and a deterministic B53 reference host without requiring a live model call. B53 product adapter/reference-host conformance is tracked by #2180.

## S3 — Host context + bootstrap/session

Status: PARTIAL.

Bounded public bootstrap/context and host-safe runtime contracts exist in IP-SIDECAR/B53 source. Canonical session/tenant authority is not owned by B53 and live trusted scope remains an Engine/Control Plane concern.

## S4 — Engine/Core execution

Status: BLOCKED on trusted Engine scope composition and subsequent B53 server-mediated EnginePort work.

Required chain:

```text
#2195 Engine -> Control Plane auth-session Service Binding trusted scope
  -> #2198 B53 server-mediated EnginePort preflight/implementation
  -> live integration gate in a separate accepted slice
```

Required invariants remain:

```text
DIRECT_PROVIDER = NO
DIRECT_BROWSER_ENGINE_MACHINE_AUTH = NO
NORMALIZED_STREAMING = YES
FAIL_CLOSED = YES
```

## S5 — Evidence, files and reusable AI UI primitives

Status: PARTIAL.

Reusable evidence/citation, attachment/file presentation, stream/error/retry lifecycle primitives exist in IP-SIDECAR. Real attachment execution still depends on trusted Engine scope composition and accepted server-mediated transport; source presence is not Production activation.

## S6 — Approved action/tool bridge

Status: PARTIAL.

Approval/confirmation presentation primitives exist in the shared runtime. A real bounded host action bridge with authoritative capability policy remains a later slice. No arbitrary host code execution is authorized.

## S7 — Multi-tenant admin/onboarding

Status: PARTIAL — local product surface complete, live Control Plane/commercial authority not complete.

#2194 merged B53-owned local-conformance source for:

- install/bootstrap version contract;
- site/app registration product projection;
- onboarding state flow;
- integration-health diagnostics;
- normal/malformed fixtures and tests.

It does not create canonical tenant/account authority, real CDN/package publication, Production activation, or external customer readiness.

## S8 — First-party adoption reconciliation

Status: PLANNED.

Audit B30, B61 and LoveBud against IP-SIDECAR.

Goal is not immediate rewrite. Replace duplicated generic capabilities in bounded slices while preserving product-specific adapters and accepted production behavior.

## S9 — External customer pilot

Status: PLANNED.

Choose one bounded external host with low-sensitivity/public context and one or two measurable journeys.

Prove:

- onboarding repeatability;
- install time;
- user value;
- reliability;
- support burden;
- real platform cost;
- rollback/offboarding.

## S10 — Commercial hardening

Status: PLANNED.

Based on pilot evidence:

- finalize packaging/entitlements/pricing;
- billing/usage integration;
- support/SLA policy;
- admin/audit hardening;
- connector portfolio;
- enterprise/private deployment decisions;
- public product site and self-serve onboarding.

## Parallel platform dependencies

- Engine trusted session/tenant scope authority remains upstream of real B53 EnginePort integration (#2195).
- IP-CORE Web/Research/Tool/Memory capabilities should be consumed rather than forked.
- B14 remains provider/model authority.
- Control Plane remains identity/entitlement/usage/billing authority.
- Google/other connector activation remains owned by the shared connector program rather than B53.

## Success definition

Padiem should be able to add AI to a new Business or customer site primarily by implementing/configuring a product adapter and Sidecar configuration rather than rebuilding the AI stack.

```text
NEW_AI_BUSINESS_TIME_TO_INTEGRATE = REDUCED
GENERIC_CAPABILITY_DUPLICATION = REDUCED
PRODUCT_DOMAIN_OWNERSHIP = PRESERVED
EXTERNAL_CUSTOMER_ONBOARDING = REPEATABLE
```

Refs #1722 #1723 #1739 #2180 #2194 #2195 #2198 #1707