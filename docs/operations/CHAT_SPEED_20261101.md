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

## Implemented changes and controlled after measurements

Stage 1 published commit: `489a531984ea30d9e83ffe1c875e46c2989c08d1`.
Stages 2 and 3 follow that commit on the same branch; the final report supplies
their published SHA. No production after samples exist for this branch yet.

The session guard and shared-login mapping reuse authority-confirmed results
for 30 seconds, bounded by the source credential expiry. Migration 087 stores
only the verified owner, hashed session key, product user ID and expiry in the
existing Chat SQLite DB. Logout, local session revocation and local permission
changes invalidate entries; a shared revision fence rejects an authority lookup
that started before invalidation. Other users/devices keep their own entries.
Permissions/entitlements themselves remain live. External authority changes
that do not pass through these hooks can remain visible after at most the TTL;
this is a short validity cache, not an authority-change notification channel.
Expired entries are never used as fallback after an identity outage.

The host uses two read-only WAL connections on dedicated threads; the existing
writer lock and atomic batch transactions stay serialized. Only conservative
SELECT statements use the readers. Connection-local queries and writes via
`first()`/`all()` remain on the writer. Each read sees a committed snapshot.

| Controlled local case | Before ms | After ms | Evidence |
|---|---:|---:|---|
| Five reads during a 120 ms writer, mean | 120.580 | 0.878 | Real SQLite WAL, read workers 0 versus 2 |
| Five sequential session checks, total | 126.48 | 29.67 | Fake 25 ms authority; calls 5 versus 1 |
| PC / Drive first paint | 151.7 | 1.6 | Actual chips JS, fake 150 ms GitHub response |
| GitHub first paint | 151.7 | 151.1 | Same JS run; no claim that upstream got faster |

The request fixture benchmark runs SELECT-only handlers on these route
templates, through the actual guard, cache, telemetry and SQLite facade.
It explicitly emits `production_measurement: false`. These are not real
handlers or a replacement for the production top-five table above.

| Fixture request | Before total ms | After total ms |
|---|---:|---:|
| `/api/claw/inbox/{kind}` | 121.08 | 1.72 |
| `/api/claw/local-access/connect` | 121.34 | 1.11 |
| `/api/claw/local-access/devices` | 121.27 | 4.31 |
| `/api/conversations` | 121.53 | 1.04 |
| `/api/projects` | 121.43 | 1.04 |

Before auth was 25.58–26.36 ms and SQLite wait 94.93–95.27 ms; after auth was
0.67–4.10 ms and SQLite wait 0.50–0.76 ms. The warm burst uses zero authority
calls after one explicit warmup, versus five cold calls. Reproduce with
`python scripts/dev/benchmark_chat_requests_261101.py` and
`python scripts/dev/benchmark_chat_sqlite_261101.py --read-workers 2`.
Times vary with scheduler load; correctness tests assert independence/isolation,
not a production speed promise.

Projects/conversations now start together. History paints before optional Claw
labels; navigation waits for the labels when needed to select the correct
product. PC/Drive/GitHub cards and alert/task inboxes paint independently.
These display-only reads have a 3-second deadline covering headers and body.
Prior same-account display may remain after an upstream failure; stale cards
use `unknown` for action decisions. Logout, account switches and 401/403 clear
the display. No deadline was added to a PC tool job, model stream or queue task.
The device manager's existing request/paused-device semantics are preserved;
its duplicate device read is not eliminated by this change.

## Process-state inventory and worker boundary

| State | Shared authority / treatment |
|---|---|
| Verified session/mapping cache | New disposable SQLite table 087; in-process single-flight only coordinates a lookup |
| Running PC jobs, continuations, task progress | Existing SQLite history and production Mesh queue 8797 |
| Session revocation, rate limits, login abuse, inbox, OAuth handoff | Existing durable stores when the production D1 facade is configured; memory stores remain test/no-DB alternatives |
| SSE iterators and per-request tasks | Async request-owned state, no cross-request subscription registry to migrate |
| Edge replay prevention | Existing shared SQLite replay DB; verification moved off the ASGI event loop |
| Object files | Existing disk R2; async writes/deletes offloaded, writes use same-directory atomic replacement |
| Schema startup | Cross-process OS file lock covers migration ledger and scripts, including implicit commits |
| JWKS/DNS caches | Disposable public-data caches, not an authorization source |
| Cron | Existing separate timer, not duplicated per ASGI worker |

The actual Uvicorn spawn supervisor was exercised with 2 and 3 workers, each
handling 60 concurrent atomic SQLite increments with an SSE response held open.
All configured worker PIDs served requests, with no lost/duplicate increments.
Three simultaneous migration processes applied `[0, 0, 2]` scripts, with no
duplicate migration. Async streaming does not occupy a dedicated worker process;
synchronous replay/R2 I/O is now offloaded as well.

