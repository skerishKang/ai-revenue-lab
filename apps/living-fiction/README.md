# Living Fiction

Status: **Phase 2b web MVP merged; Phase A production portability foundation
(Issue #77) — pending human review**

Living Fiction tests whether AI can sustain a shared narrative canon while
rapidly producing reader-responsive personal branches that visibly reflect
explicit reader choices — without mutating shared canon or auto-publishing.

## Product principle

A common canon preserves shared discussion and fandom. Optional
reader-responsive personal branches provide personalization without turning
every reader's experience into an unrelated work. Canon is immutable once
accepted; branches may add branch-only facts but cannot rewrite canon.

## Implementation status

Phase 1 (shipped):

- product and narrative contract approved for implementation;
- independent FastAPI package under `apps/living-fiction/`;
- SQLite-backed canon/branch/episode/choice repositories;
- provider-neutral `AIProvider` protocol with deterministic `MockProvider`;
- deterministic continuity, IP, safety, and markup validators;
- file-backed canon episode and personal branch generation flows;
- all generated episodes remain `pending_review` until explicit human
  publication.

Phase 2b (shipped): private reader web experience and editorial review web
MVP (invite-only reader sessions, admin sessions, choice submission, branch
generation, review decisions).

Phase A (this change, Issue #77): production portability foundation —

- explicit database backend selection (`LF_DATABASE_BACKEND`), never inferred
  from a URL; local development keeps SQLite, production allows only
  PostgreSQL and fails closed otherwise;
- backend-neutral connection adapter (`app/database/`) with a bounded,
  scale-to-zero-friendly Psycopg 3 pool; repositories run unchanged on both
  backends;
- hand-written PostgreSQL schema migrations (`migrations_postgres/`)
  semantically equivalent to the final SQLite schema, applied only by an
  explicit operator command under an advisory lock with checksum tamper
  detection; the runtime app never migrates itself and fails closed at
  startup when the schema is missing or behind;
- operator bootstrap (`app/ops/bootstrap.py`) for migration, world/canon
  seeding, bootstrap reader, and reader-bound invite issue/rotation;
- free-tier deployment skeleton: Modal Starter ASGI entry (`deploy/modal/`)
  serving the app directly — skeleton only, deployed by an operator in
  Phase B. The production request path is `Browser -> Modal FastAPI -> Neon
  PostgreSQL`; no edge proxy is required. A Cloudflare Worker proxy is an
  optional future adapter only and is not part of this skeleton;
- `COST_AND_LIMITS.md` (free-tier envelope and upgrade conditions) and
  `PRODUCTION_PORTABILITY_AUDIT.md` (SQLite→PostgreSQL audit).

## Running

```bash
cd apps/living-fiction
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
uvicorn app.main:app --reload
```

Local development needs no configuration: the SQLite backend is the default.
Copy `.env.example` to `.env` when you need to set secrets or switch
backends; every secret must be a genuinely random value (the file documents
how to generate one) — there are no source-code fallbacks.

## Production portability (Phase A)

Production uses PostgreSQL only. The runtime application connects with
`LF_DATABASE_URL` (pooled, application role); migrations and seeding use
`LF_MIGRATION_DATABASE_URL` (owner/migration role, direct connection). Both
URLs are treated as secrets and never appear in logs or error messages.

Operator bootstrap (run explicitly, never at startup, never in CI):

```bash
export LF_MIGRATION_DATABASE_URL=...   # owner/migration-role direct URL
export LF_CREDENTIAL_HMAC_KEY=...      # required for invite commands

python -X utf8 -m app.ops.bootstrap all      # migrate + world + canon + invite
python -X utf8 -m app.ops.bootstrap rotate   # revoke + reissue the bound invite
```

Invite codes are printed exactly once and stored only as keyed HMAC digests;
a lost code cannot be recovered — rotate to issue a replacement.

Deployment is Phase B and operator-driven: see `deploy/modal/README.md` for
the exact steps, and `COST_AND_LIMITS.md` for the free-tier envelope
(scale-to-zero everywhere, no always-on resource, no automatic paid upgrade).
The required production stack is Modal Starter + Neon Free; `LF_ALLOWED_ORIGINS`
is the app's own Modal HTTPS origin. No edge proxy is required.

Live PostgreSQL integration tests are opt-in and never run in the default
suite; point them at a DISPOSABLE database (they drop/create `lf_it_*`
schemas):

```bash
LF_TEST_POSTGRES_URL=postgresql://user:pw@localhost:5432/disposable \
    python -m pytest tests_postgres_integration/ -q
```

See `PRODUCT_CONTRACT.md` for the commercial, privacy, evidence, and operating
contract. See `NARRATIVE_CONTRACT.md` for canon, checkpoint, branch, continuity,
and rejoin semantics.
