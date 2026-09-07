# B62 / B14 Upstream Busy Incident Runbook (#2079)

- Status: INCIDENT RUNBOOK / READ-ONLY DIAGNOSIS FIRST
- Product surface: Padiem Chat (`chat.padiem.net`)
- Boundary: B62 Chat Worker -> B14/Core execution -> provider/model route
- Production mutation: forbidden by this document

## 1. User-visible symptom

Observed UI text:

```text
답변을 불러오지 못했습니다.
지금 사용자가 많습니다. 잠시 후 다시 시도해 주세요.
```

This text is consistent with B62 receiving an upstream busy/rate-limit style error from the B14/Core/provider execution path. It is not, by itself, proof that the static chat UI is broken.

## 2. Request path to verify

```text
Browser
  -> /api/chat/stream
  -> apps/padiem-chat Worker
  -> PADIEM_CHAT runtime settings
  -> B14_SERVICE service binding or B14 base URL
  -> B14/Core execution runtime
  -> selected provider/model
```

The incident must be diagnosed at the boundary where the first non-healthy response appears. Do not assume the provider is the root cause until B62 health and B14 binding status are checked.

## 3. Read-only checks

### 3.1 B62 health

```bash
curl -sS https://chat.padiem.net/health
```

Record:

```text
runtime=
b14_configured=
live_enabled=
quota_store_bound=
live_abuse_gate_ready=
history_store_bound=
canonical_identity_bound=
identity_shadow_bound=
```

Expected interpretation:

- `runtime=mock`: public worker is not armed for live B14 execution.
- `runtime=b14` with `live_enabled=false`: live gate is not fully armed.
- `b14_configured=false`: B14 base URL/config is missing.
- `quota_store_bound=false` or `live_abuse_gate_ready=false`: usage gate may fail closed or block live traffic.

### 3.2 Chat stream error payload

```bash
curl -i -sS https://chat.padiem.net/api/chat/stream \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  --data '{"messages":[{"role":"user","content":"테스트"}]}'
```

Record:

```text
HTTP_STATUS=
CONTENT_TYPE=
ERROR_CODE=
ERROR_MESSAGE=
FIRST_SSE_EVENT=
```

Interpretation:

- `429`, `503`, or error code `upstream_busy`: likely provider/B14 upstream pressure.
- `upstream_binding_unavailable`: B14 service binding or stream transport is unavailable.
- `unauthorized`: auth/session/project state issue.
- `usage_denied` style code: quota or abuse gate issue.
- `empty_upstream_answer` / `malformed_upstream`: B14/Core/provider response-shape issue.

### 3.3 Cloudflare binding and settings audit

Read-only confirmation only:

```text
PADIEM_CHAT_RUNTIME_MODE=
PADIEM_CHAT_LIVE_ENABLED=
PADIEM_CHAT_B14_BASE_URL=
B14_SERVICE bound=YES/NO
PADIEM_CHAT_DB bound=YES/NO
PADIEM_CHAT_QUOTA_SALT configured=YES/NO
```

Do not print or paste secret values into tickets, comments, logs, or chat.

### 3.4 B14 target check

Check the B14 Worker/service binding target separately:

```text
B14_HEALTH_STATUS=
B14_PROVIDER_ROUTE=
B14_SELECTED_MODEL=
B14_PROVIDER_STATUS=
B14_RATE_LIMIT_OR_QUOTA_SIGNAL=
```

Do not rotate keys, change provider routing, change model defaults, or deploy during diagnosis.

## 4. Triage matrix

| First failing boundary | Likely cause | Correct next action |
| --- | --- | --- |
| `/health` unavailable | B62 Worker/domain/runtime outage | Check Cloudflare Worker/Pages deployment and route status |
| `runtime=mock` | Live execution is intentionally disabled or deadman switch is active | Decide whether live should be armed; requires operator approval |
| `b14_configured=false` | Missing B14 base URL/config | Fix configuration only after approval |
| `upstream_binding_unavailable` | B14 service binding/stream transport unavailable | Inspect service binding; do not bypass with public URL without approval |
| `upstream_busy` / `upstream_rate_limited` | B14 provider/model quota or rate limit | Check B14 provider quota and model route; consider approved fallback route |
| `usage_denied` | Quota/abuse gate | Inspect usage counters and configured limits |
| `empty_upstream_answer` | Provider returned no visible answer | Check B14/Core response normalization |
| `malformed_upstream` | Provider/Core response shape mismatch | Inspect B14 runtime logs and response parser |

## 5. What source changes can and cannot fix

Source changes can help with:

- clearer diagnostics
- more precise user-facing error classification
- health metadata expansion
- smoke tests for binding/gate readiness
- operator runbooks

Source changes cannot directly fix:

- exhausted provider quota
- invalid or expired production secrets
- missing Cloudflare service binding
- disabled live gate
- model-pool runtime routing
- production deployment state

## 6. Safe follow-up implementation options

Allowed future PRs:

1. Add a B62 health detail field that distinguishes configured B14 URL from service binding presence.
2. Add a source-level test ensuring `upstream_rate_limited` maps to a precise user message and machine-readable code.
3. Add a smoke script that checks `/health` and `/api/chat/stream` without secrets.
4. Add operator documentation for approved fallback model/provider routing.

Forbidden without separate explicit approval:

- Cloudflare deployment
- secret rotation
- service binding mutation
- B14 production model default change
- quota bypass
- automatic fallback to a costly provider
- fake successful answers that hide an upstream outage

## 7. Incident report template

```text
INCIDENT=B62_B14_UPSTREAM_BUSY
TIME=
CHAT_DOMAIN=https://chat.padiem.net
USER_VISIBLE_ERROR=
HEALTH_RUNTIME=
HEALTH_B14_CONFIGURED=
HEALTH_LIVE_ENABLED=
HEALTH_QUOTA_READY=
CHAT_STREAM_HTTP_STATUS=
CHAT_STREAM_ERROR_CODE=
CHAT_STREAM_ERROR_MESSAGE=
B14_SERVICE_BOUND=
B14_HEALTH=
B14_PROVIDER_ROUTE=
B14_PROVIDER_RATE_LIMITED=
LIKELY_ROOT_CAUSE=
SAFE_FIX_RECOMMENDATION=
DEPLOY=NO
PRODUCTION_MUTATION=0
```

## 8. Current working hypothesis

Based on the observed user-facing message, the most likely class is:

```text
LIKELY_CLASS=B14_OR_PROVIDER_UPSTREAM_BUSY_OR_RATE_LIMITED
B62_STATIC_UI_PRIMARY_FAILURE=UNLIKELY
CONFIG_BINDING_FAILURE=POSSIBLE
```

This remains a hypothesis until `/health`, `/api/chat/stream`, and B14 target checks are captured.