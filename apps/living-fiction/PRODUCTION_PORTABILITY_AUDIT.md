# Production Portability Audit — Living Fiction

Scope: `apps/living-fiction/` only. Goal: keep the existing SQLite behaviour
(418-test suite) while making PostgreSQL a selectable production backend, with
a free-tier deployment skeleton (Modal Starter + Cloudflare Workers Free +
Neon Free).

## 1. Backend selection (explicit, never inferred)

| Setting                      | Purpose                                   | Rule                                        |
| ---------------------------- | ----------------------------------------- | ------------------------------------------- |
| `LF_DATABASE_BACKEND`        | `sqlite` (default) or `postgres`          | must be exactly one of the two              |
| `LF_DATABASE_PATH`           | SQLite file                               | local/default only                          |
| `LF_DATABASE_URL`            | runtime pooled PostgreSQL connection      | required when backend is `postgres`         |
| `LF_MIGRATION_DATABASE_URL`  | owner/migration-role direct connection    | required by operator commands only          |
| `LF_DATABASE_POOL_MAX_SIZE`  | pool cap (default 5)                      | small by design                             |

Fail-closed matrix (`app/config.py:validate_database`, `app/database/engine.py`):

- unknown backend → startup rejected;
- `production` + `sqlite` → startup rejected;
- `postgres` without `LF_DATABASE_URL` → startup rejected;
- `LF_DATABASE_URL` not a PostgreSQL URL → startup rejected;
- operator command without `LF_MIGRATION_DATABASE_URL` → command rejected;
- production startup with a missing/behind/divergent schema → startup
  rejected (`verify_schema_current`); the runtime role never applies
  migrations.

Error messages never include the configured URL or any credential.

## 2. SQLite-specific surface found in the codebase

| SQLite dependency                        | Where                                        | PostgreSQL handling                                              |
| ---------------------------------------- | -------------------------------------------- | ---------------------------------------------------------------- |
| `?` parameter placeholders               | every repository/service statement           | structural rewrite to `%s`, quote-aware (`app/database/sql.py`)  |
| `INSERT OR IGNORE`                       | `reader_deletion_service.py`                 | `INSERT ... ON CONFLICT DO NOTHING` (structural)                 |
| `BEGIN IMMEDIATE` (~50 call sites)       | repositories, auth, pipeline, services       | adapter maps first-word `BEGIN` to plain `BEGIN`                 |
| `sqlite3.IntegrityError` catches         | previously 13 sites in repos + pipeline      | neutral `app.database.errors.IntegrityError`, translated at the connection boundary only |
| `PRAGMA foreign_keys` / other PRAGMAs    | `app/db.py` migrator, connection setup       | SQLite-only; ignored by the PG adapter (FK enforcement is default) |
| `sqlite3.complete_statement` batching    | `app/db.py` SQLite migrator                  | stays on the raw SQLite path; PG migrator splits statements itself |
| `lower(hex(randomblob(16)))` in trigger  | reader-deletion anonymization trigger        | `gen_random_uuid()` (PG 13+ built-in) equivalent in `migrations_postgres/010_triggers.sql` |
| `BOOLEAN` columns stored as 0/1 integers | snapshots, checkpoints, clues, telemetry...  | `SMALLINT ... CHECK (x IN (0,1))`; app stores ints, reads `bool()` |
| `REAL` columns                           | telemetry latencies                          | `DOUBLE PRECISION`                                               |
| ISO-8601 `TEXT` timestamps               | every `*_at` column                          | kept as `TEXT` (app stores/compares opaque strings)              |
| `conn.in_transaction`                    | repository idle-connection guards            | Psycopg `TransactionStatus != IDLE`                              |
| `cursor.rowcount`, `row["col"]` access   | auth revoke, all row mapping                 | native in Psycopg with `dict_row`                                |

Not present (verified): `lastrowid`, `executescript` outside the SQLite
migrator, `AUTOINCREMENT`, date/time SQL functions, `json_extract`, collations.

## 3. Schema equivalence

`migrations_postgres/` (10 files) reproduces the FINAL SQLite schema produced
by `migrations/` (9 files): 22 tables, all table-level UNIQUE/CHECK/FK
constraints, 21 secondary indexes (including the stronger
`idx_reader_choices_one_per_canon`), and the reader-deletion anonymization
trigger. The SQLite migrations themselves are untouched.

