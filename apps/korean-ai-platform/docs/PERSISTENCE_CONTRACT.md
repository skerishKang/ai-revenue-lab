# Korean AI Platform — Persistence Contract (Business 14)

Status: product-local SQLite persistence implemented (demo grade).

## Canonical references

This contract follows the portfolio decisions and integration contracts read
from `origin/main`:

- `docs/decisions/ADR-0002-product-workspaces.md`
- `docs/decisions/ADR-0003-shared-portal-isolated-products.md`
- `docs/product/AI_REVENUE_LAB_PORTAL_CONTRACT.md`
- `docs/architecture/PORTAL_PRODUCT_INTEGRATION_CONTRACT.md`
- `docs/portfolio/BUSINESS_REGISTRY.md`

## Data ownership

Business 14 owns its own product-local database, migrations, secrets boundary,
records, and evidence. Per ADR-0003 §4:

- the Business 14 DB is separate from every other Business DB;
- no Business queries another Business database directly;
- portal/common storage never holds Korean AI Platform execution payloads,
  evidence, or API keys;
- sibling Business code is not imported;
- no `platform/` or shared package is created;
- secrets, execution permissions, and records stay product-local.

## Storage backend

- Default backend: SQLite (`KAP_DB_BACKEND=sqlite`), standard library `sqlite3`.
- Default path: `var/korean-ai-platform.db`, resolved relative to the Business
  14 workspace (`apps/korean-ai-platform/`).
- `KAP_`-prefixed env vars only; the ambient `DATABASE_URL` is never read.
- PostgreSQL is a future runtime boundary. Selecting `KAP_DB_BACKEND=postgresql`
  fails closed with a fixed configuration error; there is no silent fallback to
  SQLite.
- Single-process only. No multi-process/worker support.

## Tables and relationships

Relational, queryable, constrained — no JSON aggregate blobs.

- `tasks` — scalar workflow state with CHECK constraints on enums and
  non-negative numbers.
- `task_allowed_paths`, `task_denied_paths`, `task_rework_reasons` — ordered
  child rows (FK to `tasks`, `position` preserves order).
- `task_runs` — one row per run, PK `(task_id, run_number)`; rework adds a new
  `run_number`, it does not overwrite previous runs (evidence history kept).
- `run_steps`, `run_changed_files`, `run_test_summaries`, `run_test_results`,
  `run_findings`, `run_path_violations`, `run_security_notes`, `run_cost_lines`,
  `run_timeline` — run evidence child tables (FK to `task_runs`, ordered).
- `security_settings` — singleton (`id = 1`); `block_push_without_approval`
  constrained to always be true.
- `byok_registrations` — `registered` boolean per model. No raw key column.
- `task_id_sequence` — singleton DB sequence for `t-NNN` IDs.
- `seed_meta` — product-local seed flag.
- `schema_migrations` — migration version ledger.

## Transaction owner

`route -> application service -> repository / transaction -> engine pure
transition -> DB persistence`.

- The engine performs pure domain transitions and artifact creation only; it
  never runs SQL.
- Repositories own SQL and hydration only; they never own transactions.
- The application service (`app/services.py`) owns the transition-unit
  transaction: load → validate → mutate → persist as one `BEGIN IMMEDIATE`
  transaction, committed on success, rolled back on failure.
- Each of these is atomic: task creation (+ID allocation + paths), run
  transition (+full run evidence), rework (+reason +status), approve
  (+status/approver/completed_at/branch/commit), reject (+status/reason),
  settings (+all BYOK registrations).
- On DB failure, memory and DB never diverge and no success redirect is
  produced.

## Seed policy

- Demo seed tasks are created only on a truly empty database, once, tracked by
  `seed_meta`.
- Migrations never contain mutable demo data.
- Tests can create an empty DB with `SqliteTaskService.initialize(seed=False)`.
- Seed task IDs (`t-demo-*`) never collide with the `t-NNN` sequence.

## Secrets are not stored

- No raw API key, provider credential, GitHub token, DB URL, or environment
  secret is ever persisted.
- BYOK stores only a `registered` boolean. No key prefix/suffix/hash/encrypted
  value is stored in this demo.
- A blank key save preserves the existing registration; unregistration requires
  an explicit action.
- Errors are normalized to a fixed safe message; raw SQL, parameters, SQLite
  error strings, and absolute paths are never surfaced to users (original error
  kept only as `__cause__`).

## Future PostgreSQL boundary

A future PostgreSQL adapter would implement the same repository interface behind
the narrow runtime boundary in `app/db.py` / `app/repositories.py`. It is not
implemented here; selecting it fails closed.

## Data the portal and other Businesses cannot access

Execution payloads, run evidence, changed-file diffs, test results, cost/token
records, verdicts/findings, approval state, governance settings, and BYOK
registration are product-local. They are not exposed to the portal or other
Businesses.

## Deletion / retention

Backup, restore, encryption, deletion, and retention procedures are follow-up
work and are not implemented in this stage. Deleting the SQLite file resets all
local state.
