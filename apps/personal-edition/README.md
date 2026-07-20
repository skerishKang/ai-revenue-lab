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

No real credentials or private pilot material may be committed.

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

### Production requirements

When `APP_ENV=production`, the following settings are **mandatory** and must differ from their development defaults:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Strong unique key (≥32 chars) for signing session and CSRF tokens |
| `ADMIN_SECRET` | Strong unique admin secret (≥16 chars) for admin login |
| `COOKIE_SECURE` | Must be `true` to send cookies only over HTTPS |
| `SESSION_MAX_AGE_SECONDS` | Session lifetime in seconds (default 28800 = 8 hours) |
| `COOKIE_SAMESITE` | Cookie SameSite attribute (default `lax`) |

The application **refuses to start** in production if `SECRET_KEY`, `ADMIN_SECRET`, or `COOKIE_SECURE` are not properly configured.

## Phase 4 browser workflow

The application provides a server-rendered web interface for both participants and administrators.

### Participant access

1. A participant receives a one-time access token after provisioning
2. Navigate to `/p/access` and enter the token
3. The participant dashboard shows published editions and input history
4. Participants can submit new input at `/p/p1/input`
5. Participants can read published editions and submit feedback

### Admin access

1. Navigate to `/admin/access` and enter the admin secret
2. The admin dashboard shows all participants and editions
3. Admins can trigger generation for a participant's input
4. Admins can review, edit, publish, or reject editions
5. Admin can edit structured content JSON (validated against EditionContent schema)

### Security features

- **Session cookies**: Signed with purpose-separated salts; httponly, SameSite=Lax
- **CSRF protection**: Dual-cookie pattern on all state-changing POST requests
- **Privacy headers**: All `/p` and `/admin` responses include no-store, no-cache, noindex headers
- **Input size**: 500–5000 words; short-sample override requires explicit admin approval
- **Markup rejection**: Recursive check prevents script tags, event handlers, and javascript: URLs in edition content
- **Error handling**: Internal exceptions never exposed to users; generic category messages shown instead

## Database initialization

The database is automatically initialized when you first run the application.
Migrations are applied idempotently from the `migrations/` directory.

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

## Deleting a participant

Soft-delete a participant and revoke their token access:

```bash
python -m scripts.delete_participant <participant_id> [--database <path>]
```

After deletion:
- The participant's status is set to `deleted`
- Any existing browser session is immediately invalidated (session checks active status)
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
