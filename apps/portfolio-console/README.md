# AI Revenue Lab Portfolio Console

Private owner and operator control tower for AI Revenue Lab.

Portfolio Console is not the user-facing `apps/portal/` product and not merely a Business-number directory. Its purpose is to reduce the work required to operate a growing portfolio by combining deliberate Business authority with automatically synchronized operational facts.

The Console should let the owner answer quickly:

- What Businesses exist and what does each one promise?
- What is deployed and reachable?
- What is being built or reviewed now?
- Which Issue, PR, exact SHA, CI result, and phase verdict are authoritative?
- What is blocked?
- What should happen next?
- Which products are producing cost, engagement, and revenue evidence?

Canonical intent:

- `../../docs/portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

## Product boundary

Portfolio Console is an internal operational surface.

The user-facing Portal will own shared account, service catalog, and launch behavior. Portfolio Console owns non-secret portfolio oversight and links to independently operated Business surfaces and evidence.

The Console must not become a cross-product private-data dashboard or a universal product administrator.

## Data model

The Console separates two classes of information.

### Deliberate authority

Changed only through reviewed source or explicit human verdicts:

- Business number and stable identity;
- Korean and English product names;
- product boundary and authority classification;
- portfolio priority;
- UI, UX, backend, deployment, and business verdicts.

### Automatically synchronized facts

Read from approved read-only sources and refreshed without manual registry edits:

- repository and default branch;
- latest default-branch SHA and commit;
- Issue title, state, state reason, and update time;
- current or discovered PR, Draft state, merge state, head/base SHA, and update time;
- CI and check rollup;
- open Issue and PR counts where useful;
- synchronization time, stale state, and normalized source errors.

GitHub facts must not be used to invent product completion, priority, or phase approval. Automation supplies facts; humans retain judgment.

## Current source capabilities

The merged source foundation supports:

- static Business identity and authority through Business 55;
- search, lifecycle and phase filtering, sorting, details, and next-action surfaces;
- bounded server-side GitHub GraphQL aggregation;
- automatic PR discovery through structured markers, Issue references, related references, and conservative conventions;
- machine-readable human verdict parsing;
- conflict and truncation handling that refuses to guess;
- schema version 2 API responses;
- server-side cache with stale last-good fallback;
- immediate static rendering when live facts are unavailable;
- safe credential-free failure behavior;
- responsive desktop and mobile operation;
- Korean default and English secondary interface.

The current implementation must remain useful without configured credentials. Live GitHub facts are additive, not a dependency for rendering the Business authority layer.

## Runtime architecture

```text
browser
  → Cloudflare Access
  → Portfolio Console static UI
  → GET /api/github-status
  → Pages Function
  → read-only GitHub App installation
  → bounded cache and last-good snapshot
```

Credentials remain server-side. The browser must never receive:

- GitHub App private key;
- GitHub App JWT or installation token;
- Cloudflare token, account ID, or KV namespace ID;
- Access cookie or user identity diagnostic;
- local paths or raw upstream errors.

Repository access is allowlisted. Browser query parameters must not select arbitrary repositories.

## Deployment policy

For `ai-revenue-portfolio-console`, merging an approved PR to `main` is the deployment action. Cloudflare's existing Git connection automatically creates the Production deployment. Operators only observe and verify it.

Project:

```text
ai-revenue-portfolio-console
```

Production branch:

```text
main
```

Preview and staging are disabled for this project. They may be introduced only by a new explicit owner decision. Issue #324 records a historical Pages Preview TLS incident and does not authorize new Preview work.

### Prohibited for this project

- Wrangler/direct upload;
- API-created deployment or retry;
- Dashboard retry;
- Preview creation, deployment, or promotion;
- staging substitute;
- empty trigger commit;
- cancellation or replacement of a Git-triggered deployment;
- asking the owner to choose an alternate deployment mechanism.

### When the queue is stuck

```text
BLOCKED_CLOUDFLARE_PRODUCTION_BUILD_QUEUE
AUTOMATIC_MAIN_DEPLOYMENT_PENDING
LAST_KNOWN_GOOD_PRODUCTION_UNCHANGED
NO_MANUAL_DEPLOYMENT_ALLOWED
```

The operator stops after recording this state. A stuck queue does not authorize another deployment path.

### Before adding Production secrets or bindings

- verify the exact `main` SHA;
- record the current Production source and configuration as recovery evidence;
- prepare exact configuration restoration steps when configuration changes are authorized;
- confirm the existing Cloudflare Access boundary.

### Source recovery

For source failure, a reviewed fix or revert PR is merged to `main`. The Git integration deploys the fix or revert automatically. Do not restore a previous source state through a manual deployment operation.

Configuration restoration is permitted only when configuration itself caused the failure; it must not create, retry, promote, or replace a source deployment.

## Security boundary

- Use a repository-scoped, read-only GitHub App.
- Store credentials only as encrypted Cloudflare secrets.
- Keep the project behind Cloudflare Access or an equivalent private access gate.
- Do not add long-lived personal access tokens to the browser, repository, fixtures, screenshots, or logs.
- Do not add credentials, private hostnames, user data, database URLs, or unaudited deployment claims to static authority files.
- Normalize upstream errors and preserve the static Console when synchronization fails.

The included `_headers` file restricts caching, framing, forms, external connections, and permission-gated browser capabilities.

## Operating rule

Volatile GitHub facts must not be maintained by repeatedly editing static Business records or asking an operator to re-audit every Business.

A model should update deliberate authority only when a product or human verdict changes. Issue, PR, SHA, CI, and synchronization facts should update automatically after the cache TTL.

The Console is successful when it reduces manual checking and shortens the time from verified portfolio fact to owner decision.

## Run locally

From the repository root, use the committed test and local-runtime contracts under this workspace. A simple static server can inspect the authority layer, while Pages Functions or Wrangler are required to exercise `/api/github-status` locally. Local Wrangler use does not authorize a Production upload.

Static inspection:

```bash
cd apps/portfolio-console
python -m http.server 4173
```

Open `http://127.0.0.1:4173`.

