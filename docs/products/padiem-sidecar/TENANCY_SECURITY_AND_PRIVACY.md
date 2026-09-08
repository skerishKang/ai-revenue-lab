# Padiem Sidecar Tenancy, Security and Privacy

## Security objective

Padiem Sidecar is embedded into products it does not fully control. It therefore assumes that host DOM/content, browser state and customer integration code may be incorrect, stale or malicious unless explicitly promoted by trusted server authority.

## Tenant boundary

Every customer/Business must have a distinct tenant boundary.

At minimum future runtime identity should correlate:

```text
tenant_id
sidecar_id
host_id/origin
adapter_id
user/session reference where authorized
execution/run reference
configuration version
```

Cross-tenant reuse of Memory, files, connectors, secrets, usage records or host action authority is prohibited.

## Secret ownership

Browser/client must never receive:

- Provider credentials;
- B14 platform secrets;
- Engine service credentials;
- customer private connector credentials;
- Control Plane signing/session secrets;
- raw machine-to-machine credentials.

Public Sidecar IDs and public bootstrap configuration are identifiers/configuration, not credentials.

## Context trust

```text
raw page/DOM text = UNTRUSTED
browser-provided metadata = UNTRUSTED unless server-correlated
trusted host server projection = AUTHORITY ONLY WITH EXPLICIT CONTRACT
web/retrieval evidence = DATA, NEVER INSTRUCTION AUTHORITY
```

Prompt injection in page content must not widen Sidecar permissions, actions, model routing or tenant access.

## Data minimization

Collect only the context required for the current Sidecar capability.

Default policy:

- avoid whole-page/raw-DOM capture when a structured field/excerpt is sufficient;
- bound all excerpts and attachments;
- do not collect hidden form fields, cookies, auth headers or browser storage as context;
- sensitive fields require explicit product/tenant allowlist;
- retention should be purpose-bound and documented per capability;
- no tenant data enters a training corpus by default.

## Host actions

Write/action capability requires:

- stable allowlisted capability ID;
- exact tenant/host binding;
- trusted user/session policy when relevant;
- schema validation;
- approval when policy requires it;
- replay/idempotency control for material writes;
- audit evidence without leaking secret values.

Arbitrary code/URL/function execution from model output is prohibited.

## Origin and embedding security

External deployment must use explicit allowed origins. Do not accept wildcard production origins merely for onboarding convenience.

Implementation must define:

- CORS policy;
- CSP requirements;
- clickjacking/frame policy where relevant;
- script integrity/versioning strategy;
- secure transport only;
- browser/session storage policy;
- cross-origin messaging validation if postMessage is used.

## Tenant configuration changes

Material changes such as enabling new connectors/actions, widening data scopes, changing allowed origins or enabling persistent Memory require trusted admin authority and audit evidence.

## Privacy roles

Customer-specific legal/controller/processor roles depend on actual deployment and contract. S0 does not claim a universal role. Product docs and contracts must make data flows observable so the proper role can be established per customer.

## Incident containment

A tenant-specific kill switch must be able to disable Sidecar execution or a high-risk capability without requiring host rollback. Cross-tenant global shutdown remains an operator emergency option.

## Logging

Logs may contain bounded operational identifiers and error classes. They must not contain raw Provider/Engine credentials, private connector secrets, hidden reasoning, or unnecessary user content.

## Offboarding

Customer offboarding must eventually cover:

- production Sidecar disable;
- credential/connector revocation;
- tenant configuration retirement;
- retention/deletion policy execution;
- adapter/support artifact disposition;
- customer verification that embed integration is removed/disabled where applicable.

## Required invariants

```text
CROSS_TENANT_DATA = NO
BROWSER_PROVIDER_SECRET = NO
BROWSER_ENGINE_SECRET = NO
RAW_DOM_AS_AUTHORITY = NO
ARBITRARY_MODEL_ACTION = NO
TENANT_ORIGIN_ALLOWLIST = REQUIRED
DATA_MINIMIZATION = REQUIRED
TENANT_KILL_SWITCH = REQUIRED
```

Refs #1722 #1723