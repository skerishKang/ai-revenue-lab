# B62 Request Telemetry — v1 (Issue #1975)

Status: implemented (Draft PR pending review). Scope: `apps/padiem-chat` (Business 62, the customer-facing product Worker).

## Problem

Before #1975 the B62 Worker had a richly instrumented `/health` (binding and
readiness truth) but **zero per-request observability**:

- no request correlation id,
- no latency signal,
- no error-rate signal,
- no structured log channel for operations.

Any "is it slow? is it erroring?" question was unanswerable without attaching a
debugger to a live isolate.

## Decision: minimum viable, fits the current stack

The issue text proposed Prometheus metrics, alerting rules, and Grafana
dashboards. Those were **deliberately not** implemented as source changes, for
concrete reasons below. The implemented minimum is one bounded structured event
emitted per request.

### Why not Prometheus / Grafana (now)

Cloudflare Workers execute in many short-lived isolates with no shared memory
and no pull/scrape target. An in-process counter is a *sample of one isolate*,
never a fleet-wide rate. A `/metrics` endpoint returning such counters would look
authoritative while being silently wrong. Standing up a Prometheus server or a
Grafana board would also require external provisioning that this change is not
permitted to perform (`LIVE_EXTERNAL_PROVISIONING=NO`, `DEPLOY=NO`).

### What was implemented instead

- Per request, the Worker emits **one structured JSON line** carrying the exact,
  locally-measured `duration_ms`, a correlation `request_id`, the matched
  `route` template, and the `status`.
- Counting, rate derivation, and alerting are left to the log pipeline that
  Cloudflare already provides: `wrangler tail`, **Workers Logs**, and
  **Logpush** into the team's existing log/metrics backend. This is the
  stack-native aggregation layer and needs no new infrastructure.

This satisfies the issue's intent (request count, latency, error rate,
alerting, dashboard) by feeding the signals into the existing pipeline rather
than inventing a parallel, misleading one.

## Emitted event contract

One event per HTTP request, written by `app/request_telemetry.py` to the
`padiem_chat.request` logger as a single line of JSON:

```json
{
  "event": "http_request",
  "service": "padiem-chat",
  "ts": "2026-09-10T04:27:29.967Z",
  "request_id": "req_71e2c7bd1e1c46baac5f4592",
  "request_id_source": "generated",
  "method": "GET",
  "route": "/api/claw/manual-intake/artifact/{document_id}",
  "status": 200,
  "duration_ms": 0.11,
  "outcome": "ok"
}
```

### Field rules

| Field | Rule |
|-------|------|
| `event` | constant `http_request` |
| `service` | constant `padiem-chat` |
| `ts` | UTC, millisecond precision, `Z` suffix |
| `request_id` | `req_<24 hex>` generated per request; or client `X-Request-Id` if it matches a safe charset |
| `request_id_source` | `generated` or `client` (informational only) |
| `method` | HTTP method |
| `route` | matched **route template**, never the raw path |
| `status` | integer HTTP status |
| `duration_ms` | request wall-clock in milliseconds, non-negative |
| `outcome` | `ok` (<400), `client_error` (4xx), `server_error` (5xx) |

## Evidence boundary (bounded, non-secret)

The event **must never** carry request material:

- no query string (note: `?` never appears in the event),
- no request headers,
- no cookies,
- no request body,
- no client address / IP,
- no tenant or user identifier.

Path data is reduced to the matched route template, so document ids / project ids
/ conversation ids never enter the log line. Client-supplied `X-Request-Id`
values are accepted only when they match a conservative charset
(`^[A-Za-z0-9._:-]{8,64}$`), which also blocks newline injection into the log
stream; anything else is replaced with a generated id.

The response always echoes the effective `X-Request-Id` header so operators can
correlate a client call with its log entry.

## Wiring

- `app/request_telemetry.py` — pure ASGI middleware (`RequestTelemetryMiddleware`).
- `app/app_factory.py::create_app` — installs the middleware outermost and sets
  `app.state.request_telemetry_enabled`. An injectable `telemetry_emitter`
  (default: JSON line to the logger) keeps network-free tests deterministic.
- `app/app_factory.py::health` — reports `request_telemetry_enabled` (boolean
  only; no per-isolate numbers), so a deployment gate can confirm the channel
  is present in the built Worker.

## What still belongs elsewhere (explicitly out of scope here)

- **Alerting rules** (high error rate, high latency, service down): author as
  Workers Logs / Logpush alert rules against the `outcome` / `duration_ms`
  fields. No source change required.
- **Dashboards** (overview + service-specific): build in the log/metrics backend
  consuming the structured lines. No source change required.
- **Per-isolate counters / `/metrics`**: intentionally not added (see above).

## Tests

`apps/padiem-chat/tests/test_request_telemetry.py` (29 network-free cases):
request-id generation/echo/rejection, exact event key set, route-template (not
raw path), no-request-material, outcome classification, duration, default
emitter single-line JSON, emitter-failure resilience, non-HTTP scope pass-through,
and the `/health` boolean. `test_upstream_busy_diagnostics.py` health-key
allowlist was extended with `request_telemetry_enabled`.
