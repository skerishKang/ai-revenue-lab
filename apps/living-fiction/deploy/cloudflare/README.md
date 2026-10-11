# Living Fiction — Cloudflare migration M0

Issue: #2223

This directory replaces the old assumption that B03 must be restored on Modal. It is a **source-only migration adapter** for moving the existing Living Fiction FastAPI application to Cloudflare while preserving Neon PostgreSQL and the existing private reader/admin security boundary.

## Current target decision

The current production dependency path uses `psycopg[binary]` and `psycopg_pool`. Cloudflare Python Workers run on Pyodide and should not be treated as compatible with this native libpq-based path without an actual compatibility proof.

Therefore the accepted M0 direction is:

```text
PRIMARY_MIGRATION_TARGET = CLOUDFLARE_CONTAINER
DATABASE = EXISTING_NEON_POSTGRESQL
MODAL = ROLLBACK_ONLY_UNTIL_PARITY
PYTHON_WORKER = REFERENCE / FUTURE_IF_DEPENDENCY_COMPATIBLE
```

Primary path:

```text
Browser
→ Cloudflare Worker
→ Cloudflare Container
→ canonical FastAPI app.main:app / create_app()
→ existing psycopg PostgreSQL adapter
→ existing Neon PostgreSQL
```

Reference/future path only if the complete dependency set is proven compatible:

```text
Browser
→ Cloudflare Python Worker / FastAPI ASGI
→ Hyperdrive
→ existing Neon PostgreSQL
```

Do not rewrite the product into JavaScript merely to remove Modal. Do not move Neon data to D1 as part of this migration.

## M0 source adapters

### Container path — current primary

`Dockerfile.cloudflare`:

- uses Python 3.13 Linux runtime;
- installs the existing package with the existing PostgreSQL extra;
- starts `uvicorn app.main:app`;
- does not fork application routes or business logic.

`.dockerignore`:

- excludes `.env*` except the non-secret `.env.example`;
- excludes local DB/runtime state (`var`, `*.db`, `*.sqlite*`);
- excludes `node_modules`, Wrangler artifacts, test caches and Python bytecode;
- prevents CI tooling and local state from inflating or contaminating the deployment image.

`deploy/cloudflare/container_worker.js`:

- uses `@cloudflare/containers`;
- routes requests to one bounded Living Fiction container instance for parity testing;
- injects only server-owned `LF_*` runtime bindings;
- never injects `LF_MIGRATION_DATABASE_URL`;
- keeps `MockProvider` during hosting migration.

`wrangler.cloudflare-container.toml`:

- declares the Container, Durable Object binding and SQLite-backed class migration required by current Cloudflare Containers;
- contains no secret values, account IDs, deployment IDs or guessed Production hostname;
- authorizes no deployment by itself.

### Python Worker path — reference only

`deploy/cloudflare/worker.py` reuses `app.factory.create_app()` through Cloudflare ASGI and shows how trusted Worker bindings would project into the existing `LF_*` seam. `deploy/cloudflare/wrangler.toml` is explicitly reference-only and intentionally omits Hyperdrive IDs and secret values.

Do **not** claim `PYTHON_WORKER_COMPATIBLE` until an actual current Workers dependency/build/runtime probe proves the complete PostgreSQL path.

## Required trusted bindings before a later Container Preview deployment

Names only; no values belong in this repository:

```text
LF_DATABASE_URL
LF_ADMIN_SECRET
LF_CREDENTIAL_HMAC_KEY
LF_SESSION_HMAC_KEY
LF_ALLOWED_ORIGINS
```

`LF_DATABASE_URL` must be the existing Neon runtime-role connection URL. The owner/migration-role URL remains operator-only and absent from the serving runtime.

`LF_ALLOWED_ORIGINS` must be the exact authorized Cloudflare application origin selected by a later deployment gate. Do not guess a hostname in source.

## M0 CI gate

`.github/workflows/b03-living-fiction-cloudflare-m0-ci.yml` performs only non-deploy validation:

1. Cloudflare migration source-contract tests, including build-context secret/runtime-state exclusions;
2. Python syntax compilation;
3. actual `Dockerfile.cloudflare` image build;
4. current Wrangler + `@cloudflare/containers` install;
5. `wrangler deploy --dry-run` for Worker/Container config and bundle validation;
6. diff whitespace validation.

No Cloudflare credentials are supplied and no remote resource is created.

## Preserved invariants

```text
CANONICAL_CREATE_APP_REUSED = YES
PRODUCT_ROUTE_FORK = NO
PRIVATE_INVITE_READER_BOUNDARY = PRESERVE
ADMIN_REVIEW_BOUNDARY = PRESERVE
POSTGRES_SCHEMA = PRESERVE
NEON_DATA = PRESERVE
MIGRATIONS_AT_RUNTIME_STARTUP = NO
MIGRATION_ROLE_IN_SERVING_RUNTIME = NO
AI_PROVIDER_ACTIVATION = NO
MODAL_RETIREMENT_BEFORE_PARITY = NO
PRODUCTION_DEPLOYMENT_BY_M0 = NO
```

## Next gate after this PR

1. Require exact-head M0 CI GREEN.
2. Use an explicitly authorized Cloudflare Preview deployment with server-side secrets only.
3. Verify `/health`, `/access`, reader/admin auth, invite flow, database persistence, restart behavior, noindex/security headers and fail-closed errors with synthetic/owner-controlled data.
4. Confirm rollback to the existing Modal deployment remains available during parity testing.
5. Only after Cloudflare live parity, select the canonical Cloudflare URL and retire Modal separately.

Modal remains a rollback anchor until those gates pass.
