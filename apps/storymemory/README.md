# B61 StoryMemory

Production: https://storymemory-padiem.pages.dev/

The files in `public/` are copied from the original project's `dist/`; this is the actual source available at import time, rather than a generated output with separately available sources. Original location: `E:\b61-model-policy-schema-261031`; original commit: `9fff2410006d6ff3ceefe8e90d78f258c8d0d082`.

Deployment uses the existing Cloudflare Pages project `storymemory-padiem` and its production branch `main`. First restore any omitted assets listed in EXCLUDED_ASSETS.md from the original location, then from the repository root run:

```sh
wrangler pages deploy apps/storymemory/public --project-name storymemory-padiem --branch main
```

Deployment requires CTO authorization and the correct Cloudflare account; do not include credentials in source.

AI now uses `public/_worker.js` → `https://chat.padiem.net/api/apps/ai` → COM2 P01. The Pages secret `STORYMEMORY_COM2_AI_SECRET` must match the same named secret on the COM2 Chat host; the caller subject is fixed to `sub_app_storymemory`. Signing reuses BookAI records v1 (method, path, seconds timestamp, subject, SHA-256 body, then HMAC-SHA256).

StoryMemory 1.0 retains the old ingress as fallback on missing COM2 credentials, connection/timeout errors, HTTP 401/404, server failures, and only the P01 service-auth HTTP 403 codes `service_app_not_authorized` / `service_authentication_failed`. Other HTTP 403 responses remain refusals. Preserve `PADIEM_INGRESS_CLIENT_SECRET` for this fallback. Model/policy refusals and quota/validation errors do not trigger fallback. COM2 and fallback each have an independent 60-second request budget; no model retry is added. Keys and deployment are managed by CTO.

`STORYMEMORY_MODEL` optionally overrides the app's explicit model route; its default is defined in `public/_worker.js`. Do not use `b14/auto`.

`DB_MIGRATIONS/`, patch notes, and the original manifest are preserved for reference. The original manifest uses original paths and is not a manifest of the imported directory. The original project had no separately available functions/ or Wrangler configuration at its root.
