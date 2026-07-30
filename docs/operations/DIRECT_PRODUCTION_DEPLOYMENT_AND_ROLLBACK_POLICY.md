# Direct Production Deployment and Rollback Policy

- Status: portfolio operating policy
- Owner: Web CTO
- Authority: Issue #326
- Intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

## 1. Purpose

This policy keeps AI Revenue Lab deployment aligned with its operating intent: move validated product work into real operation quickly, verify it in the actual environment, and recover immediately when a critical gate fails.

Deployment policy must not turn optional infrastructure into a universal blocker or require repeated owner work.

For Git-connected Cloudflare Pages projects, **merging an approved PR to the configured Production branch is the deployment action**. Operators observe and verify the resulting automatic deployment. They do not create a second deployment manually.

## 2. Default flow

After explicit merge and Production authorization, the default flow is:

```text
validated source
→ exact-head approval
→ approved merge to main
→ Git-connected automatic Production deployment
→ immediate Production smoke and acceptance
→ retain or revert
```

Preview or staging is not a mandatory predecessor to Production.

For a Git-connected project, the following are prohibited unless a separate owner decision explicitly authorizes an exception:

- `wrangler pages deploy` or another direct upload;
- API-created deployment or retry;
- Dashboard deployment retry;
- empty or unrelated commit used only to trigger deployment;
- manual promotion of a Preview deployment.

A queued or failed automatic deployment is a platform/deployment-pipeline state to observe and report. It is not permission to create another deployment path.

## 3. Authorization boundary

Deployment authorization remains separate from UI, UX, backend, and business verdicts.

- `UI_APPROVED` does not automatically authorize merge or Production exposure.
- A merged PR does not automatically prove a UI, UX, backend, or business verdict.
- A successful automatic deployment does not prove product quality, user value, or revenue.
- Once the owner authorizes the accepted PR to merge, the Git-connected automatic Production deployment requires no second deployment approval or manual deployment action.

## 4. Dedicated project rule

Each Business uses its own approved Cloudflare Pages project, Worker, or equivalent target.

Before merge, verify:

- repository;
- Business and workspace;
- project or Worker name;
- root directory;
- Production branch;
- reviewed PR exact head;
- Production hostname;
- Access and authorization boundary when applicable.

A green deployment under an unrelated project is invalid evidence.

## 5. Exact-head and merge contract

When a PR is involved:

- verify the latest `origin/main`;
- verify the PR exact head and changed files;
- require the applicable tests and authoritative CI;
- merge only the reviewed expected head;
- record the resulting exact `main` SHA separately from the reviewed PR head;
- allow the configured Git integration to deploy that resulting `main` SHA automatically;
- do not create empty commits merely to trigger deployment;
- do not create an API, Wrangler, Dashboard, or Preview deployment as a substitute for the Git-connected automatic deployment.

Direct upload or an API-created deployment is permitted only under a separate issue or owner decision that explicitly suspends the Git-connected automatic-deployment rule and explains why.

## 6. Risk levels

### D0 — documentation only

- no runtime deployment work required;
- a documentation merge may still trigger the platform's configured automatic build, but operators do not create or retry it manually;
- validate scope, links, and formatting.

### D1 — static UI, copy, and local assets

- focused source and browser validation;
- exact-head verification;
- automatic Production deployment after merge;
- Production static and responsive smoke;
- revert authority prepared.

### D2 — frontend runtime or read-only API consumer

- deterministic tests;
- browser and network validation;
- API method and schema checks where applicable;
- automatic Production deployment after merge;
- Production smoke;
- revert authority prepared.

### D3 — backend, secrets, cache, authentication, or persistence

- full deterministic and runtime tests;
- secret and authorization boundary verification;
- Production configuration prepared before the merge that should activate it whenever practicable;
- configuration recovery and source revert prepared;
- security and leakage checks;
- controlled failure-path verification where safe.

### D4 — migration, billing, destructive data, or irreversible external action

- separate owner authorization;
- recovery rehearsal;
- Preview or staging may be explicitly required;
- destructive-operation and data-integrity review.

Risk level determines evidence. It does not authorize manual deployment for a Git-connected project.

## 7. Recovery authority

Before an approved merge that can change Production, record the current known-good state:

- current Production deployment or version ID;
- exact deployed source SHA when available;
- active hostname;
- Access or authentication behavior;
- environment-variable, secret, and binding names;
- database or migration state when applicable;
- root and critical-route health.

For source failures, the normal recovery is an expected-head-reviewed **revert PR merged to `main`**, followed by Git-connected automatic deployment of that revert.

