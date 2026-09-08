# Padiem Sidecar Customer Onboarding

## Goal

Turn a customer/Business from "we want AI on this site" into a bounded, supportable Sidecar integration without rediscovering platform ownership on every engagement.

## Intake

Collect only information needed to define the integration:

```text
organization / Business
host product/site
approved host origins
target users
primary user journeys
languages
knowledge/data sources
required current-page context
required read capabilities
requested host actions
identity/login context
privacy/retention constraints
brand/theme requirements
support/contact owner
target environment and launch boundary
```

Do not request Provider API keys for B53 integration when B14/platform execution is the intended path.

## Discovery output

Create a short integration brief:

- product promise on this host;
- top 3–5 user journeys;
- adapter-owned domain semantics;
- generic Sidecar capabilities reused;
- data/context allowlist;
- action/tool allowlist;
- identity/tenant boundary;
- implementation mode;
- unresolved blockers;
- preview/production acceptance plan.

## Capability classification

Every request is classified before implementation:

```text
B53_PRODUCT
IP_SIDECAR
IP_ENGINE
IP_CORE
B14
CONTROL_PLANE
PRODUCT_ADAPTER_ONLY
DO_NOT_SHARE
```

If a generic capability is missing, route it to the owning platform component rather than implement a customer-specific fork.

## Integration modes

### First-party Padiem Business

May use monorepo/shared Service Binding/platform integrations where authorized. Still requires adapter and tenant/product boundary.

### External web customer

Uses customer-safe public embed/bootstrap and server integration contracts. No internal machine credentials are exposed to the browser.

### Enterprise/private integration

May require SSO, private connectors, regional/private deployment or custom adapter work. These requirements are separately scoped and do not change generic ownership rules.

## Preview gate

Before Production, prove:

- host primary journey remains intact;
- exact origin/tenant binding;
- correct adapter/domain behavior;
- context minimization;
- expected answer/evidence behavior;
- error/retry/disabled state;
- action confirmation/authorization where applicable;
- mobile/accessibility baseline;
- exact runtime/adapter/config versions;
- rollback/disable procedure.

## Production activation

Production requires explicit approval of the exact integration tuple and configuration. Installation alone is not activation authority.

## Customer handoff

Provide:

- install/config documentation;
- current version and supported integration contract;
- customer admin/operator instructions;
- kill/disable escalation path;
- known limitations;
- change request process;
- support/incident contact lane;
- usage/billing presentation boundary when applicable.

## Ongoing change requests

Changes to origins, data scopes, actions, connectors or identity policy are treated as material configuration changes and receive review/QA before production widening.

## Offboarding

Define who disables/removes the embed, who revokes connectors/credentials, what retained data is deleted/retained under policy, and what evidence remains for operational/audit needs.

## First pilot selection

Prefer an initial external pilot with:

- bounded public/low-sensitivity context;
- clear existing website/product;
- one or two high-value journeys;
- no irreversible host writes in the first slice;
- responsive customer technical owner;
- measurable user/support value.

Refs #1722 #1723