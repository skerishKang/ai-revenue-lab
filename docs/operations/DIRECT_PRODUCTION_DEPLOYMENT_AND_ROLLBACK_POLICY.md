# Direct Production Deployment and Rollback Policy

- Status: portfolio operating policy
- Owner: Web CTO
- Authority: Issue #326
- Intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

## 1. Purpose

This policy keeps AI Revenue Lab deployment aligned with its operating intent: move validated product work into real operation quickly, verify it in the actual environment, and recover immediately when a critical gate fails.

Deployment policy must not turn optional infrastructure into a universal blocker or require repeated owner work that authenticated automation can perform.

## 2. Default flow

After explicit deployment authorization, the default flow is:

```text
validated source
→ exact-head approval
→ approved merge to main
→ dedicated Production deployment
→ immediate Production smoke and acceptance
→ retain or rollback
```

Preview or staging is not a mandatory predecessor to Production.

## 3. Authorization boundary

Deployment authorization remains separate from UI, UX, backend, and business verdicts.

- `UI_APPROVED` does not automatically authorize merge or deployment.
- A merged PR does not automatically prove a UI, UX, backend, or business verdict.
- A successful deployment does not prove product quality, user value, or revenue.
- Once the owner explicitly authorizes deployment for the accepted scope, operators should proceed through the documented gates without repeated minor approval questions.

## 4. Dedicated project rule

Each Business uses its own approved Cloudflare Pages project, Worker, or equivalent deployment target.

Before deployment, verify:

- repository;
- Business and workspace;
- project or Worker name;
- root directory;
- Production branch;
- exact source SHA;
- domain or service hostname;
- Access and authorization boundary when applicable.

A green deployment under an unrelated project is invalid evidence.

## 5. Exact-head and merge contract

When a PR is involved:

- verify the latest `origin/main`;
- verify the PR exact head and changed files;
- require the applicable tests and authoritative CI;
- merge only the reviewed expected head;
- deploy the resulting exact `main` SHA;
- do not create empty commits merely to trigger deployment;
- do not silently deploy older reviewed bytes after `main` has changed.

Direct upload is permitted only when explicitly authorized and the deployed bytes are tied to an exact source SHA.

## 6. Risk levels

### D0 — documentation only

- no deployment required;
- validate scope, links, and formatting.

### D1 — static UI, copy, and local assets

- focused source and browser validation;
- exact-head verification;
- Production static and responsive smoke;
- known-good rollback deployment recorded.

### D2 — frontend runtime or read-only API consumer

- deterministic tests;
- browser and network validation;
- API method and schema checks where applicable;
- Production smoke;
- deployment rollback prepared.

### D3 — backend, secrets, cache, authentication, or persistence

- full deterministic and runtime tests;
- secret and authorization boundary verification;
- deployment and configuration rollback prepared;
- security and leakage checks;
- controlled failure-path verification where safe.

### D4 — migration, billing, destructive data, or irreversible external action

- separate owner authorization;
- recovery or rollback rehearsal;
- Preview or staging may be explicitly required;
- destructive-operation and data-integrity review.

Risk level determines the evidence required. It does not automatically require Preview for D0–D3.

## 7. Production rollback authority

Before changing Production, record the current known-good state:

- deployment or version ID;
- exact source SHA when available;
- active hostname;
- Access or authentication behavior;
- environment variable and secret names;
- binding names;
- database or migration state when applicable;
- root and critical-route health.

This record is the rollback authority.

Do not add new Production secrets, bindings, migrations, or destructive behavior without knowing how to restore or remove them.

## 8. Immediate Production acceptance

After deployment, verify the relevant subset of:

- TLS and hostname validity;
- intended Access or authentication boundary;
- root and critical-route HTTP behavior;
- exact deployed source or asset identity;
- required static assets;
- API methods, headers, and schemas;
- desktop and mobile critical journeys;
- console, page, CSP, and network failures;
- secret, token, identity, and infrastructure-detail leakage;
- persistence, cache, stale fallback, or destructive behavior.

Production acceptance should begin immediately after the deployment completes.

## 9. Mandatory rollback triggers

Rollback immediately when a critical failure occurs, including:

- root or critical route unavailable;
- TLS or hostname invalid;
- Access or authentication bypass;
- authorized users locked out of a critical path without a safe recovery;
- repeated required API 5xx;
- invalid response schema or materially incorrect facts;
- credential, token, private identity, or secret leakage;
- broken static shell or critical runtime;
- unusable primary desktop or mobile journey;
- data corruption or uncontrolled destructive behavior.

Do not wait for a new owner approval to execute a prepared rollback for a critical failure.

Rollback must restore the prior known-good deployment and remove or restore newly introduced failed configuration.

## 10. Optional Preview and staging

Preview or staging is used only when it serves a concrete purpose, such as:

- destructive migration rehearsal;
- payment or billing verification;
- high-risk authentication or authorization changes;
- regulated or compliance-sensitive review;
- an external stakeholder who must not access Production;
- an explicit owner request;
- a Business-specific contract that documents why Production-first is unsafe.

Preview secrets, KV bindings, Access applications, branches, and automatic builds should not be created by default.

A Preview-only platform defect should be recorded and escalated separately. It must not block an authorized Production deployment when the source is validated and a safe rollback path exists.

## 11. API and CLI first

Operators must prefer authenticated connectors, API, or CLI automation over repeated owner Dashboard work.

Before asking the owner to click a control:

1. verify that the scoped API or connector cannot perform the operation;
2. inspect the actual current UI or authoritative API contract;
3. use the exact current permission, menu, and button names;
4. group owner-only actions into one bounded request;
5. never request passwords, OTPs, cookies, private keys, or tokens in chat.

Short-lived, least-privilege tokens are preferred. Secret values must not be echoed, logged, committed, or included in evidence.

## 12. Automatic deployment behavior

A Git-connected platform may automatically deploy after a merge or push to `main`.

This technical behavior does not create authorization. The merge and deployment must already be approved for the relevant scope.

Once approved, direct `main` to Production deployment is the normal behavior and should not be artificially delayed by an optional Preview gate.

## 13. Evidence

Every Production deployment report should record:

- repository and Business;
- exact `main` SHA;
- project or Worker name;
- Production URL;
- previous and new deployment IDs;
- rollback authority;
- tests and CI;
- smoke and acceptance results;
- secret and binding names without values;
- rollback required: yes or no;
- final disposition.

Useful dispositions include:

```text
PRODUCTION_DEPLOYMENT_VERIFIED
PRODUCTION_DEPLOYMENT_ROLLED_BACK
PRODUCTION_ACTIVATION_BLOCKED_<reason>
PREVIEW_OPTIONAL_NOT_USED
PREVIEW_REQUIRED_<documented reason>
```

## 14. Portfolio Console rule

Portfolio Console uses project `ai-revenue-portfolio-console` with Production branch `main`.

Its hash-based Pages Preview TLS defect is tracked in Issue #324. That defect is not a Production blocker.

Portfolio Console Production activation must:

- use the validated exact `main` SHA;
- preserve Cloudflare Access;
- add GitHub App secrets and KV bindings only through authorized activation work;
- verify live API, cache, stale fallback, desktop, mobile, and leakage boundaries in Production;
- roll back deployment and configuration on critical failure.

## 15. Relationship to phase gates

UI, UX, and backend gates define what work is authorized. This policy defines how an authorized deployment is executed and recovered.

A phase document must not imply that Preview is mandatory unless it links to an explicit D4 or Business-specific exception.
