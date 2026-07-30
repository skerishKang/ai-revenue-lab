# Cloudflare Worker Deployment — Korean AI Platform (Business 14)

## Architecture

```
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
- **Validation**: Manual JSON validation (not pydantic) — via `_validate_body()` in gateway.py
- **Outbound**: `httpx.AsyncClient` (standard Python) — Worker runtime compatible

## Exact Worker Name

```
ai-revenue-korean-ai-platform
```

## Production URL

```
https://ai-revenue-korean-ai-platform.charliekant.workers.dev
```

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
bash ./deploy.sh             # production deploy
```

The script performs:
1. `uv sync --frozen` — install exact dependency versions
2. `uv run pywrangler sync --force` — vendor Python packages for Pyodide
3. `rm -rf .venv .venv-workers` — remove pywrangler-generated venvs
4. `npx wrangler deploy` — upload to Cloudflare

Expected output:
```
Total Upload: ~4403 KiB / gzip: ~954 KiB
```

## Workers Builds (GitHub Automatic Deployment)

Connect in Cloudflare Dashboard → Workers & Pages → `ai-revenue-korean-ai-platform` → Settings → Build:

| Field | Value |
|-------|-------|
| Worker name | `ai-revenue-korean-ai-platform` |
| GitHub repository | `skerishKang/ai-revenue-lab` |
| Cloudflare Production branch | `ops/business-14-dedicated-cloudflare-worker-138` |
| Root directory | `apps/korean-ai-platform` |
| Build command | *(leave empty)* |
| Deploy command | `bash ./deploy.sh` |

`Production branch` is Cloudflare control-plane terminology. It does not itself grant portfolio release authority. Deployment authorization, exact-head validation, and rollback preparation follow `docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`.

## Environment Variables

Runtime variables (set via Cloudflare Dashboard → Worker → Variables):

| Variable | Description | Required |
|----------|-------------|----------|
| `BUSINESS14_PROVIDER_REGISTRY_JSON` | JSON array of provider configs | No (not_configured) |
| `BUSINESS14_PILOT_BASE_URL` | Legacy single-provider base URL | No |
| `BUSINESS14_PILOT_MODEL_ID` | Legacy single-provider model ID | No |
| `BUSINESS14_PILOT_PROVIDER_ID` | Legacy single-provider ID | No |
| `BUSINESS14_PILOT_UPSTREAM_MODEL` | Legacy upstream model name | No |
| `BUSINESS14_PILOT_TIMEOUT_SECONDS` | Upstream timeout (default 30) | No |

## No-Secret Policy

- Provider API keys are NEVER stored in Worker variables
- API keys are user-provided via `X-Business14-Provider-Key` header at runtime
- Keys are validated, used for upstream Authorization, and discarded
- Keys never appear in logs, responses, or stack traces
- GitHub repository contains NO credentials

## Security Headers

Static assets and Worker responses both include:

```http
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Cache-Control: no-store
```

Static files are served via Cloudflare Workers `[assets]` with `run_worker_first = true`,
which allows the Worker to apply headers before serving.

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
- /workspace loads with Korean text
- Language switch to English works
- Static assets load (no 404)
- Browser console: 0 errors
- No JavaScript exceptions

Mobile (390×844):
- No horizontal overflow (scrollWidth === clientWidth)
- Model select accessible
- Key input accessible
- Language switch accessible

## Rollback

```bash
# Via CLI — rollback to previous version
npx wrangler rollback --name ai-revenue-korean-ai-platform

# Via Dashboard — Workers → ai-revenue-korean-ai-platform → Deployments → ⋮ → Rollback
```

After rollback:
1. Verify `/workspace` returns HTTP 200
2. Verify `/api/pilot/health` returns expected state
3. Verify static assets return HTTP 200
4. Verify no credential exposure

Rollback does NOT affect other Cloudflare projects (Personal Video Archive, Pages, etc.)

## Known Limitations

- **Provider registry not configured**: The Worker deploys in `not_configured` state.
  Set `BUSINESS14_PROVIDER_REGISTRY_JSON` for multi-provider chat.
- **Static files at root path**: Assets are served at `/app.css` not `/static/app.css`
  (Cloudflare Workers Static Assets behavior).
- **Disposable BYOK key required**: Real Provider calls need a user-supplied API key
  via `X-Business14-Provider-Key` header. No keys are bundled.
- **FastAPI/Pydantic removed**: Manual validation replaces pydantic's auto-validation.
  The validation is equivalent but does not use pydantic internally.
