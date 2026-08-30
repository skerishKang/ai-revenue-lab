# Personal Edition

Status: **Active Business 1 product**

Personal Edition transforms user-supplied conversations, notes, journal entries, or voice transcripts into a polished recurring letter or compact magazine. Explicit feedback must materially change the next edition, and publication remains human-reviewed.

## Current governance

Personal Edition owns its product-specific quality and review contracts. In particular, B1 must continue to verify:

- source grounding and provenance;
- prohibited-inference / invented-fact rejection;
- editorial-plan and structured-edition validity;
- visible feedback adaptation;
- human review before publication;
- private participant and operator boundaries.

General provider/model selection is **not** owned by the historical Personal Edition benchmark program anymore. Portfolio-wide provider/model eligibility, availability, cost/latency/quality policy, fallback, and route evidence belong to **Business 14 · Korean AI Platform / Router Core (#371)**.

Historical benchmark/pilot Issues **#2, #12, #40, and #49** were closed `not_planned` on 2026-08-30. They remain historical evidence only and are not current execution gates.

The old `scripts/benchmark.py` utility remains in the tree for historical/product-local diagnostic use. It must **not** be treated as authoritative for new cross-provider/model role decisions in its current legacy form. Historical PR #50 remains closed and unmerged.

## Canonical documents

- `../../docs/decisions/ADR-0001-first-revenue-experiment.md`
- `../../docs/decisions/ADR-0002-product-workspaces.md`
- `../../docs/product/PERSONAL_EDITION_MVP_CONTRACT.md`
- `../../docs/architecture/PERSONAL_EDITION_MVP_ARCHITECTURE.md`

Historical experiment documents such as `../../docs/experiments/HY3_PERSONAL_EDITION_BENCHMARK.md` are preserved for provenance but are not current model-selection authority.

## Implementation rule

All product code, tests, configuration examples, scripts, migrations, and product-local fixtures belong in this directory.

No real credentials or private participant material may be committed.

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

When `APP_ENV=production`, the following settings are mandatory and must differ from development defaults:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Strong unique key (≥32 chars) for signing session and CSRF tokens |
| `ADMIN_SECRET` | Strong unique admin secret (≥16 chars) for admin login |
| `COOKIE_SECURE` | Must be `true` to send cookies only over HTTPS |
| `SESSION_MAX_AGE_SECONDS` | Session lifetime in seconds (default 28800 = 8 hours) |
| `COOKIE_SAMESITE` | Cookie SameSite attribute (default `lax`) |

The application refuses to start in production if `SECRET_KEY`, `ADMIN_SECRET`, or `COOKIE_SECURE` are not properly configured.

## Browser workflow

The application provides a server-rendered interface for participants and administrators.

### Participant access

1. A participant receives a one-time access token after provisioning.
2. Navigate to `/p/access` and enter the token.
3. The participant dashboard shows published editions and input history.
4. Participants can submit new input at `/p/p1/input`.
5. Participants can read published editions and submit feedback.

### Admin access

1. Navigate to `/admin/access` and enter the admin secret.
2. The admin dashboard shows participants and editions.
3. Admins can trigger generation for a participant input.
4. Admins can review, edit, publish, or reject editions.
5. Structured content JSON is validated against the EditionContent schema.

### Security features

- signed session cookies with purpose-separated salts;
- CSRF protection on state-changing POST requests;
- restrictive private/no-index response headers;
- input-size and short-sample controls;
- recursive unsafe-markup rejection;
- generic user-facing error handling.

## Database initialization

The database is initialized through the product migration path. Migrations must remain idempotent and preserve the currently selected backend contract.

## Provisioning a participant

Create a participant and receive a one-time access token:

```bash
python -m scripts.provision_participant <participant_id> "<display_name>" \
    [--language ko|en] [--database <path>]
```

The command returns the raw token once. Store it securely; the product stores only its digest.

## Deleting a participant

```bash
python -m scripts.delete_participant <participant_id> [--database PATH]
```

Deletion/revocation behavior must preserve the current product contract and invalidate private access as specified by the repository tests.

## Repository APIs

Product-local repository modules include participant, input, edition, feedback, and generation-run persistence. Transaction ownership, parameterized SQL, state transitions, structured JSON validation, and UTC timestamps are enforced by the current implementation and tests.

## Provider configuration boundary

The existing application can be configured with mock or external-provider paths through environment-only configuration. Credentials must never be committed, printed, or persisted in product evidence.

This direct provider configuration is an implementation compatibility path, **not** a declaration that Personal Edition owns portfolio-wide provider/model strategy. New general routing and model-selection decisions should follow Business 14 / Router Core authority (#371).

## Legacy benchmark and pilot utilities

The repository still contains historical utilities such as `scripts/benchmark.py` and `scripts/pilot_ops`. They may be useful for reproducibility, regression investigation, or narrowly scoped B1 diagnostics, but they are not current commercial or cross-model governance.

Important historical boundaries:

- the old HY3 benchmark plan is not a current gate;
- the old Gemini 15-case report is diagnostic evidence only and must not be presented as an accepted cross-model ranking;
- the old KRW 4,900 / seven-edition pilot was a pricing hypothesis, not current pricing or revenue evidence;
- no new live benchmark, paid pilot, or participant study is authorized merely because these scripts remain in the repository;
- if B1 needs a new benchmark or paid pilot, create a fresh issue against the current B1 product/runtime contract.

## Known limitations

- automated tests do not imply live-provider quality or commercial acceptance;
- no historical benchmark result should be upgraded into current evidence without fresh validation;
- current product, UI, runtime, deployment, and commercialization authority must be read from the latest active B1 issues/PRs and portfolio governance, not from retired July benchmark issues.
