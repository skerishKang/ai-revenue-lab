# Modal deployment (Phase B — operator run)

This directory contains the Modal entry that serves the existing Living
Fiction ASGI app (`app.factory.create_app`) on Modal's free **Starter** plan.
Nothing here deploys itself; every step below is run explicitly by an
operator.

## What the entry configures

- App name: `ai-revenue-living-fiction`.
- Scale to zero: `min_containers=0`, `buffer_containers=0`, 60 s
  `scaledown_window`. No keep-warm container, no GPU, no Volume, no custom
  domain (custom domains are not available on Starter anyway).
- Hard capacity cap: `max_containers=2`. Modal serves one concurrent input per
  container by default; the entry deliberately does not opt into
  `@modal.concurrent`, so total concurrency is bounded by the container cap.
- Minimal resources: 0.25 vCPU, 512 MB per container.
- Secrets are referenced by NAME (`living-fiction-secrets`); no secret value
  exists in this repository.
- Cold starts are expected: the first request after idle pays container
  startup plus one PostgreSQL connection + schema-current check.

## Image packaging

The Modal Image ships only the runtime sources, added explicitly with
`Image.add_local_dir`. Modal 1.x does not auto-mount sibling local packages, so
this entry never relies on automount and never copies the whole repository:

- `app` → `/root/app` — the FastAPI package, carrying `templates/` and
  `static/` to `/root/app/templates` and `/root/app/static` (where
  `app/web.py` resolves them).
- `migrations_postgres` → `/root/migrations_postgres` — verified at startup by
  `app/factory.py`.

Excluded from the Image: `tests/`, `tests_postgres_integration/`, local SQLite
data, `.env`, virtualenvs, Git metadata, and other Business apps.

## Prerequisites

1. A Modal account on the Starter plan (`$0 + compute`, $30/month free
   credit).
2. `pip install modal` and `modal setup` (creates your API token locally).
3. A Neon project with:
   - an **owner/migration role** connection string
     (`LF_MIGRATION_DATABASE_URL`), and
   - a **runtime role** connection string (`LF_DATABASE_URL`) whose grants
     cover DML on the application tables only.
4. The schema already applied (the runtime never migrates):

   ```bash
   cd apps/living-fiction
   LF_MIGRATION_DATABASE_URL="<owner-role URL>" python -X utf8 -m app.ops.bootstrap migrate
   ```

5. Bootstrap data + first invite (prints the invite code once):

   ```bash
   LF_MIGRATION_DATABASE_URL="<owner-role URL>" \
   LF_CREDENTIAL_HMAC_KEY="<your key>" \
       python -X utf8 -m app.ops.bootstrap all
   ```

## Deploy

1. Create the Modal secret (values stay on Modal; only names appear here).
   `LF_ALLOWED_ORIGINS` is the app's own Modal HTTPS origin — the URL the
   browser loads the app from. No edge proxy is required:

   ```bash
   modal secret create living-fiction-secrets \
       LF_ENV=production \
       LF_DATABASE_BACKEND=postgres \
       LF_DATABASE_URL="<runtime-role URL>" \
       LF_ALLOWED_ORIGINS="https://ai-revenue-living-fiction--<your-team>.modal.run" \
       LF_ADMIN_SECRET="<random 32+ chars>" \
       LF_CREDENTIAL_HMAC_KEY="<random 32+ chars>" \
       LF_SESSION_HMAC_KEY="<random 32+ chars, distinct>"
   ```

   `LF_MIGRATION_DATABASE_URL` is deliberately NOT a Modal runtime secret; it
   is used only by the explicit operator migration/bootstrap commands above.

2. Deploy from the package root so the `app` package uploads:

   ```bash
   cd apps/living-fiction
   modal deploy deploy/modal/app_entry.py
   ```

3. Verify:

   ```bash
   curl https://ai-revenue-living-fiction--<your-team>.modal.run/health
   ```

## Operating notes

- **Rotate the invite** (revokes the active code, prints a replacement once):

  ```bash
  LF_MIGRATION_DATABASE_URL="<owner-role URL>" \
  LF_CREDENTIAL_HMAC_KEY="<your key>" \
      python -X utf8 -m app.ops.bootstrap rotate
  ```

- **Schema changes**: add a new `migrations_postgres/NNN_*.sql` file, run
  `bootstrap migrate`, then redeploy. Startup fails closed if the runtime
  schema is behind the on-disk migrations.
- **Cost control**: see `../../COST_AND_LIMITS.md`. The Starter plan bills
  only active container seconds; idle costs nothing. Do not enable keep-warm,
  GPU, or paid plan features without the upgrade conditions in that document.

## Production deployment record (non-secret)

Actual Phase B deployment evidence. No secret material, connection host,
password, invite code, or session token is recorded here — only public /
non-secret identifiers.

- **Deployment date**: 2026-07-24
- **Architecture**: Browser → Modal FastAPI → Neon PostgreSQL (no edge proxy).
- **Plans**: Neon **Free** (scale-to-zero) · Modal **Starter** (scale-to-zero).
- **Modal app / function**: `ai-revenue-living-fiction` / `web`.
- **Public Modal URL**: `https://padiemipu--ai-revenue-living-fiction-web.modal.run`
- **Neon project**: `ai-revenue-living-fiction` (region `aws-ap-southeast-1`,
  PostgreSQL 17).
- **Database**: `living_fiction`.
- **Owner / migration role**: `living_fiction_owner` (direct, unpooled —
  operator-only; never a runtime secret).
- **Runtime role**: `living_fiction_app` (pooled endpoint, `sslmode=require`,
  DML-only least privilege).

### Verification summary

- **Migrations**: 10 applied via `bootstrap migrate`; re-run is idempotent
  ("schema already current"); `schema_migrations` ordered with checksums.
- **Runtime privilege matrix**: `CONNECT` / `USAGE` / `SELECT,INSERT,UPDATE,
  DELETE` granted; `CREATE` on `public` revoked; no table ownership;
  `CREATE` / `ALTER` / `DROP` all denied (SQLSTATE 42501) as `living_fiction_app`.
- **Bootstrap**: 1 world, 1 published canon episode, 1 bootstrap reader,
  1 active invite (DB stores only a keyed HMAC digest of the invite code).
- **Smoke**: `/health`, `/access`, `/admin/access` all 200 over HTTPS; private
  pages send `Cache-Control: no-store` and `X-Robots-Tag: noindex`; foreign-
  `Origin` POST rejected 403; same-origin POST accepted; reader/admin cookies
  are `Secure; HttpOnly; SameSite=lax`.
- **Reader/admin workflow**: invite login → canon read → choice → branch
  `pending_review` → admin approve → reader reads approved branch; DB ended with
  1 choice, 1 branch, 1 personal episode, 1 review decision; invite/session
  stored digest-only (no plaintext columns).
- **Restart persistence**: after `modal app rollover --strategy recreate`, the
  same in-memory reader cookie still read the approved branch (200); session,
  branch, review, and audit rows persisted; canon snapshot/checkpoint unchanged.
- **Cold start**: after >90 s idle, `/health` returned 200 in ~5.8 s (container
  scaled to zero, then cold-started); reader session still valid afterwards.
- **Cost controls**: Neon Free + scale-to-zero; Modal `min_containers=0`,
  `max_containers=2`, no GPU, no Volume, no keep-warm; no paid upgrade or card
  enrollment.
