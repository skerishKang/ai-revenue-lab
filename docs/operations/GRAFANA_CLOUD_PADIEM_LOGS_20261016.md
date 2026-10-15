# PADIEM Grafana Cloud Logs — deployment and operations (2026-10-16)

## Scope and authority
- External Grafana Cloud Japan Stack: `zestypuma1700`; Grafana URL: https://zestypuma1700.grafana.net/.
- Loki hostname: `logs-prod-030.grafana.net`, Loki write path: `/loki/api/v1/push`.
- OTLP log ingest: `https://otlp-gateway-prod-ap-northeast-0.grafana.net/otlp/v1/logs`.
- OTLP authentication username: `1876517`; Loki query authentication username: `1834293`. They are different instance IDs.
- Cloud subscription on 2026-10-16: Free trial, on-screen end date 2026-10-30. No new payment or upgrade authorized.
- Existing B62 `request_telemetry.py` is authoritative for safe event projections; no raw customer request data is exported.
- Cloudflare remains only the existing B62 application runtime. Do not configure R2, Workers Logs, Logpush, Queues, or GitHub full-CI log collection for this pipeline.

## Shipped source integration and limits
- B62 HTTP middleware assigns/echoes a validated `X-Request-Id`, records status, route template and latency, and emits bounded stage events for B14 operations with the same request ID.
- B14's internal execution identifier is saved as *additional correlation metadata*, not as a replacement for the externally visible request ID.
- The opt-in `GrafanaOtlpExporter` only accepts the defined `http_request`/`ai_stage` event keys, with strict endpoint and label validation. The Worker exports only AI API routes and HTTP 5xx errors. Each request carries at most 11 structured events (10 bounded stages + HTTP) and a one-second remote deadline.
- Export is registered via Worker `waitUntil`; no Grafana network request is awaited before sending the HTTP response. Export failures are isolated. If the trusted credential is unavailable/invalid, exporter is OFF and customer behavior stays unchanged.
- The existing local structured logger still emits HTTP events (not an external Cloudflare log archive). This task does not enable any new Cloudflare retention sink.
- Request ID correlation currently crosses **B62 HTTP -> B14 client stage**, recording selected route/provider summary. It is NOT proof of independent B14 Worker -> Engine -> external provider trace propagation. A cross-service end-to-end trace remains pending until confirmed by an actual live request and correlated records from those services.
- Do not claim real ingestion until one synthetic safe event can be queried by request ID in Grafana Explore. Do not transmit actual prompts, query strings, cookie values, request bodies, headers, IPs, customer identities, unredacted provider errors, or token values.

## Provisioning — prerequisites not supplied by code
The Grafana Cloud Portal access policy `padiem-prod-logs-write` already exists at https://grafana.com/orgs/zestypuma1700/access-policies . Its realm is the Japan `zestypuma1700` stack and **sole scope** is `logs:write`; as of last inspection it has **no tokens**.

1. Create **one** token under that access policy. Do not paste its value into a chat, an Issue, a PR, a script, or command-line history. Provision it using the authorized operator UI into the server-side PADIEM Cloudflare Secrets Store under the name `PADIEM_GRAFANA_OTLP_TOKEN`. In the deployment config, bind that name to the B62 Worker after confirming it actually exists. Never put the value into `wrangler.toml` or `[vars]`.
2. The *public* OTLP URL and instance username are in `apps/padiem-chat/wrangler.toml`. They are not credentials. Activation requires all three trusted bindings (`PADIEM_GRAFANA_OTLP_ENDPOINT`, `PADIEM_GRAFANA_OTLP_USERNAME`, `PADIEM_GRAFANA_OTLP_TOKEN`).
3. Use the existing protected B62 Worker Production workflow, not `wrangler deploy` or an ad hoc Dashboard deployment. Inspect relevant current-main drift, exact-head CI, destination and configured release/rollback requirements; do not claim deployed because a PR merged.
4. Send exactly one non-sensitive synthetic safe event or one authorized production request. Verify a Grafana LogQL query such as `{service_name="padiem-chat"} | json | request_id="req_<validated id>"`. A 401/403 may mean incorrect OTLP username/token scope; keep customer execution independent.
5. The dashboard source JSON is `apps/padiem-chat/observability/padiem-requests-grafana.json` (5 panels). Import to the actual Grafana instance and resolve the Loki datasource. The dashboard URL is not considered created/operational until Grafana confirms saving it and panels find real data.

## Independent COM1 archive (does NOT happen automatically)
- Pull architecture: Grafana Loki authenticated `logs:read` HTTP API -> Windows COM1 local SQLite `%LOCALAPPDATA%\PADIEM\GrafanaLogs\archive.sqlite3`, with WAL, request-ID index and dedup by event hash.
- Archiver: `scripts/ops/grafana_com1_backup.py`. Scheduled installer: `scripts/ops/install_grafana_com1_backup.ps1`.
- Create a **separate** access policy with only `logs:read` in the Japan Stack and its own token. Do not reuse the `logs:write` token and do not grant `logs:delete`. Store read token as current COM1 Windows user DPAPI secret via interactive operator PowerShell:
  `powershell -NoProfile -File scripts/ops/install_grafana_com1_backup.ps1 -InitializeSecret`
  This stores the token under `%LOCALAPPDATA%\PADIEM\secrets\grafana-loki-read.dpapi` and registers a task every 15 minutes, only after token entry.
- Scheduled task: `PADIEM-Grafana-Logs-COM1-Backup`. It runs only when this Windows user is logged in; it is **not** a guaranteed always-online offsite backup. If COM1 is offline, backlog is pulled in bounded chronological 24-hour batches when it comes online again. Do not assume Grafana retention guarantees retrieval after expiration.
- No task or token was installed as part of preparing this source. After operator token authorization, confirm `Get-ScheduledTask`, test `python scripts/ops/grafana_com1_backup.py`, and query `archive.sqlite3` for the synthetic request ID. A silent failed task is not backup proof.
- COM1 has finite disk and the SQLite archive currently has **no automated retention limit**. Check disk and archive size and decide a local retention/rotation policy before usage volume grows; never enable paid Grafana ingestion to compensate.

## Operations checklist
| Boundary | Evidence required | Present on 2026-10-16 |
| --- | --- | --- |
| B62 request/stage projection | Focused tests + exact source SHA | Code in PR worktree; focused tests run |
| Grafana policy | Actual access policy and logs:write scope | Policy created; token missing |
| B62->Grafana ingestion | Actual Loki sample in Explore | NOT VERIFIED |
| B14/Engine/provider distributed trace | Same request ID in actual downstream services | NOT VERIFIED |
| Grafana dashboard | Saved dashboard link + real query result | JSON only; NOT IMPORTED |
| COM1 archive | DPAPI read token, scheduled task, SQLite readback | Source only; NOT ACTIVE |
| Production | Protected B62 Worker release run and deployment SHA | NOT DEPLOYED |

## Query cardinality, cost and rollback
- Keep tenant IDs, user identities, message content, full URLs, raw error strings, and raw provider headers out of payload.
- Request ID is a log field, not a high-cardinality Loki label.
- Cloud Free usage is bounded by upstream plan terms, not the 14-day trial banner. Review ingestion/retention/usage before the trial ends on 2026-10-30. Disable B62 `PADIEM_GRAFANA_OTLP_TOKEN` binding to stop external export without affecting API responses.
- If the archiver fails, do not retry indefinitely, reset its cursor, or equate Grafana's stored data with a completed COM1 backup. Check for 401/403 (read scope) or transport error and repair once.
