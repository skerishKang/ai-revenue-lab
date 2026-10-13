# Git-Connected Automatic Production and Recovery Policy

- Status: portfolio operating policy
- Owner: Web CTO
- Authority: Issue #326
- Intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

## 1. Purpose

This policy keeps AI Revenue Lab deployment aligned with its operating intent: move validated product work into real operation quickly, verify it in the actual environment, and recover through reviewed source changes when a critical gate fails.

Deployment policy must not turn unapproved infrastructure into a blocker or require repeated owner work.

For Git-connected Cloudflare Pages projects, **merging an approved PR to the configured Production branch is the deployment action**. Operators observe and verify the resulting automatic deployment. They do not create a second deployment manually.

## 2. Default flow

After explicit merge and Production authorization, the default flow is:

```text
validated source
→ exact-head approval
→ approved merge to main
→ Git-connected automatic Production deployment
→ immediate Production smoke and acceptance
→ retain or merge a reviewed fix/revert PR
```

Preview and staging are disabled by default.

For a Git-connected project, the following are prohibited unless a new explicit owner decision authorizes the exact exception:

- `wrangler pages deploy` or another direct upload;
- API-created deployment or retry;
- Dashboard deployment retry;
- empty or unrelated commit used only to trigger deployment;
- Preview creation, deployment, or promotion;
- staging-project substitution;
- cancellation and replacement of a Git-triggered deployment.

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
- do not create an API, Wrangler, Dashboard, Preview, or staging deployment as a substitute for the Git-connected automatic deployment.

Direct upload, API-created deployment, Preview, or staging is permitted only when a **new explicit owner decision** suspends the Git-connected automatic-deployment rule for the exact named operation and explains why. Opening or editing an issue does not create that authority by itself.

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
- last known-good Production source recorded.

### D2 — frontend runtime or read-only API consumer

- deterministic tests;
- browser and network validation;
- API method and schema checks where applicable;
- automatic Production deployment after merge;
- Production smoke;
- last known-good Production source recorded.

### D3 — backend, secrets, cache, authentication, or persistence

- **full relevant coverage of the changed high-risk boundary**, not an automatic whole-repository or whole-product suite;
- focused deterministic/runtime regression for the changed behavior plus the configured CI that protects affected dependencies;
- broader runtime suites only when the change crosses those broader surfaces;
- secret and authorization boundary verification when those boundaries are actually touched;
- Production configuration prepared before the merge that should activate it whenever practicable;
- exact configuration restoration steps and reviewed source fix/revert path prepared;
- security and leakage checks;
- controlled failure-path verification where safe.

### D4 — migration, billing, destructive data, or irreversible external action

- separate owner authorization;
- recovery rehearsal;
- Preview or staging only when a new explicit owner decision or an already approved Business-specific contract requires it;
- destructive-operation and data-integrity review.

Risk level determines evidence. It does not authorize Preview, staging, or manual deployment for a Git-connected project.

## 7. Recovery evidence

Before an approved merge that can change Production, record the current known-good state:

- current Production deployment or version ID;
- exact deployed source SHA when available;
- active hostname;
- Access or authentication behavior;
- environment-variable, secret, and binding names;
- database or migration state when applicable;
- root and critical-route health.

For source failures, the normal recovery is an expected-head-reviewed **fix or revert PR merged to `main`**, followed by Git-connected automatic deployment.

Configuration restoration may be performed through the relevant control plane when configuration itself caused the failure, but it must not create, retry, promote, or replace a source deployment.

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
- do not use Wrangler, API deployment creation, Dashboard retry, Preview, staging, or an empty commit;
- do not cancel and replace the Git-triggered deployment;
- report the exact Cloudflare deployment state;
- leave the last known-good Production serving;
- resume verification only after the automatic deployment succeeds.

When a newly deployed source causes a critical Production failure:

- prepare and merge an expected-head-reviewed fix or revert PR;
- allow the Git-connected integration to deploy it automatically;
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

## 10. Preview and staging are disabled by default

Preview or staging is not an operator option. It may be introduced only by:

1. a new explicit owner decision authorizing the exact named exception; or
2. an already approved Business-specific contract that explicitly requires it.

Examples that may justify an owner decision include:

- destructive migration rehearsal;
- payment or billing verification;
- high-risk authentication or authorization changes;
- regulated or compliance-sensitive review;
- an external stakeholder who must not access Production.

An operator may not create Preview authority merely by documenting a purpose, opening an issue, or encountering a stuck automatic deployment.

Without explicit authority, do not create Preview secrets, KV bindings, Access applications, branches, builds, deployments, URLs, or evidence packages.

A Preview-only platform defect must not block the normal Git-connected `main` → Production path.

## 11. API, CLI, and owner interaction

API, CLI, and connectors are preferred for **read-only inspection and authorized configuration management**, not for creating an extra deployment on a Git-connected Pages project.

Operators may use them to:

- inspect project configuration and deployment state;
- manage explicitly authorized secrets or bindings;
- verify Access and runtime facts;
- collect sanitized evidence.

Operators must not use them to create, retry, promote, or directly upload a deployment. Only a new explicit owner decision may authorize the exact exception.

Before asking the owner to click a control:

1. verify the action is actually required;
2. inspect the current UI or authoritative API contract;
3. use exact current names;
4. group owner-only actions;
5. never request passwords, OTPs, cookies, private keys, or tokens in chat.

Never ask the owner to choose an alternate deployment mechanism when the Git-triggered automatic deployment is queued, stuck, or failed.

## 12. Evidence

Every Production report should record:

