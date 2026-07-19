# Personal Edition

Status: **Active first revenue experiment**

Personal Edition transforms a user-supplied conversation, note, journal entry, or voice transcript into a polished recurring letter or compact magazine. Explicit feedback must materially change the next edition.

## Current scope

The first paid pilot tests:

```text
user material
→ editorial plan
→ structured personal edition
→ human review
→ private delivery
→ reader feedback
→ visibly adapted next edition
```

## Canonical documents

- `../../docs/decisions/ADR-0001-first-revenue-experiment.md`
- `../../docs/decisions/ADR-0002-product-workspaces.md`
- `../../docs/product/PERSONAL_EDITION_MVP_CONTRACT.md`
- `../../docs/architecture/PERSONAL_EDITION_MVP_ARCHITECTURE.md`
- `../../docs/experiments/HY3_PERSONAL_EDITION_BENCHMARK.md`

## Implementation rule

All product code, tests, configuration examples, scripts, migrations, and product-local fixtures belong in this directory.

The current implementation entry issue is GitHub Issue #20. No real credentials or private pilot material may be committed.

## Local setup

```bash
python3 -m venv /tmp/ai-revenue-lab-personal-edition-venv
source /tmp/ai-revenue-lab-personal-edition-venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run the application

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Run tests

```bash
pytest -q
```

## Configuration

Copy `.env.example` to `.env` and adjust as needed. Defaults use the `mock` provider, which requires no external dependencies.

## Database initialization

The database is automatically initialized when you first run any script or
application that uses `app.db.get_connection()`. Migrations are applied
idempotently from the `migrations/` directory.

To initialize manually:

```python
from app.db import get_connection, apply_migrations

conn = get_connection("var/personal-edition.db")
apply_migrations(conn, "migrations")
conn.close()
```

## Provisioning a participant

Create a new participant and receive a one-time access token:

```bash
python -m scripts.provision_participant <participant_id> "<display_name>" \
    [--language ko|en] [--database <path>]
```

Example:

```bash
python -m scripts.provision_participant alice "Alice" --language ko
```

The command prints a one-time token. **Store it securely** — it will not be
shown again. The database stores only the SHA-256 hash of this token.

## Retaining the one-time token

After provisioning, the token must be:

1. Copied and stored in a password manager or secure vault
2. Never committed to version control
3. Never shared over unencrypted channels
4. Used as a Bearer token in API requests (Phase 3)

The token is a 256-bit URL-safe string generated via `secrets.token_urlsafe(32)`.

## Inspecting records

View all records for a participant:

```bash
python -m scripts.inspect_records <participant_id> [--json] [--database <path>]
```

Example:

```bash
python -m scripts.inspect_records alice
python -m scripts.inspect_records alice --json
```

Text output shows participant info, inputs, editions, and feedback.
JSON output provides a structured dump suitable for piping to `jq`.

## Deleting a participant

Soft-delete a participant and revoke their token access:

```bash
python -m scripts.delete_participant <participant_id> [--database <path>]
```

Example:

```bash
python -m scripts.delete_participant alice
```

After deletion:
- The participant's status is set to `deleted`
- Token lookup returns `None` (access revoked)
- The `deleted_at` timestamp is recorded
- Dependent records (inputs, editions, feedback) remain in the database

## Repository APIs

All repository modules follow the same transaction policy:

- Each write function begins with `BEGIN IMMEDIATE` and ends with `COMMIT`
- If the caller already has an open transaction, `RepositoryTransactionError` is raised
- All SQL is parameterized
- All timestamps are UTC ISO-8601

### Available repositories

| Module | Purpose |
|---|---|
| `app.participant_repository` | Participant CRUD, token provisioning, deletion |
| `app.input_repository` | Input record CRUD, sequence numbering |
| `app.edition_repository` | Edition CRUD, publication state machine, content updates |
| `app.feedback_repository` | Feedback CRUD, structured direction validation |
| `app.generation_run_repository` | Generation run accounting, provider metrics |

### Privacy helpers

`app.privacy` provides Starlette response factories with restrictive cache
and no-index headers for private participant data:

- `restrictive_cache_response()` — full no-store, no-cache, private, noindex
- `no_index_response()` — noindex without full cache restrictions
- `private_json_response()` — JSON with all restrictive headers