Migration runner guarantees (`app/database/migrate_postgres.py`):

- filename-sorted apply order recorded in `schema_migrations`;
- SHA-256 checksum per file; a changed-after-apply file fails rather than
  diverging;
- idempotent re-run (applied versions skipped; all DDL is
  `CREATE ... IF NOT EXISTS`);
- `pg_advisory_lock` serializes concurrent operator runs;
- each file applies in its own transaction (rolled back on failure);
- `verify_schema_current` fails closed on missing or unknown versions —
  used by production startup.

## 4. Connection model

- SQLite: one file connection per request (unchanged local behaviour).
- PostgreSQL: `psycopg_pool.ConnectionPool` with `min_size=0`,
  `max_size=LF_DATABASE_POOL_MAX_SIZE` (default 5), `timeout=5 s`,
  `max_idle=60 s`, `max_lifetime=300 s`. Idle containers hold zero
  connections, so Neon Free can scale to zero. Connections are returned at
  request end (pooled `close()` → `putconn`; an uncommitted transaction is
  rolled back on return).
- Autocommit + explicit `BEGIN`/`COMMIT` brackets writes, matching the
  repository transaction pattern; plain reads leave no transaction open.

## 5. Operator bootstrap (`app/ops/bootstrap.py`)

Commands: `migrate`, `world`, `canon`, `reader`, `invite`, `rotate`, `all`.
Never runs at startup, never in CI.

- Idempotent: re-running creates no duplicate world, canon episode, reader,
  or active invite.
- Invite codes: CSPRNG (`secrets.token_urlsafe`), stored only as keyed HMAC
  digests; plaintext printed exactly once to the operator terminal; never
  persisted, logged to a file, or exposed via any web route.
- `rotate` revokes every active bound invite before issuing a replacement.
- First canon episode is generated with the deterministic free MockProvider
  and published — zero AI API cost.

## 6. Deployment skeleton (no resources created by this repo)

- **Modal** (`deploy/modal/app_entry.py`): reuses `create_app()`; app name
  `ai-revenue-living-fiction`; `min_containers=0`, `buffer_containers=0`,
  `max_containers=2`, 60 s scaledown, 0.25 vCPU / 512 MB, no GPU/Volume/
  custom domain; secrets referenced by name only. API verified against
  `modal==1.5.2`.
- **Cloudflare** (`deploy/cloudflare/`): thin proxy; upstream from
  `UPSTREAM_ORIGIN` env only (never hardcoded); method/body/query/headers
  preserved; Host/X-Forwarded-* set; same-host-only CORS preflight;
  Set-Cookie passthrough; Location rewritten to the user-facing hostname;
  `Cache-Control: no-store` forced; bounded 30 s timeout; generic 502/504/500
  bodies with no upstream URL; structurally not an open proxy; no path
  blocking (reader `/access` untouched); `/admin/*` protection documented as
  Cloudflare Access configuration.

## 7. Test coverage

Always run (SQLite, no external services):

- existing 418-test suite — unchanged and green (SQLite regression);
- `tests/test_production_portability_contracts.py` — backend selection and
  fail-closed rules, URL/secret non-leakage, SQL adaptation, migration
  manifest/order/checksum/splitter, fail-closed schema verification,
  bootstrap idempotency + invite rotation + digest-only storage, Modal entry
  import + ASGI startup + resource caps, Cloudflare proxy static contracts.

Explicit only (requires a local PostgreSQL; never part of the default run):

- `tests_postgres_integration/` — live apply of `migrations_postgres/`,
  schema verification, bootstrap seeding through the adapter, uniqueness →
  neutral IntegrityError translation, anonymization trigger, pool acquire/
  release, checksum tamper detection. Run with:

  ```bash
  LF_TEST_POSTGRES_URL="postgresql://<role>@localhost:5432/<db>" \
      pytest tests_postgres_integration/ -q
  ```

## 8. Known Phase B blockers (operator actions, not code)

1. Provision Neon project + owner and runtime roles (no credentials exist in
   this repo).
2. Create the Modal secret `living-fiction-secrets` with real values.
3. `modal deploy` and `wrangler deploy` (Phase B), then set
   `LF_ALLOWED_ORIGINS` to the worker hostname.
4. Configure Cloudflare Access for `/admin/*` (email OTP).
5. Replace the MockProvider with a real provider only with an explicit AI
   budget (see `COST_AND_LIMITS.md`).