## GitHub live sync diagnostic contract

The `/api/github-status` endpoint returns a safe, generalized `error.code` for public consumption (e.g. `UPSTREAM_UNAVAILABLE`, `UPSTREAM_RATE_LIMITED`, `CONFIGURATION_MISSING`).

When a failure occurs, the response MAY include an additional `error.diagnosticCode` field and a matching `X-Portfolio-Diagnostic-Code` response header. This is a fixed, limited enum — never a raw upstream error, secret, or response body.

### Allowed diagnostic codes

```
CONFIGURATION_MISSING
CACHE_CONFIGURATION_MISSING
CRYPTO_UNAVAILABLE
PRIVATE_KEY_INVALID
JWT_SIGNING_FAILED
INSTALLATION_TOKEN_EXCHANGE_FAILED
INSTALLATION_TOKEN_RESPONSE_INVALID
GITHUB_GRAPHQL_AUTH_FAILED
GITHUB_GRAPHQL_RATE_LIMITED
GITHUB_GRAPHQL_REQUEST_FAILED
GITHUB_GRAPHQL_RESPONSE_INVALID
GITHUB_GRAPHQL_DATA_UNAVAILABLE
CACHE_READ_FAILED
UNKNOWN_INTERNAL
```

### Rules

- Public `error.code` continues to be safely normalized — do not rely on `diagnosticCode` for client logic.
- `diagnosticCode` is an **internal operator aid** for distinguishing authentication-failure stages without exposing secrets or generating new App keys.
- The `diagnosticCode` is never a raw upstream message, HTTP response body, JWT, token, App/installation ID, or private key.
- If a Git-connected automatic deployment fails, **do not work around it with a manual deployment** — fix the source PR and let the automatic deployment retry.

## Function contract marker

Every `/api/github-status` response includes:

```text
X-Portfolio-Function-Contract: github-status-diagnostics-v1
```

This is a fixed literal identifying the deployed Pages Functions bundle contract family.

- It is not a commit SHA, deployment ID, or secret.
- It does not indicate GitHub sync success, credential health, or Business record completeness.
- It does not indicate Production acceptance passage.
- It exists to confirm which Functions contract a live deployment is serving after a Git-connected automatic deployment.
- It must not be used as justification for manual deployment, retry, or Preview promotion.

## Validation

```bash
cd apps/portfolio-console

# Syntax checks
node --check functions/api/github-status.js
node --check functions/_lib/github-app-auth.js
node --check functions/_lib/github-client.js
node --check functions/_lib/github-status-service.js
node --check functions/_lib/response.js
node --check functions/_lib/cache.js
node --check functions/_lib/business-fact-merger.js
node --check functions/_lib/business-github-map.js
node --check functions/_lib/business-github-query.js
node --check functions/_lib/business-pr-discovery.js
node --check functions/_lib/business-verdict-parser.js
node --check businesses.js
node --check app.js
node --check github-live-status.js
node --check business-live-facts.js

# Unit tests (Node)
node tests/test_github_status.mjs

# Unit tests (Python)
python3 -m unittest discover -s tests -p "test_*.py" -v

# Validators
node tests/validate_projects.js
node --input-type=module -e "import('./tests/test_github_ui.mjs')"

# Whitespace check
git diff --check
```

Required behavioral boundaries include:

- exactly 55 Business authority records;
- no duplicate Business numbers;
- PR merge does not imply UI approval;
- missing or conflicting verdicts remain unverified or conflicted;
- ambiguous or truncated discovery does not guess;
- static rendering survives missing credentials and GitHub failure;
- API responses contain no secrets or private infrastructure details;
- desktop and mobile have no critical overflow, console, page, CSP, or required-asset failures.

## Related authority

- Issue #137 — actionable owner dashboard direction
- Issue #163 — live read-only GitHub status architecture
- Issue #285 — automatic Business Issue, PR, CI, and phase mapping
- PR #296 — merged Business 1–55 mapping and discovery foundation
- Issue #323 — automatic Production deployment observation and live verification only
- Issue #324 — historical Pages Preview TLS platform incident; no Preview authority
- Issue #326 — Git-connected automatic Production and reviewed fix/revert operating policy
- Issue #329 — removal of manual-deployment and Preview ambiguity