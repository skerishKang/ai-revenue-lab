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

## Phase 2 scope

Live chat transport only. Search, file upload, login/history, Projects, image, voice, billing and public Production deployment are not part of this phase.

## Tests

```bash
python -m pytest -q
```

The test suite is deterministic and uses `httpx.MockTransport`; no provider network call is required.
