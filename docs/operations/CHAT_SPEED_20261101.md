# Chat request latency and COM2 worker preparation

Work order: #6460 §4-1. Base `680e19f89ebb7b2cbe4c43b406e8a5991ce5a7fe`,
branch `perf/chat-speed-261101`. Scope: Chat request instrumentation, identity
validation cache, local SQLite concurrency, Claw initial reads, host worker
preparation and their tests. No model selection, live configuration, service
restart, deployment, PR or merge. The existing Engine `pc_work_metrics`/B14
turn record remains the PC-work measurement authority; request spans complement
it on the already existing `http_request` log, without a new metrics database.

## Production baseline (read-only)

2026-11-01: read the preceding two hours of `padiem-chat-com2.service` journal
through K_lipvoice/Ubuntu, extracting only declared route templates and numeric
duration/status fields. 64 API request events. Sorted by maximum observed total:

| Route | n | Mean ms | Max ms | Auth/identity/P01/B14/queue/SQLite ms | After ms |
|---|---:|---:|---:|---|---|
| `/api/claw/local-access/devices` | 1 | 13708.28 | 13708.28 | Unmeasured | Deployment required |
| `/api/claw/verified-model-choices` | 6 | 6739.65 | 10450.98 | Unmeasured | Deployment required |
| `/api/voice/identity` | 3 | 7044.73 | 10445.79 | Unmeasured | Deployment required |
| `/api/auth/password/login` | 1 | 8592.59 | 8592.59 | Unmeasured | Deployment required |
| `/api/claw/inbox/{kind}` | 2 | 8089.89 | 8374.97 | Unmeasured | Deployment required |

These are real observed totals, not an attribution to any particular subsystem.
Old logs contain no component durations. A production before/after component
comparison requires CTO deployment of the instrumentation and subsequent use;
this code-only lane does not manufacture missing component measurements.

## Measurement contract

The existing single request event gains `timings_ms` with fixed keys `auth`,
`edge`, `identity`, `p01`, `b14`, `queue`, `sqlite_wait`, `sqlite_execute`.
`duration_ms` remains whole-response wall time, including streaming consumption.
Timers use `perf_counter`, a request ContextVar, and a shared thread-safe
accumulator propagated into SQLite threads. No SQL, bind values, tokens,
request bodies, identities or raw paths are added. Route templates retain the
existing telemetry privacy boundary; the edge middleware's raw-path print is
removed. Identity time can be inside auth; simultaneous calls can overlap.
**Columns are inclusive and must not be summed as a latency budget.**

SQLite wait includes executor scheduling and the connection lock; execution
includes the DB driver's operation. B14 reuses its existing completion/stream
timers, excluding the overlapping first-delta event. P01 stream timing spans
its iterator's lifecycle; telemetry does not buffer chunks or add a deadline.
The host puts the existing telemetry middleware outside edge verification so
ingress replay-store latency is visible as `edge`.

## Reproduced local baselines (synthetic, not production)

- WAL SQLite: a controlled 120 ms writer with five simultaneous reads caused
  121.47 / 121.62 / 122.07 / 121.91 / 121.79 ms read totals. The wait component
  was 120.978 / 121.134 / 121.327 / 121.652 / 121.698 ms; execution was
  0.159 / 0.335 / 0.119 / 0.167 / 0.022 ms. Reproduce with
  `python scripts/dev/benchmark_chat_sqlite_261101.py`.
- Canonical session guard: five sequential requests to a synthetic 25 ms
  identity resolver made five calls, taking 126.48 ms in total.
- Actual Claw chips JS: with an immediate PC answer and a 150 ms GitHub answer,
  PC was still unpainted at 51 ms because all three responses shared a join.

## Initial UI request ordering

`app.js` originally awaited auth → projects → conversations → Claw run labels
before completing history rendering. Auth events also start device-manager,
alerts/tasks and local-connect reads. Connection chips start devices,
connector status and GitHub status concurrently but originally paint only
after all finish. Claw's main shell itself renders before these reads.
Additional initial reads include product capabilities/auth, PC pairings,
admin session and optional push capability. All can compete for the same
identity and SQLite path. No production timing attribution is inferred from
this static call graph alone.

## Reuse

Use existing ASGI middleware, stdlib ContextVar/SQLite and Uvicorn rather than
adding a telemetry service, database server or process manager. SQLite WAL
supports concurrent committed snapshots for separate readers, while retaining
one writer: <https://www.sqlite.org/wal.html> and
<https://www.sqlite.org/isolation.html>. Worker management reference:
<https://uvicorn.dev/deployment/>. No copied third-party implementation.
