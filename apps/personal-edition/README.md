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

## Phase 5A — Safe provider activation

The application defaults to `MockProvider`, which requires no external dependencies or credentials.

### External provider configuration

Set the following environment variables (or in `.env`):

| Variable | Required | Description |
|---|---|---|
| `AI_PROVIDER` | yes | Set to `external` |
| `AI_BASE_URL` | yes | Chat completions endpoint |
| `AI_API_KEY` | yes | Bearer token for the endpoint |
| `AI_MODEL` | yes | Advertised model name |
| `AI_TIMEOUT_SECONDS` | optional | Per-request timeout (default: 120) |
| `AI_COST_CLASS` | optional | `free`, `paid`, `local`, or `unknown` (default: `free`) |

Fail-closed behavior:

- Unknown `AI_PROVIDER` values are rejected at startup.
- Missing `AI_BASE_URL`, `AI_API_KEY`, or `AI_MODEL` when `AI_PROVIDER=external` fails closed.
- In production (`APP_ENV=production`), `AI_BASE_URL` must use HTTPS.
- Credentials are never printed, logged, or stored in database rows.

## Phase 5A — Benchmark tasks

The benchmark runner executes five distinct production-path tasks:

```bash
python3 -m scripts.benchmark run <task> [options]
```

| Task | Description |
|---|---|
| `editorial_plan` | Editorial-plan-only stage |
| `first_edition` | Full pipeline: plan + draft + validate + persist |
| `feedback_second_edition` | Follow-up edition with persisted feedback |
| `adversarial_grounding` | Full pipeline with prohibited-inference grounding test |
| `validator_feedback_repair` | Candidate corruption + deterministic validation + same-provider repair |

### Options

| Option | Description |
|---|---|
| `--fixture NAME` | Fixture to use (repeatable; default: all fixtures) |
| `--repeat N` | Repeat count per fixture (default: 1) |
| `--output PATH` | Path to write JSON benchmark report |
| `--db PATH` | SQLite database path (default: `var/benchmark.db`) |
| `--correct MINUTES` | Set `human_correction_minutes` for all runs after completion |

### Example

```bash
python3 -m scripts.benchmark run first_edition --fixture korean_founder --repeat 3 --db var/benchmark.db
```

## Phase 5A — Repeated benchmark runs

Each repetition uses isolated synthetic participant and input identities derived from the benchmark name, fixture name, and run index. No repetition inherits editions, feedback, or idempotency records from another.

Durable evidence is stored in a file-backed SQLite database (default: `var/benchmark.db`). The `--db` flag specifies an alternative path.

No real participant data is used in any benchmark run.

## Phase 5A — Human correction time

### During benchmark execution

```bash
python3 -m scripts.benchmark run first_edition --correct 5.0
```

This sets `human_correction_minutes` to `5.0` for all runs completed in that benchmark session.

### After benchmark execution

```bash
python3 -m scripts.benchmark update-correction --run-id <RUN_ID> --minutes 12.5
```

Or via pilot ops:

```bash
python3 -m scripts.pilot_ops update-correction --run-id <RECORD_ID> --minutes 12.5
```

Validation: minutes must be ≥ 0.0. The value is persisted in the `benchmark_runs` and `pilot_ops_records` tables.

## Phase 5A — Benchmark and pilot evidence

### Database location

Default: `var/benchmark.db` (benchmark) and `var/personal-edition.db` (pilot ops).

### Listing records

```bash
python3 -m scripts.pilot_ops list-records [--type TYPE] [--participant-id ID] [--db PATH]
```

### Exporting evidence

```bash
python3 -m scripts.pilot_ops export-evidence [--participant-id ID] [--export-safe] [--output PATH] [--db PATH]
```

The `--export-safe` flag:

- Pseudonymizes participant identifiers (SHA-256 truncated hash).
- Redacts private text fields (`notes`, `feedback_text`, `evidence_description`, etc.).

No credentials, API keys, or full generated private output appear in exported evidence.

## Phase 5A — Manual pilot workflow

### Invitation and consent

1. Provision a participant: `python3 -m scripts.provision_participant <id> "<name>"`
2. The participant receives a one-time token.
3. Participant enters the token at `/p/access`.
4. Participant submits input at `/p/p1/input` with consent confirmed.

### Free sample and paid editions

- One sample edition may be free.
- Seven subsequent editions for KRW 4,900 is a hypothesis, not proof of payment or revenue.
- No payment gateway, email automation, or public signup is implemented.

### Review before publication

Every edition passes through `pending_review` state. An administrator must explicitly publish or reject each edition. Automatic publication is prohibited.

## Phase 5A — Payment evidence restrictions

Payment evidence records must never contain:

- Payer identity (name, email, phone, ID)
- Account or card data (card numbers, account numbers)
- Transaction or payment reference numbers
- Credentials (API keys, tokens, passwords)
- Screenshots or receipt images
- Private artifact paths

The `PaymentEvidenceRecord` model enforces these restrictions at construction time.

## Phase 5A — Deletion and revocation

### Operator deletion command

```bash
python3 -m scripts.pilot_ops delete --participant-id <ID> [--reason REASON] [--notes NOTES] [--db PATH]
```

Or the legacy command:

```bash
python3 -m scripts.delete_participant <participant_id> [--database PATH]
```

### Lifecycle

1. A `deletion_request` record is created.
2. The participant is soft-deleted (status set to `deleted`, `deleted_at` timestamp recorded).
3. A `deletion_completion` record is created with the result.
4. Existing browser sessions are immediately invalidated (session checks active status).
5. Token access is revoked.

### Idempotent execution

Repeated deletion of the same participant is idempotent. The second execution returns `not_found` and records a completion record with `deletion_result: "not_found"`.

### Export-safe identity handling

The `export-evidence --export-safe` command pseudonymizes participant identifiers and redacts private text.

## Known limitations

- No live provider call was performed in automated tests. All tests use `MockProvider` or monkeypatched adapters.
- No real participant, payment, or revenue exists. All data is synthetic.
- No payment gateway, email automation, public signup, or automatic publication is implemented.
- The KRW 4,900 for seven editions is a pricing hypothesis, not proven revenue.
- External provider configuration requires manual environment setup.
