# Living Fiction — Cloudflare migration M0

Issue: #2223

This directory replaces the old assumption that B03 must be restored on Modal. It is a **source-only compatibility adapter** for moving the existing Living Fiction FastAPI application to Cloudflare while preserving Neon PostgreSQL and the existing private reader/admin security boundary.

## Target

Preferred path, only after compatibility proof:

```text
Browser
→ Cloudflare Python Worker
→ canonical FastAPI create_app()
→ Hyperdrive
→ existing Neon PostgreSQL
```

Fallback if the native PostgreSQL dependency cannot run safely in Python Workers:

```text
Browser
→ Cloudflare Worker
→ Cloudflare Container running the existing FastAPI application
→ existing Neon PostgreSQL
```

Do not rewrite the product into JavaScript merely to remove Modal. Do not move Neon data to D1 as part of this migration.

## M0 adapter

`worker.py`:

- imports Cloudflare `workers.asgi`;
- projects trusted Worker bindings into the existing `LF_*` configuration seam before importing `app.factory`;
- reuses `create_app()` directly;
- requires a Hyperdrive binding for the runtime PostgreSQL URL;
- never exposes or imports the migration-role database URL;
- keeps `MockProvider` during hosting migration so infrastructure movement does not silently widen AI-provider scope;
- fails closed if required trusted bindings are absent.

`wrangler.toml` intentionally omits Hyperdrive IDs and secret values. It is not a Production deployment authorization.

## Compatibility gate

Cloudflare Python Workers run on Pyodide. Current Cloudflare package guidance supports FastAPI/Pydantic and pure/PyEmscripten packages, but the existing production database path uses:

```text
psycopg[binary]
psycopg_pool
```

Do **not** claim native Python Worker compatibility until an actual `pywrangler` build/dev probe exercises the deployed dependency set and a PostgreSQL/Hyperdrive connection path.

Required disposition:

```text
PYTHON_WORKER_COMPATIBLE
```

or

```text
CONTAINER_FALLBACK_REQUIRED
```

If `psycopg` or another required dependency is unavailable under Pyodide, stop the native Worker lane. Use the Cloudflare Container fallback so the existing Python/PostgreSQL implementation remains authoritative.

## Required trusted bindings before a later deployment

Names only; no values belong in this repository:

```text
HYPERDRIVE
LF_ADMIN_SECRET
LF_CREDENTIAL_HMAC_KEY
LF_SESSION_HMAC_KEY
LF_ALLOWED_ORIGINS
```

`LF_ALLOWED_ORIGINS` must be the exact authorized Cloudflare application origin selected by a later deployment gate. Do not guess a hostname in source.

## Preserved invariants

```text
CANONICAL_CREATE_APP_REUSED = YES
PRODUCT_ROUTE_FORK = NO
PRIVATE_INVITE_READER_BOUNDARY = PRESERVE
ADMIN_REVIEW_BOUNDARY = PRESERVE
POSTGRES_SCHEMA = PRESERVE
NEON_DATA = PRESERVE
MIGRATIONS_AT_RUNTIME_STARTUP = NO
MIGRATION_ROLE_IN_WORKER = NO
AI_PROVIDER_ACTIVATION = NO
MODAL_RETIREMENT_BEFORE_PARITY = NO
PRODUCTION_DEPLOYMENT_BY_M0 = NO
```

## Operator sequence after this PR

1. Run the native Python Worker dependency/build probe from `apps/living-fiction` using current Cloudflare tooling.
2. If native Worker dependencies pass, provision an approved Hyperdrive binding to the existing Neon database and run bounded Preview parity tests.
3. If native Worker dependencies fail, create the bounded Cloudflare Container adapter using the existing FastAPI/psycopg app unchanged where practical.
4. Verify `/health`, `/access`, reader/admin auth, invite flow, database persistence, restart behavior, noindex/security headers, and fail-closed errors with synthetic/owner-controlled data.
5. Only after parity and rollback evidence, cut traffic to Cloudflare and retire Modal separately.

Modal remains a rollback anchor until those gates pass.
