# Padiem Sidecar Roadmap

## S0 — Product consolidation and documentation

Status: current.

Deliver:

- B53 product identity consolidation;
- canonical docs/operations pack;
- Portfolio identity reconciliation;
- reuse/adoption matrix;
- no runtime or Production mutation.

## S1 — Internal Platform registration

Dependency: Internal Platform registry #1707 / PR #1713 merged and accepted.

Add:

```text
IP-SIDECAR = Padiem Embedded AI Runtime
```

Define exact source/runtime ownership before implementation. Do not fake a Business number for the internal component.

## S2 — Reference host + panel shell

Build one deterministic host fixture and reusable right-side Sidecar shell proving:

- desktop/mobile behavior;
- accessibility;
- theme tokens;
- open/close/disabled/error states;
- host primary journey unaffected.

No real model call required for the first shell.

## S3 — Host context + bootstrap/session

Implement bounded public bootstrap and context bridge:

- tenant/Sidecar public ID;
- allowed origin;
- adapter/version;
- structured current-page context;
- server-authoritative configuration;
- no browser machine secrets.

## S4 — Engine/Core execution

Integrate the reference Sidecar through IP-ENGINE/IP-CORE/B14.

Required:

```text
DIRECT_PROVIDER = NO
DIRECT_BROWSER_ENGINE_MACHINE_AUTH = NO
NORMALIZED_STREAMING = YES
FAIL_CLOSED = YES
```

## S5 — Evidence, files and reusable AI UI primitives

- citations/evidence;
- source inspection;
- files/images after storage/trust contract;
- research/status presentation;
- reusable error/retry/reconnect states.

## S6 — Approved action/tool bridge

Introduce capability allowlists and confirmation/approval UI for a bounded host action.

First action should be reversible/low-risk. No arbitrary host code execution.

## S7 — Multi-tenant admin/onboarding

Add customer/Business configuration flow:

- host registration;
- origins;
- branding;
- capabilities;
- adapter/version;
- preview/health;
- disable/rollback.

Control Plane integration occurs only through accepted identity/entitlement/usage contracts.

## S8 — First-party adoption reconciliation

Audit B30, B61 and LoveBud against IP-SIDECAR.

Goal is not immediate rewrite. Replace duplicated generic capabilities in bounded slices while preserving product-specific adapters and accepted production behavior.

## S9 — External customer pilot

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

Based on pilot evidence:

- finalize packaging/entitlements/pricing;
- billing/usage integration;
- support/SLA policy;
- admin/audit hardening;
- connector portfolio;
- enterprise/private deployment decisions;
- public product site and self-serve onboarding.

## Parallel platform dependencies

- #1698 and subsequent Engine service identity work may affect cross-product caller onboarding.
- IP-CORE Web/Research/Tool/Memory capabilities should be consumed rather than forked.
- B14 remains provider/model authority.
- Control Plane remains identity/entitlement/usage/billing authority.

## Success definition

Padiem should be able to add AI to a new Business or customer site primarily by implementing/configuring a product adapter and Sidecar configuration rather than rebuilding the AI stack.

```text
NEW_AI_BUSINESS_TIME_TO_INTEGRATE = REDUCED
GENERIC_CAPABILITY_DUPLICATION = REDUCED
PRODUCT_DOMAIN_OWNERSHIP = PRESERVED
EXTERNAL_CUSTOMER_ONBOARDING = REPEATABLE
```

Refs #1722 #1723 #1707 #1698