# Cloudflare Worker Deployment — Korean AI Platform (Business 14)

- Scope: product-specific Cloudflare Worker runtime deployment
- Portfolio hosting terminology: `docs/operations/CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md`

## Terminology and lifecycle

This document describes an explicitly authorized Worker runtime deployment, not a Phase 1 static hosted-review connection.

Cloudflare uses the field name `Production branch` for the primary Git-connected deployment branch. That field name alone does not authorize a portfolio product release. The release state still requires the applicable issue, exact-head review, runtime evidence, and user/CTO authorization.

The feature branch shown below was the historical branch-validation setting used by PR #142. After merge, the intended primary branch was `main`. This document does not claim the current Cloudflare control-plane setting without direct dashboard or API verification.

## Architecture

```text
Browser → Cloudflare Edge → [Assets] static files → Worker (Pyodide)
                                         ↓
                              Starlette ASGI app
                              ├─ Jinja2 templates (workspace.html)
                              ├─ Provider routing (httpx outbound)
                              └─ BYOK chat completions API
```

- **Worker**: `worker.py` — ASGI entrypoint with env bridge + security headers
- **Framework**: Starlette (not FastAPI) — removes pydantic-core 4 MiB dependency
- **Config**: `os.environ` based (not pydantic-settings) — via `app/config.py` and `app/pilot/config.py`
- **Validation**: Manual JSON validation (not pydantic) — via `_validate_body()` in `gateway.py`
- **Outbound**: `httpx.AsyncClient` (standard Python) — Worker runtime compatible

## Exact Worker Name

```text
ai-revenue-korean-ai-platform
```

## Product runtime URL

```text
https://ai-revenue-korean-ai-platform.charliekant.workers.dev
```

The URL is product-specific. A successful deployment to a different Worker or Pages project is not Korean AI Platform evidence.

## Prerequisites

- Node.js >= 22
- Wrangler >= 4.64 (installed via npm)
- `uv` >= 0.29
- Cloudflare account with Workers permission

## Local Development (uvicorn)

```bash
cd apps/korean-ai-platform
uv sync --frozen
uv run uvicorn app.main:app --reload
open http://127.0.0.1:8000/workspace
```

## Local Worker Test (pywrangler dev)

```bash
cd apps/korean-ai-platform
uv run pywrangler dev
curl http://127.0.0.1:8787/workspace
```

## Clean Checkout Build & Deployment

Use the committed build script from the repo root:

```bash
cd apps/korean-ai-platform
bash ./deploy.sh --dry-run   # verify size without deploying
bash ./deploy.sh             # deploy the authorized Worker runtime
```

The script performs:

1. `uv sync --frozen` — install exact dependency versions
2. `uv run pywrangler sync --force` — vendor Python packages for Pyodide
3. `rm -rf .venv .venv-workers` — remove pywrangler-generated venvs
4. `npx wrangler deploy` — upload to Cloudflare

Expected output:

```text
Total Upload: ~4403 KiB / gzip: ~954 KiB
```

Running the script proves only that a deployment command completed. It does not prove that the intended Git branch, Worker name, environment, or release authorization is correct. Verify those separately.

## Workers Builds (GitHub Automatic Deployment)

Connect in Cloudflare Dashboard → Workers & Pages → `ai-revenue-korean-ai-platform` → Settings → Build.

### Historical PR #142 branch-validation setting

| Field | Value |
|---|---|
| Worker name | `ai-revenue-korean-ai-platform` |
| GitHub repository | `skerishKang/ai-revenue-lab` |
| Cloudflare `Production branch` field | `ops/business-14-dedicated-cloudflare-worker-138` |
| Root directory | `apps/korean-ai-platform` |
| Build command | *(leave empty)* |
| Deploy command | `bash ./deploy.sh` |

### Intended post-merge primary setting

| Field | Intended value |
|---|---|
| Worker name | `ai-revenue-korean-ai-platform` |
| GitHub repository | `skerishKang/ai-revenue-lab` |
| Cloudflare primary branch | `main` |
| Root directory | `apps/korean-ai-platform` |
| Build command | *(leave empty)* |
| Deploy command | `bash ./deploy.sh` |

