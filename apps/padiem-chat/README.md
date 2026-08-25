# Padiem Chat — Business 62 Runtime

Padiem Chat is Padiem's Korean-first, general-user AI front door.

## Boundary

```text
Browser → Padiem Chat /api/chat → Business 14 b14/auto → provider/model
```

Padiem Chat owns the consumer-facing chat, continuity, Projects and bounded user-reference context. It does not own provider adapters, provider keys, model catalogs, routing or fallback policy. Those remain Business 14 authority.

## Runtime modes

### Mock (default)

```bash
PADIEM_CHAT_RUNTIME_MODE=mock \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Mock mode makes zero upstream model calls and labels the result as a mock response.

### Business 14

```bash
PADIEM_CHAT_RUNTIME_MODE=b14 \
PADIEM_CHAT_B14_BASE_URL=https://<approved-b14-host> \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

The browser never supplies a provider key or an upstream URL. B62 calls the fixed Business 14 endpoint using `model=b14/auto` and lets Business 14 choose the actual route.

## Attachments and document boundary

Current browser attachments are intentionally bounded:

```text
Images:   JPEG / PNG / WebP, one per request, up to 4 MiB
Documents: TXT / Markdown / CSV / JSON, one per request,
           UTF-8 text only, up to 96 KiB / 40,000 characters
```

Text-document content is wrapped as **untrusted reference data** inside the server-owned additional system context. It cannot select a provider, endpoint or model, and the full document text is not returned in public response metadata or written into ordinary conversation history.

PDF, DOCX, PPTX and XLSX extraction are **not supported yet**. They are deliberately deferred until a compatible extraction path is proven for the exact Cloudflare Python Worker runtime or moved behind an approved dedicated extraction service. B62 must not silently treat unsupported binary files as text.

## Auth, history and Projects

Authentication defaults off. When Google OAuth and the D1 binding are actually provisioned, B62 supports:

```text
signed-in user
├─ recent conversations
├─ Projects
│  ├─ persistent project instructions
│  ├─ project-owned chats
│  └─ bounded project text files
└─ signed HttpOnly session
```

Project text files use the same D1 binding as history and store validated UTF-8 text only. Current limits are 12 files per project, 40,000 characters per file and 160,000 stored characters per project. Original binary files and base64 payloads are not persisted in this phase.

Project/file access is owner-scoped server-side. Browser-supplied project or file identifiers never bypass ownership checks. Project instructions and file content are subordinate to core security/tool rules and do not change Business 14 routing authority.

## Cloudflare Python Worker package

`worker.py` is the Cloudflare Worker entrypoint and `wrangler.toml` deliberately defaults the deployment to:

```text
PADIEM_CHAT_RUNTIME_MODE=mock
```

The deployed Worker creates the Starlette app from immutable Worker bindings through `settings_from_worker_bindings(self.env)`. It does not depend on browser-provided upstream configuration and it does not define an OpenRouter/provider-key binding.

Server-owned runtime configuration includes B14/web/auth settings, while the optional D1 binding name is:

```text
PADIEM_CHAT_DB
```

No fake D1 database ID is committed to `wrangler.toml`. Without the actual binding, persistence-dependent capabilities remain unavailable rather than falling back to in-memory production state.

`b14` mode without a valid B14 URL fails closed instead of silently falling back to mock.

All responses receive `nosniff`, `DENY` frame policy and `no-referrer`; API, auth and health responses additionally receive `Cache-Control: no-store`.

## Public-release boundary

A deployed Worker is not automatically a public live-AI release. Anonymous live-provider access requires a separate abuse/cost gate with Cloudflare-side rate limiting or equivalent globally reliable controls, quota/spend limits and an emergency disable path. A per-isolate Python counter must not be treated as the public security boundary.

Production auth/history/Projects/project files also require the real D1 migrations and Google OAuth configuration. Repository code readiness is not a claim that those production resources are active.

## Tests

```bash
python -m pytest -q
```

The test suite is deterministic and uses `httpx.MockTransport`; no provider network call is required.
