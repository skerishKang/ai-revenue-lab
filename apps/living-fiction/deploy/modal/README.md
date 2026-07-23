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
