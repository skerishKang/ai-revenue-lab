# Padiem Chat — Business 62 Runtime

Padiem Chat is Padiem's Korean-first, general-user AI front door.

## Boundary

```text
Browser → Padiem Chat /api/chat → Business 14 b14/auto → provider/model
```

Padiem Chat does not own provider adapters, provider keys, model catalogs, routing or fallback policy. Those remain Business 14 authority.

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

## Cloudflare Python Worker package

`worker.py` is the Cloudflare Worker entrypoint and `wrangler.toml` deliberately defaults the deployment to:

```text
PADIEM_CHAT_RUNTIME_MODE=mock
```

The deployed Worker creates the Starlette app from immutable Worker bindings through `settings_from_worker_bindings(self.env)`. It does not depend on browser-provided upstream configuration and it does not define an OpenRouter/provider-key binding.

Supported deployment-owned bindings:

```text
PADIEM_CHAT_RUNTIME_MODE
PADIEM_CHAT_B14_BASE_URL
PADIEM_CHAT_TIMEOUT_SECONDS
```

`b14` mode without a valid B14 URL fails closed instead of silently falling back to mock.

All responses receive `nosniff`, `DENY` frame policy and `no-referrer`; API and health responses additionally receive `Cache-Control: no-store`.

## Public-release boundary

A deployed Worker is not automatically a public live-AI release. Anonymous live-provider access requires a separate abuse/cost gate with Cloudflare-side rate limiting or equivalent globally reliable controls, quota/spend limits and an emergency disable path. A per-isolate Python counter must not be treated as the public security boundary.

No DNS/custom-domain mutation is part of Phase 3.

## Tests

```bash
python -m pytest -q
```

The test suite is deterministic and uses `httpx.MockTransport`; no provider network call is required.
