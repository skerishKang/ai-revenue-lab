# Padiem AI Engine — API Reference

```text
DOC_STATUS = CURRENT_API_AUTHORITY
SCOPE = internal Engine HTTP contract only
SPEC = apps/padiem-ai-engine/openapi.json
VALIDATED_BY = apps/padiem-ai-engine/tests/test_openapi_contract.py
```

This page is the **API reference** for the internal Padiem AI Engine (IP-ENGINE) HTTP contract. It is intentionally narrow: it documents *how to call the endpoints*, not the platform role or architecture. For those, see `docs/internal-platform/engine/README.md` and `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`.

## What this API is

The Engine exposes two internal endpoints over a Cloudflare **Service Binding**. It is consumed only by first-party callers (e.g. Padiem Chat / B62, Padiem Claw) and is **not** publicly routable. The machine-readable contract lives in `openapi.json` (OpenAPI 3.0.3).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/internal/v1/health` | Liveness + capability posture |
| POST | `/internal/v1/execute` | Completed-run / orchestration execution |

## Endpoints (summary)

### `GET /internal/v1/health`
Always returns `200` when the Worker is up. Feature readiness is truthful: degraded capabilities are reported as `unavailable` rather than hidden. Non-GET methods return `405`.

Response (200) includes `status`, `service`, `core_available`, `b14_service_bound`, `capabilities` (bounded posture), `service_identity`, and `endpoints`.

### `POST /internal/v1/execute`
Body must be `application/json`, at most **128 KiB** (limit is source-bound — see validation below). Required top-level fields: `app_id`, `agent`, `messages`. The `agent` object requires `id`, `title`, `description`, `system_instruction`, `task_type`, `optimize_for`, `max_tokens`.

Success (200) returns `ok: true` with `answer`, the resolved `route` projection, `metadata`, and any evidence/projection fields spread into the body. All errors return `ok: false` with `error.code` / `error.message` / `error.retryable`.

Possible error statuses: `400` (invalid request/JSON/contract), `404` (unknown route), `405` (wrong method), `409` (idempotency conflict), `413` (body too large), `415` (wrong content type), `422` (boundary/context/policy), `500` (internal), `502`/`503`/`504` (upstream).

## How it is consumed

First-party callers reach the Engine through the `B14_SERVICE` / dedicated Engine Service Binding configured in `apps/padiem-ai-engine/wrangler.toml`; they do not call a public URL. The reference client is `apps/padiem-ai-engine/clients/python`.

## Keeping the spec honest

`openapi.json` is **source-bound**, not decorative. `tests/test_openapi_contract.py` asserts that the spec's paths, required request fields, and the 128 KiB limit match the constants in `app/service.py` (`EXECUTE_PATH`, `HEALTH_PATH`, `MAX_REQUEST_BODY_BYTES`, `_TOP_LEVEL_REQUIRED`, `_AGENT_REQUIRED`). A source change that alters the contract must update the spec in the same pull request, or the test fails.

## Rendering the spec (local, no new infra)

The spec is plain JSON; render it with any OpenAPI 3.0 tool, e.g.:

```bash
npx @redocly/cli preview-docs apps/padiem-ai-engine/openapi.json
# or
npx swagger-ui-cli serve apps/padiem-ai-engine/openapi.json
```

No server-side component is required; this stays within the existing tooling boundary (`DEPLOY=NO`).
