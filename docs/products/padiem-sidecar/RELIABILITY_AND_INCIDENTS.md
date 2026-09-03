# Padiem Sidecar Reliability and Incidents

## Reliability objective

Sidecar is an augmentation layer. A Sidecar failure must not take down or corrupt the host product's primary journey.

## Incident classes

### SEV-1 — host or cross-tenant risk

Examples:

- Sidecar breaks the host's primary page/journey;
- cross-tenant data exposure;
- secret/credential exposure;
- unauthorized material host action;
- global runtime defect affecting many tenants with unsafe behavior.

Default response:

```text
IMMEDIATE DISABLE / CONTAIN
PRESERVE EVIDENCE
STOP AFFECTED WRITES
ESCALATE TO OWNER
NO SILENT RETRY OF MATERIAL ACTIONS
```

### SEV-2 — tenant production unavailable or materially wrong

Examples:

- tenant Sidecar cannot bootstrap/execute;
- adapter/context mismatch gives materially incorrect domain behavior;
- evidence/research path broadly unavailable;
- approved action capability fails persistently.

Response: tenant/capability disable or rollback, bounded diagnosis, restore accepted version.

### SEV-3 — degraded/non-critical

Examples:

- theme/UI defect;
- intermittent streaming reconnect issue;
- non-critical analytics/diagnostic failure;
- one optional capability unavailable.

Response: preserve host operation, ticket/fix in normal release lane.

## Detection signals

Future telemetry should support:

- bootstrap error rate;
- execution/stream completion rate;
- context/config/adapter rejection rate;
- evidence/research error rate;
- host action error/replay conflict rate;
- tenant disable state;
- abnormal usage/burst signals;
- version-specific regression signals.

## Incident triage fields

```text
INCIDENT_ID
TENANT/SIDECAR
HOST/ORIGIN
ENVIRONMENT
RUNTIME_VERSION
ADAPTER_VERSION
CONFIG_VERSION
FIRST_OBSERVED
SCOPE
USER/HOST IMPACT
DATA/SECRET IMPACT
ACTION IMPACT
CURRENT_CONTAINMENT
ROLLBACK_ANCHOR
OWNER_LAYER
```

Do not copy sensitive customer payloads into public issue evidence.

## Ownership routing

- install/UI/admin -> B53;
- embedded runtime/browser bridge -> IP-SIDECAR;
- service auth/transport -> IP-ENGINE;
- shared AI semantics -> IP-CORE;
- provider/model -> B14;
- identity/entitlement/billing -> Control Plane;
- domain semantics/action backend -> product/customer adapter/host owner.

## Recovery rules

- restore host safety first;
- prefer tenant/capability-specific disable before global shutdown;
- do not retry material actions without idempotency/replay evidence;
- do not switch to a direct Provider shortcut when Engine/Core is down;
- preserve exact pre/post configuration and version evidence;
- rollback success requires functional verification, not only deploy success.

## Post-incident review

Capture:

- trigger/root cause;
- why existing gates did/did not catch it;
- containment and recovery timeline;
- customer/tenant scope;
- data/action impact;
- corrective source/config/test/operations change;
- whether the issue belongs to B53 or a shared platform owner.

## Reliability targets

S0 does not invent SLA/uptime numbers. Commercial SLA/SLO targets require real production telemetry and contractual product decisions.

Refs #1722 #1723