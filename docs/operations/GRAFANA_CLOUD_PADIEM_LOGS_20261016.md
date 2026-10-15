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
- Source now forwards diagnostic `X-Request-Id` over existing fixed B62->B14, B62->Engine and Engine->B14 Service Bindings. B14/Engine add independent metadata-only Worker emission and fixed code/latency for B14's canonical completed provider attempt. The original request ID is *never* used for authentication, tenant access, or account authority. A cross-service end-to-end trace remains pending until confirmed by an actual live request and correlated records from those services.
- Do not claim real ingestion until one synthetic safe event can be queried by request ID in Grafana Explore. Do not transmit actual prompts, query strings, cookie values, request bodies, headers, IPs, customer identities, unredacted provider errors, or token values.

## Provisioning — source and external activation
The Grafana Cloud Portal access policy `padiem-prod-logs-write` already exists at https://grafana.com/orgs/zestypuma1700/access-policies . Its realm is the Japan `zestypuma1700` stack and **sole scope** is `logs:write`; a scoped `logs:write` token was created and stored in the existing B62 Cloudflare account-level Secrets Store; its value is never published.

1. **DONE (account configuration):** `logs:write` token created in Grafana and registered as `PADIEM_GRAFANA_OTLP_TOKEN` in the existing Charliekant account-level Cloudflare Secrets Store (`f0b09ca04a7b43248154c773704a5616`). B62/B14/Engine Wrangler source declares the encrypted secret reference. No token values in source. Binding to the **served Workers** requires separately approved protected releases.
2. The *public* OTLP URL and instance username are in `apps/padiem-chat/wrangler.toml`. They are not credentials. Activation requires all three trusted bindings (`PADIEM_GRAFANA_OTLP_ENDPOINT`, `PADIEM_GRAFANA_OTLP_USERNAME`, `PADIEM_GRAFANA_OTLP_TOKEN`).
3. Use the existing protected B62 Worker Production workflow, not `wrangler deploy` or an ad hoc Dashboard deployment. Inspect relevant current-main drift, exact-head CI, destination and configured release/rollback requirements; do not claim deployed because a PR merged.
4. **DONE (external ingest canary):** one content-blind OTLP request returned HTTP 204 and the matching LogQL request-ID lookup returned HTTP 200. This proves external Grafana ingestion but not served Worker ingestion. A 401/403 after Worker deployment may mean credential, scope or binding mismatch; keep customer execution independent.
5. **DONE (Dashboard API):** the 8-panel JSON in `apps/padiem-chat/observability/padiem-requests-grafana.json` is saved at https://zestypuma1700.grafana.net/d/padiem-requests-logs/eb3f920 ; authenticated GET readback showed all eight panels. Live metrics for B14/Engine remain empty until their separate Workers are deployed.

## Independent COM1 archive (activated: 15-minute scheduled backup)
- Pull architecture: Grafana Loki authenticated `logs:read` HTTP API -> Windows COM1 local SQLite `%LOCALAPPDATA%\PADIEM\GrafanaLogs\archive.sqlite3`, with WAL, request-ID index and dedup by event hash.
- Archiver: `scripts/ops/grafana_com1_backup.py`. Scheduled installer: `scripts/ops/install_grafana_com1_backup.ps1`.
- **DONE:** separate `padiem-com1-loki-read` Grafana access policy scoped solely to Japan Stack `logs:read`; distinct token saved with COM1 Windows-user DPAPI at `%LOCALAPPDATA%\PADIEM\secrets\grafana-loki-read.dpapi`. Do not reuse `logs:write`, grant `logs:delete`, or publish the token.
- The installer copies both archive code and task runner to the stable COM1 user location `%LOCALAPPDATA%\PADIEM\GrafanaLogs\bin` before registering the 15-minute Task Scheduler job. Therefore removing a Git worktree does not break the scheduled backup. A one-time installation command is `powershell -NoProfile -File scripts/ops/install_grafana_com1_backup.ps1`. `-InitializeSecret` is reserved for interactive token rotation; never send the secret to chat.
- Scheduled task: `PADIEM-Grafana-Logs-COM1-Backup`. It runs only when this Windows user is logged in; it is **not** a guaranteed always-online offsite backup. If COM1 is offline, backlog is pulled in bounded chronological 24-hour batches when it comes online again. Do not assume Grafana retention guarantees retrieval after expiration.
- **DONE, COM1 acceptance:** task `PADIEM-Grafana-Logs-COM1-Backup` is Ready and its on-demand execution finished with `LastTaskResult=0`. A fresh synthetic Loki log was archived to SQLite and read back (1 record/1 request ID). The task is configured for every 15 minutes, interactive-user only; continuous offline operation is not claimed.
- COM1 has finite disk and the SQLite archive currently has **no automated retention limit**. Check disk and archive size and decide a local retention/rotation policy before usage volume grows; never enable paid Grafana ingestion to compensate.