Production read-only inspection found the active DB on **9p**, `/opt/padiem`
on **ext4**, and no active Redis service/listener. Keep SQLite. Multiworker
startup rejects 9p, network or unknown filesystems and resolves symlinks/deepest
mounts for both the actual DB file and any explicit replay DB. Default 1 keeps
the existing deployment usable. Code and local tests are ready for 2/3 workers;
the live host is **not yet ready** until the data move and deployment below.
An additional read-only `/proc` snapshot showed the current Chat process at
100,268 KiB RSS (9 threads), with 5,462,848 KiB host memory available out of
8,135,244 KiB. This snapshot is not a peak-memory or multiworker capacity test;
repeat measurement under representative work before increasing workers.

## CTO / COM2 operator application (not executed by this lane)

| Setting | Initial value / meaning |
|---|---|
| `PADIEM_CHAT_AUTH_CACHE_SECONDS` | `30`; `0` disables, supported positive range 1–60 |
| `PADIEM_CHAT_SQLITE_READERS` | `2`; `0` restores serial reads |
| `PADIEM_CHAT_WORKERS` | `1`; measure first, then `2` or `3` on Linux storage |
| `PADIEM_CHAT_LOCAL_DATA_DIR` | Move complete state to `/opt/padiem/chat-com2/data` before multiple workers |
| `PADIEM_COM2_EDGE_REPLAY_DB` | If explicitly set, relocate to Linux storage too |
| `PADIEM_CHAT_SESSION_SECRET` | Keep the existing shared value; multiworker launch requires it, never generates one |

The installer/service/backup configuration accepts the reviewed Linux data path;
the old path stays the default. The installer never copies or relocates data.
An approved COM2 lane must freeze/stop writers, take a verified SQLite-aware
backup, move the complete data directory (DB/replay/object files and ownership),
retain the old rollback copy, update configuration and start with one worker.
Do not copy only a live main DB file while WAL writes continue. Backup unit
reads the existing environment file and follows the selected data directory.
Run migration 087 through the existing startup migration mechanism.
The Claw JS changes also require the approved front static-asset rollout:
`padiem-chat-front/wrangler.toml` binds `ASSETS` to `../padiem-chat/static`, and
the front serves these assets before proxying. Updating only the COM2 checkout
does not publish the new browser JS. CTO must use the existing front deployment
gate with `--keep-vars`; no domain, tunnel, origin or fallback change is needed.

After deploying on one worker, use real Claw initial loads and a signed-in AI
answer to collect stage timings. Then compare 2 and 3 workers under the same
workload, watching memory, DB wait, complete tool jobs and open streams.
No live worker-count change is justified by the synthetic numbers alone.

For a read-only recent request summary (fixed route/status/timing fields only):

```sh
journalctl -u padiem-chat-com2.service --since '2 hours ago' -o cat \
  | python scripts/ops/summarize_chat_latency_261101.py --top 5 --sort max --format markdown
```

The summary tool accepts old and new JSON request events, rejects unknown/raw
paths, and labels missing components unmeasured rather than zero. It reports
mean, max and p95 with status counts. Collect the same window/workload before
and after; return the production component table to CTO once deployed.

## Validation

- Complete Chat suite before installing the optional browser runtime:
  **9,636 passed, 198 skipped, 1 existing failure**;
  94 subtests passed, 221.05 seconds. The sole failure is
  `test_claw_automation_worker_composition.py::test_worker_first_initialization_injects_the_runtime_env`:
  this CPython environment has no `pyodide`. The exact test also fails at the
  same `worker.py:1854` import on isolated base `680e19f8`.
- COM2 Chat packaging: **23 passed**. Shell syntax and diff whitespace pass.
- New behavior coverage includes request/context isolation and frozen canonical
  exception preservation; WAL committed snapshots/atomic writes; owner/session
  cache isolation, expiry, logout/permission invalidation and in-flight fencing;
  initial rendering, stale-display/account boundaries and response-body timeout;
  settings/rollback switches; safe log aggregation; actual 2/3-process request,
  SSE and concurrent migration execution.
- Final cache-off compatibility follow-up: **78 passed**, including three new
  tests proving explicit host cache-off never revives a process-local mapping,
  while the unchanged Worker composition retains its behavior.
- Installed the repository CI-pinned Playwright 1.55.0 and Chromium for a
  supplemental browser run: related UI modules **39 passed**; remaining browser
  modules **321 passed, 16 existing failures, 1 skipped** (592.88 seconds).
  Every failed node also fails on isolated base `680e19f8`: six touch-size checks,
  one home ratio, two device-band checks, one layout shift, three mobile legacy
  panel checks and three import/generation checks. Fifteen error messages match
  exactly; the home ratio has a small pixel float difference and fails the same
  lower bound. The remaining skip requires a hard-coded Windows Chrome path.
  These supplemental counts overlap static checks from the complete suite and
  must not be added to it as a unique total. No new failing behavior remains.
- No workflow dispatch, deployment, service restart, production data move or
  production configuration/secret change was performed. Live effect remains
  unmeasured until the approved COM2 deployment.
