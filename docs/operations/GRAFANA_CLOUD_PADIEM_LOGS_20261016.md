# PADIEM Grafana Cloud Logs — deployment and operations (2026-10-16)

## Scope and authority
- External Grafana Cloud Japan Stack: `zestypuma1700`; Grafana URL: https://zestypuma1700.grafana.net/.
- Loki hostname: `logs-prod-030.grafana.net`, Loki write path: `/loki/api/v1/push`.
- OTLP log ingest: `https://otlp-gateway-prod-ap-northeast-0.grafana.net/otlp/v1/logs`.
- OTLP authentication username: `1876517`; Loki query authentication username: `1834293`. They are different instance IDs.
- Cloud subscription on 2026-10-16: Free trial, on-screen end date 2026-10-30. No new payment or upgrade authorized.
- Existing B62 `request_telemetry.py` is authoritative for safe event projections; no raw customer request data is exported.
- Cloudflare remains the existing application runtime (B62/B14/Engine), not an additional long-term log archive. Do not configure R2, Workers Logs, Logpush, Queues, or GitHub full-CI log collection for this pipeline.

## Actual production acceptance — 2026-10-16

- **Source merge:** PR #4852 at `33f391a81116f6b2ce94104f19c10b83f5ae4100`; follow-up protected Engine fix #4868 and B62 exact Grafana runtime activation #4870, #4877, #4878. Grafana-related Worker CI, secret-binding source tests, protection gates, and GitGuardian passed at their documented exact heads. A separate full B62 Chat/Claw UI regression continued to have pre-existing failures, not counted as a Grafana PASS.
- **B14:** protected deployment run [#38798169390](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38798169390), served-version/smoke PASS. No provider call was requested for the acceptance probe. Real request ID `padiem-grafana-b14-261016-probe-01` returned one Loki event and one COM1 SQLite row.
- **Engine:** initial post-deploy binding guard failure followed by **successful protected rollback** to `99b7dddb-a0f4-4ee1-8830-51323d808285`. Narrow binding-guard repair PR #4868 merged; protected redeployment [#38800199159](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38800199159) served version `59beccaf-3a1e-413e-a78f-0bbd3d56d920`. Live request ID `padiem-grafana-engine-261016-probe-01` is present once in Loki and once in COM1 SQLite. Engine smoke ultimately PASS after one isolated network-related retry.
- **B62 (Chat, Claw, B66 shared Worker):** first protected release [#38810262265](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38810262265) attached the canonical Secrets Store reference; a read-only check identified the two public OTLP variables as missing. Exact public-variable fix #4878 merged; final protected production release [#38812641351](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38812641351) deployed source commit `8c6ef547ebfd78cf77249953fd4fbdb38e3af05e`, served version `316ac1ee-f2de-4f12-8628-719a9ff15916`. `GRAFANA_SERVED_IMMUTABLE_BINDING=PASS`, `GRAFANA_SERVED_PUBLIC_VARS=PASS`, D1 migrations 008/040 exact, `B62_PRODUCTION_SMOKE=PASS`. A safe, unauthenticated GET to `/api/b66/runtime-config` returned 401 with echoed request ID `padiem-grafana-b62-261016-final-probe`; one corresponding Grafana Loki event reached COM1 SQLite.
- **COM1 automatic backup:** a manual immediate run of the already-installed 15-minute Scheduled Task completed with `LastTaskResult=0`. SQLite direct read confirmed one archived row per B62, B14 and Engine live request ID (three services independently verified).
- **Unverified acceptance boundary:** a **single authenticated end-to-end request** joining B62→B14/Engine→completed provider call under the **same** `X-Request-Id` has not been observed. Distinct independent service probes are not an inter-service trace. Do not mark full cross-service or all provider adapters as operational E2E PASS.

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

1. **DONE (account configuration):** `logs:write` token created in Grafana and registered as `PADIEM_GRAFANA_OTLP_TOKEN` in the existing Charliekant account-level Cloudflare Secrets Store (`f0b09ca04a7b43248154c773704a5616`). B62/B14/Engine Wrangler source declares the encrypted secret reference. No token values in source. The three **served Workers** were subsequently activated through existing protected workflows; actual request-ID Loki/COM1 acceptance is recorded below.
2. The *public* OTLP URL and instance username are in `apps/padiem-chat/wrangler.toml`. They are not credentials. Activation requires all three trusted bindings (`PADIEM_GRAFANA_OTLP_ENDPOINT`, `PADIEM_GRAFANA_OTLP_USERNAME`, `PADIEM_GRAFANA_OTLP_TOKEN`).
3. Use the existing protected B62 Worker Production workflow, not `wrangler deploy` or an ad hoc Dashboard deployment. Inspect relevant current-main drift, exact-head CI, destination and configured release/rollback requirements; do not claim deployed because a PR merged.
4. **DONE (external ingest canary):** one content-blind OTLP request returned HTTP 204 and the matching LogQL request-ID lookup returned HTTP 200. This was the original external ingest canary. Subsequent real served-Worker ingestion is independently proven below. A 401/403 after Worker deployment may mean credential, scope or binding mismatch; keep customer execution independent.
5. **DONE (Dashboard API):** the 8-panel JSON in `apps/padiem-chat/observability/padiem-requests-grafana.json` is saved at https://zestypuma1700.grafana.net/d/padiem-requests-logs/eb3f920 ; authenticated GET readback showed all eight panels. The separate B14/Engine Worker deployments have since completed, with actual request-ID evidence archived below.

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
| B62 request/stage projection | Focused tests + exact source SHA | Source merged in #4852; real B62 request-ID readback PASS |
| Grafana policy | Actual access policy and logs:write scope | logs:write and independent COM1 logs:read policies; served bindings for all three Workers VERIFIED |
| B62->Grafana ingestion | Actual Loki sample and COM1 SQLite readback | PASS: served B62 request `padiem-grafana-b62-261016-final-probe`, GET `/api/b66/runtime-config` returned 401 and echoed the same X-Request-Id; COM1 archive 1 row from Loki |
| B14/Engine/provider distributed trace | Same request ID across B62→B14→Engine and an actual provider attempt | Each independent Worker PASS (three request IDs archived); **single cross-service request ID and live provider-call stage NOT VERIFIED** |
| Grafana dashboard | Saved dashboard link + real query result | 8-panel Grafana API save and GET readback PASS: https://zestypuma1700.grafana.net/d/padiem-requests-logs/eb3f920 |
| COM1 archive | DPAPI read token, scheduled task, SQLite readback | PASS: 15-minute task, LastTaskResult=0; live B62/B14/Engine request IDs each archived as exactly one row |
| Production | Protected B62/B14/Engine releases and exact served versions | PASS: B62 #38812641351 served version `316ac1ee-f2de-4f12-8628-719a9ff15916`; Engine #38800199159 served version `59beccaf-3a1e-413e-a78f-0bbd3d56d920`; B14 #38798169390 protected deploy/smoke PASS |

## Query cardinality, cost and rollback
- Keep tenant IDs, user identities, message content, full URLs, raw error strings, and raw provider headers out of payload.
- Request ID is a log field, not a high-cardinality Loki label. Upstream model/provider names are omitted from external Grafana payloads. B14 physical provider call logging stores only a fixed outcome/error category, never the vendor/model identity.
- Cloud Free usage is bounded by upstream plan terms, not the 14-day trial banner. Review ingestion/retention/usage before the trial ends on 2026-10-30. Disable B62 `PADIEM_GRAFANA_OTLP_TOKEN` binding to stop external export without affecting API responses.
- If the archiver fails, do not retry indefinitely, reset its cursor, or equate Grafana's stored data with a completed COM1 backup. Check for 401/403 (read scope) or transport error and repair once.

## Expanded multi-service release and evidence
- Independent opt-in Worker wrappers: `apps/korean-ai-platform/{worker.py,app/stack_telemetry.py}` and `apps/padiem-ai-engine/{worker_identity.py,app/stack_telemetry.py}`; same no-request-body allowlist in both independently bundled Workers. Each service needs its own protected release; a B62 deploy does not deploy B14 or Engine.
- B62 additionally exports static product buckets `chat`, `claw`, `b66`, `other` from route templates only. No raw URL, model identity or customer data reaches Loki.
- Both independent Workers record only API/internal Worker response completion latency; **streaming full-body completion latency is not yet proven**. Provider-call stage instrumentation currently covers B14's canonical completed chat attempt; other streaming adapter branches require separate evidence before claiming full provider coverage.
- COM1 backup query now includes service names `padiem-chat`, `korean-ai-platform`, `padiem-ai-engine`. The distinct `logs:read` policy and COM1 DPAPI secret are configured, 15-minute Task Scheduler job running; one independent synthetic readback confirmed.
- Two Grafana scoped access policies and tokens were configured without upgrading the plan. The B62, B14 and Engine production Workers were deployed through their separate protected release workflows and their real log archive observations are documented above. These releases do not prove a single end-to-end provider trace.