Do not state that the account currently uses `main` unless the Cloudflare control plane is directly verified. Do not reuse this Worker or its build connection for another Business.

## Environment Variables

Runtime variables are set via Cloudflare Dashboard → Worker → Variables.

| Variable | Description | Required |
|---|---|---|
| `BUSINESS14_PROVIDER_REGISTRY_JSON` | JSON array of provider configs | No (`not_configured`) |
| `BUSINESS14_PILOT_BASE_URL` | Legacy single-provider base URL | No |
| `BUSINESS14_PILOT_MODEL_ID` | Legacy single-provider model ID | No |
| `BUSINESS14_PILOT_PROVIDER_ID` | Legacy single-provider ID | No |
| `BUSINESS14_PILOT_UPSTREAM_MODEL` | Legacy upstream model name | No |
| `BUSINESS14_PILOT_TIMEOUT_SECONDS` | Upstream timeout (default 30) | No |

## No-Secret Policy

- Provider API keys are never stored in Worker variables.
- API keys are user-provided via `X-Business14-Provider-Key` header at runtime.
- Keys are validated, used for upstream Authorization, and discarded.
- Keys never appear in logs, responses, or stack traces.
- The GitHub repository contains no credentials.

## Security Headers

Static assets and Worker responses both include:

```http
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Cache-Control: no-store
```

Static files are served via Cloudflare Workers `[assets]` with `run_worker_first = true`, which allows the Worker to apply headers before serving.

## Exact deployment verification

Before accepting deployment evidence, record and verify:

- Worker name;
- GitHub repository;
- configured primary branch;
- root directory;
- deployed exact SHA;
- environment classification;
- URL host;
- visible Korean AI Platform identity;
- required runtime and asset responses;
- authorization issue and release status.

A green build under a different Worker or project is invalid evidence.

## Health Verification

```bash
curl -fsS https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace
curl -fsS https://ai-revenue-korean-ai-platform.charliekant.workers.dev/api/pilot/health
curl -fsS https://ai-revenue-korean-ai-platform.charliekant.workers.dev/api/pilot/models
curl -fsS -o /dev/null https://ai-revenue-korean-ai-platform.charliekant.workers.dev/app.css
curl -fsS -o /dev/null https://ai-revenue-korean-ai-platform.charliekant.workers.dev/app.js
curl -fsS -o /dev/null https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace.js
```

## Browser Verification

```bash
cd apps/korean-ai-platform
python -m pytest tests/test_worker.py -v
python -m pytest -q
python -W error::Warning -m pytest -q
```

Desktop (1440×900):

- `/workspace` loads with Korean text;
- language switch to English works;
- static assets load without 404;
- browser console has zero errors;
- no JavaScript exceptions occur.

Mobile (390×844):

- no horizontal overflow (`scrollWidth === clientWidth`);
- model select is accessible;
- key input is accessible;
- language switch is accessible.

## Rollback

```bash
# Via CLI — rollback to previous version
npx wrangler rollback --name ai-revenue-korean-ai-platform

# Via Dashboard — Workers → ai-revenue-korean-ai-platform → Deployments → ⋮ → Rollback
```

After rollback:

1. verify `/workspace` returns HTTP 200;
2. verify `/api/pilot/health` returns the expected state;
3. verify static assets return HTTP 200;
4. verify no credential exposure;
5. record the active Worker version or SHA;
6. confirm no unrelated Cloudflare project changed.

Rollback does not affect other Cloudflare projects when the correct Worker name is used.

## Known Limitations

- **Provider registry not configured**: the Worker deploys in `not_configured` state. Set `BUSINESS14_PROVIDER_REGISTRY_JSON` for multi-provider chat only through an approved configuration change.
- **Static files at root path**: assets are served at `/app.css`, not `/static/app.css`, because of Cloudflare Workers Static Assets behavior.
- **Disposable BYOK key required**: real provider calls need a user-supplied API key via `X-Business14-Provider-Key`; no keys are bundled.
- **FastAPI/Pydantic removed**: manual validation replaces pydantic auto-validation. The contract must be maintained by tests.
