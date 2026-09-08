# Padiem Sidecar Operations Runbook

## Operating model

Padiem Sidecar is a multi-tenant embedded product. Operations must keep product configuration, shared platform runtime and each host integration independently observable and reversible.

## Environment model

Target environments:

```text
DEV
PREVIEW
PRODUCTION
```

A customer/Business must not be promoted to Production solely because the generic Sidecar runtime is healthy. The exact tenant/site configuration and adapter version must be accepted too.

## Onboarding checklist

1. identify tenant/customer and host product;
2. register approved host origins;
3. select/create bounded product adapter;
4. define context/data scopes;
5. define enabled read capabilities;
6. define any host action capabilities and approval requirements;
7. configure branding/language/presentation;
8. verify tenant isolation and secrets boundary;
9. install in dev/preview host;
10. run context, evidence, streaming and failure-mode QA;
11. capture exact Sidecar/adapter/config versions;
12. obtain explicit Production activation decision.

## Daily/continuous operating signals

Future dashboards/telemetry should distinguish:

- bootstrap success/failure;
- host-origin/config mismatch;
- Sidecar open/session start;
- Engine/Core execution success/failure;
- streaming interruption;
- evidence/research failure;
- host action proposed/approved/failed;
- adapter/version mismatch;
- tenant kill-switch state;
- usage/cost state from authoritative platform sources.

No metric should leak Provider credentials or customer private payloads.

## Configuration ownership

```text
B53 admin/product config = Sidecar product settings
Product Adapter config = domain/host integration settings
IP-SIDECAR = generic embedded runtime config
IP-ENGINE = service execution config
IP-CORE = shared runtime semantics/config
B14 = provider/model config
Control Plane = canonical identity/entitlement/usage/billing/audit
```

Operators must change the owning layer rather than patching around it in B53.

## Integration health states

Recommended public/operator states:

```text
READY
DEGRADED_AI
DEGRADED_CONTEXT
ACTION_DISABLED
CONFIGURATION_ERROR
ADAPTER_INCOMPATIBLE
DISABLED_BY_OPERATOR
```

Do not report READY if only the panel loads while Engine/Core execution is unavailable.

## Kill switch

At minimum future operations need:

- per-Sidecar disable;
- per-tenant disable;
- per-capability disable;
- global emergency disable.

A disable must fail safely without taking down the host site/app.

## Change management

Every production-impacting change records:

```text
TENANT/HOST
ENVIRONMENT
CURRENT_RUNTIME_VERSION
CURRENT_ADAPTER_VERSION
CURRENT_CONFIG_VERSION
TARGET_VERSION/CHANGE
ROLLBACK_ANCHOR
TEST/QA EVIDENCE
APPROVAL
```

## Customer adapter changes

Adapter changes receive their own compatibility/QA gate. A generic Sidecar runtime release must not silently alter product-specific semantics.

## Cost/usage operations

B53 may display customer usage/cost only from authoritative platform records. Do not infer billing from browser request counts.

Operating review should track:

- AI execution volume;
- retrieval/tool volume where available;
- high-cost capability usage;
- errors/retries;
- tenant plan/entitlement state;
- anomalous bursts/abuse signals.

## Support escalation

Route defects by owner:

```text
Install/UI/branding/customer admin -> B53
Host/domain semantics -> Product/Customer Adapter
Embedded runtime/browser bridge -> IP-SIDECAR
Cross-runtime auth/transport -> IP-ENGINE
Evidence/research/memory/tool semantics -> IP-CORE
Provider/model/routing -> B14
Identity/entitlement/usage/billing -> Control Plane
Host backend/action implementation -> Host owner
```

## Offboarding

1. disable production Sidecar;
2. confirm host no longer depends on Sidecar for primary journey;
3. revoke tenant/customer connector/action credentials as applicable;
4. remove host-origin/config authority;
5. execute agreed retention/deletion process;
6. preserve only required operational/audit evidence;
7. confirm customer-side embed removal/disable.

## S0 note

This runbook defines the operating contract. No live Sidecar environment exists by authority of this document alone.

Refs #1722 #1723