Configuration restoration may be performed through the relevant control plane when required, but it must not be confused with creating a new source deployment.

## 8. Automatic Production acceptance

After the Git-connected automatic deployment completes, verify the relevant subset of:

- deployment source SHA and status;
- TLS and hostname validity;
- intended Access or authentication boundary;
- root and critical-route HTTP behavior;
- required static assets;
- API methods, headers, and schemas;
- desktop and mobile critical journeys;
- console, page, CSP, and network failures;
- secret, token, identity, and infrastructure-detail leakage;
- persistence, cache, stale fallback, or destructive behavior.

Do not call a merge "deployed" until the automatic Production deployment is confirmed.

## 9. Failure handling

When the automatic deployment is queued, stuck, or failed before Production changes:

- do not create another deployment;
- do not use Wrangler, API deployment creation, Dashboard retry, or an empty commit;
- report the exact Cloudflare deployment state;
- leave the last known-good Production serving;
- resume verification only after the automatic deployment succeeds.

When a newly deployed source causes a critical Production failure:

- prepare and merge an expected-head-reviewed revert PR;
- allow the Git-connected integration to deploy the revert automatically;
- restore configuration separately when the failed change introduced configuration mutations;
- verify the known-good Production state is restored.

Critical failures include:

- root or critical route unavailable;
- TLS or hostname invalid;
- Access or authentication bypass;
- repeated required API 5xx;
- invalid response schema or materially incorrect facts;
- credential, token, private identity, or secret leakage;
- broken static shell or critical runtime;
- unusable primary desktop or mobile journey;
- data corruption or uncontrolled destructive behavior.

## 10. Optional Preview and staging

Preview or staging is used only for a concrete documented purpose, such as:

- destructive migration rehearsal;
- payment or billing verification;
- high-risk authentication or authorization changes;
- regulated or compliance-sensitive review;
- an external stakeholder who must not access Production;
- an explicit owner request;
- a Business-specific contract explaining why Production-first is unsafe.

Preview secrets, KV bindings, Access applications, branches, and builds are not created by default.

A Preview-only platform defect must not block the normal Git-connected `main` → Production path.

## 11. API, CLI, and owner interaction

API, CLI, and connectors are preferred for **read-only inspection and authorized configuration management**, not for creating an extra deployment on a Git-connected Pages project.

Operators may use them to:

- inspect project configuration and deployment state;
- manage explicitly authorized secrets or bindings;
- verify Access and runtime facts;
- collect sanitized evidence.

Operators must not use them to create, retry, promote, or directly upload a deployment unless a separate explicit exception authorizes it.

Before asking the owner to click a control:

1. verify the action is actually required;
2. inspect the current UI or authoritative API contract;
3. use exact current names;
4. group owner-only actions;
5. never request passwords, OTPs, cookies, private keys, or tokens in chat.

## 12. Evidence

Every Production report should record:

- repository and Business;
- reviewed PR head;
- resulting exact `main` SHA;
- Git-connected project and Production branch;
- automatic deployment ID and status;
- Production URL;
- previous known-good deployment;
- tests and CI;
- Production smoke and acceptance results;
- secret and binding names without values;
- revert required: yes or no;
- final disposition.

Useful dispositions include:

```text
AUTOMATIC_PRODUCTION_DEPLOYMENT_VERIFIED
AUTOMATIC_PRODUCTION_DEPLOYMENT_PENDING
BLOCKED_CLOUDFLARE_PRODUCTION_BUILD_QUEUE
PRODUCTION_REVERT_MERGED_AND_VERIFIED
PREVIEW_OPTIONAL_NOT_USED
```

## 13. Portfolio Console rule

Portfolio Console uses project `ai-revenue-portfolio-console` with Production branch `main`.

Its Preview TLS defect is tracked in Issue #324 and is not a Production blocker.

Portfolio Console operation must:

- merge reviewed source to `main` and allow the Git integration to deploy automatically;
- never use Wrangler direct upload, API deployment creation, Dashboard retry, or Preview promotion without a new explicit owner decision;
- preserve Cloudflare Access;
- manage GitHub App secrets and KV bindings as configuration only;
- verify live API, cache, stale fallback, desktop, mobile, and leakage boundaries after the automatic deployment succeeds;
- use a reviewed revert PR for source rollback.

## 14. Relationship to phase gates

UI, UX, and backend gates define what work is authorized. This policy defines how an authorized merge reaches Production through the existing Git integration and how failures are recovered.

A phase document must not imply that Preview or manual deployment is mandatory unless it links to an explicit exception.