## Operations checklist
| Boundary | Evidence required | Present on 2026-10-16 |
| --- | --- | --- |
| B62 request/stage projection | Focused tests + exact source SHA | Code in PR worktree; focused tests run |
| Grafana policy | Actual access policy and logs:write scope | Policy and server-side Secret created; Worker binding pending deployment |
| B62->Grafana ingestion | Actual Loki sample in Explore | Synthetic safe sample OTLP 204 / Loki query 200 PASS; B62 Worker runtime NOT VERIFIED |
| B14/Engine/provider distributed trace | Same request ID in actual downstream services | NOT VERIFIED |
| Grafana dashboard | Saved dashboard link + real query result | 8-panel Grafana API save and GET readback PASS: https://zestypuma1700.grafana.net/d/padiem-requests-logs/eb3f920 |
| COM1 archive | DPAPI read token, scheduled task, SQLite readback | PASS: logs:read policy, COM1 DPAPI, 15-minute task Ready, executed LastTaskResult=0, 1 synthetic record readback |
| Production | Protected B62 Worker release run and deployment SHA | NOT DEPLOYED |

## Query cardinality, cost and rollback
- Keep tenant IDs, user identities, message content, full URLs, raw error strings, and raw provider headers out of payload.
- Request ID is a log field, not a high-cardinality Loki label. Upstream model/provider names are omitted from external Grafana payloads. B14 physical provider call logging stores only a fixed outcome/error category, never the vendor/model identity.
- Cloud Free usage is bounded by upstream plan terms, not the 14-day trial banner. Review ingestion/retention/usage before the trial ends on 2026-10-30. Disable B62 `PADIEM_GRAFANA_OTLP_TOKEN` binding to stop external export without affecting API responses.
- If the archiver fails, do not retry indefinitely, reset its cursor, or equate Grafana's stored data with a completed COM1 backup. Check for 401/403 (read scope) or transport error and repair once.

## Expanded multi-service release and evidence (source only)
- Independent opt-in Worker wrappers: `apps/korean-ai-platform/{worker.py,app/stack_telemetry.py}` and `apps/padiem-ai-engine/{worker_identity.py,app/stack_telemetry.py}`; same no-request-body allowlist in both independently bundled Workers. Each service needs its own protected release; a B62 deploy does not deploy B14 or Engine.
- B62 additionally exports static product buckets `chat`, `claw`, `b66`, `other` from route templates only. No raw URL, model identity or customer data reaches Loki.
- Both independent Workers record only API/internal Worker response completion latency; **streaming full-body completion latency is not yet proven**. Provider-call stage instrumentation currently covers B14's canonical completed chat attempt; other streaming adapter branches require separate evidence before claiming full provider coverage.
- COM1 backup query now includes service names `padiem-chat`, `korean-ai-platform`, `padiem-ai-engine`. The distinct `logs:read` policy and COM1 DPAPI secret are configured, 15-minute Task Scheduler job running; one independent synthetic readback confirmed.
- Two Grafana scoped access policies and tokens were configured without upgrading plan. **No B62/B14/Engine Production Worker code deployments were executed by this observability change**; each release remains subject to exact-main CI and product-specific protected deployment workflows.
