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

Preview is optional and is not a prerequisite for Production. The hash-based Pages Preview TLS defect tracked in Issue #324 is a platform incident, not a blocker for an authorized automatic-Production path.

### Prohibited for this project

- Wrangler/direct upload;
- API-created deployment or retry;
- Dashboard retry;
- Preview deployment or promotion;
- staging substitute;
- empty trigger commit;
- cancellation or replacement of a Git-triggered deployment.

### When the queue is stuck

```text
BLOCKED_CLOUDFLARE_PRODUCTION_BUILD_QUEUE
AUTOMATIC_MAIN_DEPLOYMENT_PENDING
LAST_KNOWN_GOOD_PRODUCTION_UNCHANGED
NO_MANUAL_DEPLOYMENT_ALLOWED
```

### Before adding Production secrets or bindings

- verify the exact `main` SHA;
- record the current known-good Production deployment and configuration;
- prepare configuration rollback;
- confirm the existing Cloudflare Access boundary.

### Source recovery

For source failure, a reviewed fix or revert PR is merged to `main`. The Git integration deploys the fix or revert automatically. Do not restore a previous state through a manual deployment operation.

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

From the repository root, use the committed test and local-runtime contracts under this workspace. A simple static server can inspect the authority layer, while Pages Functions or Wrangler are required to exercise `/api/github-status`.

Static inspection:

```bash
cd apps/portfolio-console
python -m http.server 4173
```

Open `http://127.0.0.1:4173`.

## Validation

Run the committed tests and validators from `apps/portfolio-console`:

```bash
node tests/test_github_status.mjs
python -m unittest discover -s tests -p "test_*.py"
node tests/validate_projects.js
node --check app.js
node --check github-live-status.js
node --check business-live-facts.js
node --check functions/api/github-status.js
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
- Issue #323 — authorized live Production activation and verification
- Issue #324 — non-blocking Pages hash-Preview TLS platform incident
- Issue #326 — direct Production and rollback operating policy
