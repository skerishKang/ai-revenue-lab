# B61 StoryMemory

Production: https://storymemory-padiem.pages.dev/

The files in `public/` are copied from the original project's `dist/`; this is the actual source available at import time, rather than a generated output with separately available sources. Original location: `E:\b61-model-policy-schema-261031`; original commit: `9fff2410006d6ff3ceefe8e90d78f258c8d0d082`.

Deployment uses the existing Cloudflare Pages project `storymemory-padiem` and its production branch `main`. First restore any omitted assets listed in EXCLUDED_ASSETS.md from the original location, then from the repository root run:

```sh
wrangler pages deploy apps/storymemory/public --project-name storymemory-padiem --branch main
```

Deployment requires authorization and the correct Cloudflare account; do not include credentials in source. Production Pages secret: `PADIEM_INGRESS_CLIENT_SECRET`. Its value is managed outside the repository and must match the ingress client secret. The ingress itself also uses `PADIEM_ENGINE_CALLER_SECRET`, managed separately by the engine operator.

`STORYMEMORY_MODEL` optionally overrides the app's explicit model route; its default is defined in `public/_worker.js`. Do not use `b14/auto`.

`DB_MIGRATIONS/`, patch notes, and the original manifest are preserved for reference. The original manifest uses original paths and is not a manifest of the imported directory. The original project had no separately available functions/ or Wrangler configuration at its root.