- repository and Business;
- reviewed PR head;
- resulting exact `main` SHA;
- Git-connected project and Production branch;
- automatic deployment ID and status;
- Production URL;
- previous known-good Production source and configuration;
- tests and CI;
- Production smoke and acceptance results;
- secret and binding names without values;
- fix/revert PR required: yes or no;
- final disposition.

Useful dispositions include:

```text
AUTOMATIC_PRODUCTION_DEPLOYMENT_VERIFIED
AUTOMATIC_PRODUCTION_DEPLOYMENT_PENDING
BLOCKED_CLOUDFLARE_PRODUCTION_BUILD_QUEUE
PRODUCTION_FIX_OR_REVERT_MERGED_AND_VERIFIED
PREVIEW_DISABLED_NOT_USED
```

## 13. Portfolio Console rule

Portfolio Console uses project `ai-revenue-portfolio-console` with Production branch `main`.

Its Preview TLS defect is tracked in Issue #324 as historical platform evidence and grants no Preview authority.

Portfolio Console operation must:

- merge reviewed source to `main` and allow the Git integration to deploy automatically;
- never use Wrangler direct upload, API deployment creation, Dashboard retry, Preview, or staging without a new explicit owner decision;
- preserve Cloudflare Access;
- manage GitHub App secrets and KV bindings as configuration only;
- verify live API, cache, stale fallback, desktop, mobile, and leakage boundaries after the automatic deployment succeeds;
- use a reviewed fix or revert PR for source recovery.

## 14. Relationship to phase gates

UI, UX, and backend gates define what work is authorized. This policy defines how an authorized merge reaches Production through the existing Git integration and how failures are recovered.

A phase document must not imply that Preview, staging, or manual deployment is available unless it links to a new explicit owner decision or an already approved Business-specific exception.

## 15. PADIEM B62 Worker — single-owner protected manual release (owner decision 2026-10-13)

**Scope:** `skerishKang/ai-revenue-lab` / B62 `padiem-chat` production **Worker code deployment**, tracked in [#4522](https://github.com/skerishKang/ai-revenue-lab/issues/4522) and [#4549](https://github.com/skerishKang/ai-revenue-lab/issues/4549). This is a **product-specific, existing GitHub Actions manual deployment contract**, not a change to §1–14's Git-connected **Pages** automatic deployment policy, nor authorization to deploy B14, B54, Engine or any other Worker.

The owner has confirmed that this repository is operated predominantly by one person. **A second account owned and controlled by that same person is not an independent human reviewer.** An unconfigured GitHub `production` Required Reviewer rule (`required_reviewers=0`) is **not, by itself, a release blocker** and the owner must not be asked to invent a second GitHub identity. Older #4522 commentary stating independent required reviewers are mandatory for this specific rollout is superseded by this dated owner decision. **Do not delete the `production` environment, disable or bypass an actual existing protection, add collaborators, change repo settings, or claim a review gate was satisfied.** If GitHub enforces a protection at execution, satisfy it legitimately or stop; this policy is not a technical bypass.

### Mandatory substitute controls — fail closed

1. **Authority and scope:** Record named owner permission, scope and release window; CENTRAL owns exact-head review and execution; local agents do not deploy, and source PR merge alone is not production approval. Preserve all existing authentication, model, D1 and customer-entitlement feature holds.
2. **Revision and checks:** Require reviewed source merged to current `main`, relevant required exact-HEAD CI and GitGuardian success, plus no conflicting deployment; re-check exact `main` SHA before any write. Do not infer readiness from historical CI or source green alone.
3. **Nonmutating preflight first:** Use existing `.github/workflows/b62-production-code-deploy-gate.yml` `repository_preflight` and `cloudflare_readonly` modes on exact current `main`, with the existing canonical Worker, hostname, binding and secret authority checks. Require D1 migration **008 and 040 both EXACT**, same Worker-bound `PADIEM_CHAT_DB`, recovery capability, current served/version topology, valid scoped credentials, and no unverified identity/config drift. **Migration 040 was already applied/read back EXACT; do not apply it again.**
4. **Rollback and configuration:** Record the latest verified 100%-served old Worker version and available rollback path; preserve actual D1, R2, service, environment-variable and secret bindings. Do not log token/secret values or create a replacement credentials workflow. Unknown/ambiguous responses block mutation.
5. **Single controlled deployment:** Only if all checks pass, use the existing explicit, bounded `workflow_dispatch` `deploy_production_code` path with exact `target_sha` and its established confirmation string. Keep the existing GitHub `production` environment reference; do not weaken its technical safeguards. No implicit deploy on arbitrary merge, parallel deployment, fallback upload, or ad-hoc `wrangler` command.
6. **Independent evidence from the running service:** Require exact newly served version readback, health and previous-binding parity, and authenticated owner P01 status/approval/SSE journey with bounded Chat/Claw/Calendar acceptance where relevant. A successful workflow/merge is not equal to a verified live customer session; on failure use the existing bounded rollback/recovery contract, no blind retries.

`RELEASE_AUTHORITY=SINGLE_OWNER` · `SECOND_PERSONAL_ACCOUNT_REQUIRED=NO` · `EXISTING_GITHUB_PROTECTIONS_BYPASSED=NO` · `D1_040_REAPPLY=NO` · `PRODUCTION_MUTATION_BEFORE_PREFLIGHT=NO`.

**Technical exception:** The file `b62-current-main-production-deploy-trigger.yml` has a separate path-scoped `push` trigger when **that workflow file itself** is changed. Do not edit/merge it as a casual documentation change; review its deployment-dispatch effect separately. This policy amendment does not modify either deployment workflow.

**Evidence state at adoption:** D1 040 exact was independently proven via #4522's prior runs; **new B62 Worker serving status and authenticated owner P01 E2E remain unverified**. This governance decision changes who approves, not what has been deployed.
