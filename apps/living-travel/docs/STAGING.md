# Living Travel — Staging Operations

This document describes how to deploy, configure, and operate the Living Travel
staging environment.

## Architecture

| Layer | Technology | Isolation |
|-------|-----------|-----------|
| Frontend | Cloudflare Pages (static) | Separate project `ai-revenue-living-travel` |
| API | Modal (serverless FastAPI) | App `ai-revenue-living-travel-staging` |
| Database | Neon PostgreSQL 16 | Project `ai-revenue-living-travel` |
| Auth | Firebase (shared project) | `ai-revenue-lab-identity` |

The staging stack is fully isolated from the Personal Edition app. No shared
database, no shared Modal app, no shared Cloudflare project.

## Environment Variables

### Modal (server-side)

Set via Modal Secret `ai-revenue-living-travel-staging`:

| Variable | Description |
|----------|-------------|
| `LT_DATABASE_BACKEND` | Must be `postgresql` |
| `LT_DATABASE_URL` | Neon pooled connection string |
| `LT_MIGRATION_DATABASE_URL` | Neon direct (non-pooled) connection string |
| `LT_AUTH_MODE` | Must be `firebase` |
| `LT_FIREBASE_PROJECT_ID` | `ai-revenue-lab-identity` |
| `LT_ALLOWED_ORIGINS` | Comma-separated allowed CORS origins |
| `LT_OPERATOR_SECRET` | Operator bootstrap secret (rotate periodically) |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Full service account JSON for token verification |

### Cloudflare Pages (client-side)

No server-side secrets. The Firebase Web SDK config in
`site/staging/assets/config.js` contains only public web API keys.

## Deployment

### 1. Provision Neon database

```bash
neon projects create --name ai-revenue-living-travel --pg-version 16
neon databases create --project-id <PROJECT_ID> --name living_travel
```

Record the pooled and direct connection strings.

### 2. Deploy Modal app

```bash
cd apps/living-travel
modal deploy modal_app.py
```

The app name is derived from `APP_NAME = "ai-revenue-living-travel-staging"` in
`modal_app.py`. The web endpoint URL will be:
`https://ai-revenue-living-travel-staging--web.modal.run`

### 3. Deploy Cloudflare Pages

```bash
cd apps/living-travel/pages-preview
npx wrangler pages deploy site --project-name ai-revenue-living-travel
```

Branch previews deploy automatically on PR branches via the Cloudflare Pages
GitHub integration.

### 4. Configure Firebase authorized domains

In the Firebase console for `ai-revenue-lab-identity`, add the Cloudflare Pages
domain to Authentication → Settings → Authorized domains:

- `ai-revenue-living-travel.pages.dev`
- `<branch>.ai-revenue-living-travel.pages.dev` (for branch previews)

## Database Migrations

Migrations run automatically on application startup via advisory-lock-protected
idempotent execution. No manual migration step is required.

- SQLite migrations: `migrations/001–006.sql`
- PostgreSQL migrations: `migrations/postgresql/001–006.sql`

The migration engine selects the correct set based on `LT_DATABASE_BACKEND`.

## Operator Bootstrap

After first deployment, bind an operator identity:

```bash
python -m app.admin bind-operator --firebase-uid <UID>
```

This must be run against the staging database (set `LT_DATABASE_URL` and
`LT_DATABASE_BACKEND=postgresql` in the environment).

## Security Invariants

- Bearer-token only authentication (no cookies, no localStorage tokens)
- CORS restricted to exact Cloudflare Pages origins
- CSP on `/staging/*` allows only gstatic scripts + exact Firebase/API origins
- No `unsafe-inline`, no `unsafe-eval`, no wildcard origins
- All API responses use safe DOM rendering (textContent only)
- Firebase service account JSON never ships to the browser
- Invitation codes are one-time-use (consumed on claim)
- Operator role requires explicit DB mapping (never auto-granted)

## Monitoring

- Modal dashboard: https://modal.com/apps (app: `ai-revenue-living-travel-staging`)
- Neon dashboard: https://console.neon.tech (project: `ai-revenue-living-travel`)
- Cloudflare dashboard: https://dash.cloudflare.com (project: `ai-revenue-living-travel`)

## Rollback

Modal deployments are versioned. To roll back:

```bash
modal app rollback ai-revenue-living-travel-staging --version <N>
```

Database migrations are additive-only (no down migrations). Schema rollback
requires restoring from a Neon branch/backup.
