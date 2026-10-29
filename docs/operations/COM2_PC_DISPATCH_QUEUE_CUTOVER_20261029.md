# COM2 PC dispatch queue — installation, cutover and rollback (#5573 / #5881)

Code/runbook only. Nothing below has been executed against 컴2 or Cloudflare by
this PR; the installation and the backend switch each need the Owner's instruction.
The queue exists to move one thing — the atomic claim lane — off the Cloudflare
Python runtime, whose `NoGilError` and `Worker exceeded CPU time limit` failures are
what a PC command dies of today and what a Free plan cannot raise.

References: [host facts](COM2_HOST_FACTS_20261026.md),
[file-lane runbook](FILE_LANE_COM2_RUNBOOK.md),
[Tunnel runbook](COM2_TUNNEL_RUNBOOK.md),
[release and rollback policy](DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md),
[service code](../../apps/padiem-mesh-queue/service.py),
[Chat adapter](../../apps/padiem-chat/app/queue_store_proxy.py).

## 1. What changes hands

Ownership decided as **(가) — the queue owns the pairing and presence state**, not a
second copy of it. One writer per row, so there is no reconciliation to design.

| State | Authority after the switch |
|---|---|
| `oracle_mesh_dispatch` (claim, lease, nonce, consume) | queue |
| `pc_pairing_codes`, `pc_device_links` | queue |
| `mesh_device_presence` | queue |
| `claw_pc_device_selection_store` (preferred PC) | Chat D1 — unchanged |
| conversation rows, R2 originals, result framing (`store_oracle_mesh_command_result`) | Chat Worker — unchanged |

The Chat Worker reaches the queue through one allowlisted store call
(`/internal/store`), and the executor reaches it on the same paths it already posts
to. What is *not* served by the queue is the result submission: framing the answer
and writing the conversation stay in the Worker, which asks the queue only for the
atomic `consume` decision.

Nothing here adds a ceiling to a running command. The claim lease (#5895), renewal
(#5997) and "no time limit on execution" are unchanged; the queue holds a command
open for as long as the PC takes, exactly as the D1 lane does.

## 2. Fixed 컴2 layout

Ubuntu 24.04 under WSL2 with systemd, like the file lane. Loopback only: the
executor is on this host, and the Chat Worker arrives through the tunnel that
terminates here. No public bind address is created at any step.

| Purpose | Path / identity |
|---|---|
| Code and venv | `/opt/padiem/mesh-queue`, `/opt/padiem/mesh-queue/venv/bin/python` |
| Database (SQLite, WAL) | `/opt/padiem/mesh-queue/queue.sqlite3` |
| Private environment | `/opt/padiem/mesh-queue/queue.env`, mode 0600 |
| Channel secret (reused) | `/opt/padiem/oracle-mesh/channel-secret.txt`, mode 0600 |
| Service-to-service secret | `/opt/padiem/mesh-queue/service-secret.txt`, mode 0600 |
| Ownership map | `/opt/padiem/mesh-queue/ownership-map.json` |
| Unit / account | `padiem-mesh-queue.service` / `padiem-mesh` |
| HTTP | `127.0.0.1:8797` |
| Backup | `/opt/padiem/backups/mesh-queue`, `padiem-mesh-queue-backup.timer` at 04:35 |
| Health record | `padiem-mesh-queue-health.timer`, every 5 minutes, journal only |

The executor unit, MeshCentral, the file lane on 8788, SSH and the other tunnel
paths are outside this operation. Do not restart WSL/Windows or those services.

`MESH_QUEUE_CHANNEL_SECRET_FILE` points at the secret the Worker and the executor
already hold. The queue does not mint a third value: three parties with one secret is
the design, and a fourth secret would be a fourth thing to rotate out of step.

## 3. Install the service (no traffic yet)

```bash
sudo bash apps/padiem-mesh-queue/deploy/install.sh
```

The installer is re-runnable and refuses to guess material: it prints
`MESH_QUEUE_STEP=service_secret_missing`, `channel_secret_missing` or
`ownership_map_missing` instead of creating an empty file, then it rsyncs the queue,
links the modules the queue imports (`app`, `padiem_ai_core`, `padiem_control_plane`)
rather than copying them into a shape that can drift, builds the venv from
`requirements.txt`, installs the units and the timer, and answers `/health` once.

Order that matters:

1. The Worker has a route to a loopback service only through the tunnel: one ingress
   rule on 컴2's `cloudflared` maps a hostname to `http://127.0.0.1:8797`. That rule is
   the tunnel lane's own change (COM2_TUNNEL_RUNBOOK), not something this service
   opens — it binds loopback and stays that way. Everything the tunnel does expose is
   guarded by the service secret header, the allowlist and the constant-time compare;
   nothing on the executor's side of the door needs a hostname at all, because the
   executor is on the same host.
2. `provision_service_secret.sh` creates `service-secret.txt` (`umask 077`, mode
   0600). It never prints the value; the same text is handed to the Cloudflare side
   from the file, on stdin, never as a shell argument.
3. The Cloudflare side is set through the deploy gate: `PC_QUEUE_SERVICE_SECRET` (the
   same text), `PC_QUEUE_ORIGIN` (the tunnel hostname, https origin, bare) and
   `PC_QUEUE_BACKEND=d1` so the adapter stays off. A secret is not logged, echoed or
   committed on either side, and neither value is compared by printing it — the Chat
   side's first successful call *is* the verification.
4. `install.sh` runs last, because the service refuses to start without the files.

Then, still with the Chat Worker on `d1`, prove the two halves talk:

```bash
curl -sS --max-time 10 http://127.0.0.1:8797/health
```

`PC_QUEUE_BACKEND` stays `d1` until section 5. A queue that is installed and unused is
the intended state for a day.

## 4. Copy the state, then prove parity

The rows are moved by the code that reads them, not by hand-written INSERTs:

```bash
/opt/padiem/mesh-queue/venv/bin/python copy_state.py copy \
  --source /path/to/d1-snapshot.sqlite --target /opt/padiem/mesh-queue/queue.sqlite3
/opt/padiem/mesh-queue/venv/bin/python copy_state.py diff \
  --target /opt/padiem/mesh-queue/queue.sqlite3
```

`copy` takes each table in one transaction, records a snapshot of every key with its
row hash and timestamp, and refuses to call itself done unless the counts match;
`diff` reads that snapshot back out of the queue database and answers the only
question that matters during a switch — *what did the queue change since I copied* —
as added / removed / changed per key.

The differential gate (`apps/padiem-mesh-queue/tests/test_queue_differential_parity.py`)
runs both authorities against the **same** SQLite file and asserts the same answers,
with the values that legitimately differ (codes, digests, nonces, timestamps, tags)
masked. The scenario the Owner asked to be included, and it is:

**새 PC 원클릭 연결** — handoff/claim a pairing code, watch the executor poll observe
it, and see the PC appear in the device list — must produce the same result on the D1
path and on the queue path. A double-click pairing that completes on one side and not
the other is exactly the drift this gate exists to catch, and it did catch a real one
(a `datetime` reaching the store encoded differently) before any traffic moved.

## 5. Cutover

Only with no work in flight. The predicate is the health read, not a guess:

```
pending_unclaimed == 0 and pending_claimed == 0 and received == 0
```

`received` counts `received` *and* `store_failed`, because both are a result waiting
to land. `pending_claimed` is a command a PC is executing right now — switching while
it is non-zero means the submission may arrive at an authority that never handed the
claim out.

1. Ask the Owner for a quiet window; confirm no PC command is running.
2. `curl …/health` → all three zero. If not zero, wait; do not switch.
3. Re-run `copy_state.py diff` for whatever the queue changed since section 4 and copy
   again, so the queue's last write is the newest state.
4. Set `PC_QUEUE_BACKEND=com2` on the Chat Worker through the deploy gate, publish,
   and confirm the Worker's own start-up line `PC_QUEUE_BACKEND=com2`.
5. Give the executor the queue as its claim lane, in its `executor.env`:

   ```
   ORACLE_MESH_QUEUE_ORIGIN=http://127.0.0.1:8797
   ```

   and restart `padiem-oracle-mesh-executor.service`. Only the claim legs move —
   poll, renew, cancel, busy. The **result submission stays with the Chat Worker**
   (`CHAT_ONLY_PATHS`), because framing the answer and writing the conversation rows
   are not the queue's job. `ORACLE_MESH_CHAT_ORIGIN` keeps its current value, which
   is what makes the rollback in section 6 a one-line removal rather than a
   reconfiguration.
6. Watch for 30 minutes: one short read, one `find` that returns a completed result,
   one pairing. Record the counts before and after.

Steps 4 and 5 are one move, in that order. A queue origin set while the Worker still
reads D1 means the two halves decide from two different copies of the same row: the
claim is handed out of the queue's database while the submission is checked against
D1's nonce, so the work the PC did is refused or, on a row that has drifted the other
way, accepted twice. Whichever way it fails, it fails on a customer's command. The
reverse (Worker switched, executor not) is harmless: the Worker answers the claim lane
from the queue's store through the proxy, which is exactly what the differential test
runs.

The switch is a data-authority change, so it happens when no row is being written by
two parties. A service restart is **not** a cutover event: the claim, the nonce and
`claimed_until` live in the file, so a queue that restarts mid-command hands the same
claim back when the executor renews.

## 6. Rollback

One environment line:

```
PC_QUEUE_BACKEND=d1
```

Set it through the gate, publish, and the Chat Worker composes its D1 stores again —
the proxy is chosen at assembly time, so there is no in-process flag to flip and no
code to redeploy. On the executor, empty `ORACLE_MESH_QUEUE_ORIGIN` and restart: with
no queue origin every leg, the claim included, asks the Worker, which is the lane's
original shape. The queue keeps running; it simply stops being asked. Anything the
queue claimed after the switch stays in its database and is read back with
`copy_state.py diff`, so a rollback loses nothing that was not copied forward again.

## 7. Watchdog, backups and what an operator reads

Three things watch this service, because the service is passive: quiet traffic is
normal, so "no request lately" means nothing.

* In-process: `service.py` asks its own store a health question every
  `LIVENESS_INTERVAL_SECONDS` (60) with a wall-clock bound
  (`LIVENESS_DEADLINE_SECONDS`, 20). The bound is held by a thread waiting on the
  answer, since a SQLite call that blocks inside the engine cannot be interrupted
  cooperatively. Three consecutive failures exit with code **87**, which the journal
  records; a hung process records nothing.
* Out-of-process: `Restart=always`, `RestartSec=10`, `StartLimitIntervalSec=0` — no
  start-rate ceiling, so a service that keeps failing keeps being retried and keeps
  saying so. `MemoryMax=512M` bounds the process, not a command: an OOM-killed queue
  loses no claim, because the lease re-delivers the work exactly as #5895 designed.
* On the host: `padiem-mesh-queue-health.timer` reads `/health` every 5 minutes and
  records the counts. It takes no action — described below, with the reason it is a
  record and not a third restart path.

Daily backup at 04:35 (`padiem-mesh-queue-backup.timer`, `Persistent=true` so a
missed window runs at the next boot):

```bash
systemctl list-timers padiem-mesh-queue-backup.timer
journalctl -u padiem-mesh-queue-backup.service -n 20 --no-pager
```

`backup.sh` uses `VACUUM INTO` — a consistent snapshot taken inside SQLite, not a file
copy that can catch a half-written page while the lane is claiming — then opens the
copy, requires `PRAGMA integrity_check` to say `ok`, prints the four row counts, and
only then rotates. A backup that cannot be opened never replaces one that could.
Seven are kept (`MESH_QUEUE_BACKUP_KEEP`). Restoring is: stop the unit, move the live
`queue.sqlite3` aside together with its `-wal` and `-shm` partners, copy the backup into
place, start the unit, and read `/health` before `PC_QUEUE_BACKEND` is trusted again.
A restore that skips the stop is a restore against a database that is still being
written.

Read-only status has two halves, and the split is the loopback bind. `ops-readonly-status`
probes public health endpoints (`OPS_HEALTH_CHAT_CODE`, `OPS_HEALTH_FILES_CODE`); the
queue deliberately does not join that list, because the only way a GitHub runner could
read `127.0.0.1:8797` is a tunnel hostname in front of the claim lane — and a reachable
`/api/claw/connector/mesh-reads/poll` is the thing being protected. So the queue's own
numbers are recorded on the host instead:
`padiem-mesh-queue-health.timer` runs every 5 minutes, and

```bash
journalctl -u padiem-mesh-queue-health.service -S -12h --no-pager | tail -20
```

answers "was the PC lane alive at 03:40, and was anyone waiting for it" as a read. The
Chat-side half stays visible in the Worker's own start-up line `PC_QUEUE_BACKEND=…`.

The timer takes no action: a wedged process is the in-service watchdog's job and a
crashed one is systemd's, so what it adds is a readable record of the hours around an
incident rather than a guess afterwards.

The executor-side monitoring — poll refusals, queue silence, 1102/1010 detection — is
아스트라1's handover (#82); this lane installs nothing beyond its own `/health`.

The tests that decide whether a switch is allowed run on GitHub, not on a workstation:
`com2-mesh-queue-contract-tests.yml` executes `apps/padiem-mesh-queue/tests` on every PR
touching the queue, the store modules it imports or the migrations it applies. It holds no
credential and makes no network call — a cutover gate that only ever passed on one laptop
is not a gate.

## 8. This week's Chat deploy carries the switch

The next Chat Worker publish is not only the queue adapter. It carries PR-E (#6128)
with **D1 migration 077** (`077_project_files_text_byte_bound.sql`, the
`project_files` CHECK moving to `length(CAST(content_text AS BLOB)) <= 2097152`) plus
#6113, #6119, #6120, #6124, #6116, #6118/#6123/#6125 and PR-B (#6121/#6132).

The order is fixed and is the only dangerous part:

1. `b62-d1-migrate-gate.yml` — the one general D1 migration gate for this database —
   runs `mode=readonly` first (it reads the live binding, the `d1_migrations` ledger
   and the plan for the window), then `mode=apply` with the migration number `077` and
   the authorization phrase the input asks for. **Confirm from its own output that the
   ledger now names 077.** The recorded count and the file count are different numbers:
   077 went in at `B62_D1_PLAN_RECORDED=75` → 76, against 76 migration files in the
   checkout — so read `LEDGER_HAS_077=1` and the ledger's newest name, not a count that
   was predicted. Before any code goes out. A CHECK constraint the deployed code does
   not know about yet rejects writes; a code path that assumes the new bound while the
   constraint is still the old one accepts writes nothing will police. The two gates are
   separate workflows on purpose, so this order is an operator action and not something
   one run can get wrong by itself.
   A shadow rebuild — `INSERT`, `DROP TABLE`, `RENAME`, as 068 and 069 were — carries
   `DROP TABLE`, so the gate refuses it until `allow_table_drop=true` is passed:
   `B62_D1_GATE=FAIL:B62_D1_DROP_GUARD_REFUSED=STOP:<file>` with `PRODUCTION_MUTATION=0`
   is the refusal, not a fault. Grant the flag for that one run and set nothing back.
   Take the export first: `SELECT * FROM <rebuilt table> ORDER BY rowid` plus that table's
   own `sqlite_master` DDL, written 0600 on the host, row count and SHA-256 recorded and
   no content printed. That is the restore material for exactly the object the migration
   rewrites.
2. Then `b62-production-code-deploy-gate.yml` with `mode=deploy_production_code`
   publishes the Worker at the exact main SHA.
3. `PC_QUEUE_BACKEND` stays `d1` in this deploy. The queue is installed and verified
   first (sections 3–4); the switch (section 5) is a separate, deliberate act.

Any single 5xx during the publish stops it: the gate's
`rollback_production_code` returns the previous version and the operator reports,
rather than continuing to a step that looks greener.

### 077 applied — 2026-10-29, and what the record looked like

Run `40813300365` (`mode=apply`, `up_to=077`, `allow_table_drop=true`, exact main). Its
own markers: `PLAN_WINDOW=76 PLAN_RECORDED=75 PLAN_APPLY=1` → `WINDOW_FILES=1
WINDOW_SHA_VERIFIED=PASS WINDOW_APPLIED=1 GATE_APPLY=PASS`, and
`ROW_COUNTS_BEFORE … project_files=14`. The schema diff came back empty in both
directions (`SCHEMA_TABLES/COLUMNS/OTHER _ADDED|_REMOVED`), which is what a rebuild of
one table should look like from outside.

Read-only afterwards: `LEDGER_RECORDED=76`, `LEDGER_HAS_077=1`, newest name
`077_project_files_text_byte_bound.sql`, `CHECK_2MIB_PRESENT=True`,
`CHECK_CHARS_CAP_PRESENT=False`, `project_files=14` — and the row digest of the
re-read table (`1cc5a58a0a482b96…`, 33,054 bytes) is identical to the export taken
before the run, so the rebuild carried every row unchanged. Backups live on 컴2 at
`/opt/padiem/backups/d1-exports/` (root:root 0600): the 14-row JSON export
(`9dfb334113b8d386…`) and the pre-migration DDL of the table plus its two indexes
(`b6f4754b8890de6f…`).

The bound was then read from Production and replayed in a scratch SQLite — production was
not written to test it: 2,097,152 bytes accepted, 2,097,153 refused, 40,001 Korean
characters (120,003 bytes) **accepted**, 699,051 Korean characters (2,097,153 bytes)
refused. Bytes, not characters, which was the point of 077.

One thing the window itself taught: `project_files` went 18 → 14 between two reads
(03:11 and 03:29), and no CI lane did it. The only code that deletes those rows is
authenticated and owner-scoped — `project_files.py:delete_file` reached from the owner's
DELETE route, and the same call as the post-create rollback when the R2 original cannot
be stored, which answers the user with a 503. The lanes running in that window
(`B62 Unified Browser QA`, `B62 Padiem Chat CI`, `Web Desktop Non-Model E2E`,
`COM2 PR Auto Sandbox`) serve their own `uvicorn app.main:app` on `127.0.0.1` with
fixture users, or a Pages preview URL, and `tests/e2e` names no production host — so
none of them can reach the Production D1. A net −4 is also exactly what four uploads that
rolled back would look like to a count taken mid-request: the rows existed only inside
those requests. What would settle it next time is the tail lane run *during* the activity
it is meant to explain — a real-time tail cannot answer for a window it was not open in,
and `request_telemetry` writes to the Worker log channel, which is where the tail reads.

### Time Travel: available, and not reachable with this token

D1 Time Travel is not a paid-only feature; it exists on this plan. What this host's API
token lacks is the permission — `wrangler d1 time-travel info` dies in its pre-flight on
`GET /memberships` (`Authentication error [code: 10000]`, "Unable to retrieve email for
this user"), and the direct REST guesses (`time-travel`, `time_travel`, with and without
`/info`, GET and POST) all return `Route not found` rather than a permission error, so the
path is not even established. Recording a bookmark from automation would need the token to
carry `User Details: Read` plus D1 read/write on the account (`Account D1:Edit`) for the
restore direction. **No token permission was changed here, and none is changed by this
runbook.** Until one is, the export above is the restore material for a rebuild, which is
why section 8 makes it a precondition rather than a nicety.

## 9. What is deliberately not here

* No JS Worker. The `padiem-mesh-channel` port was cancelled: a second
  implementation of a channel that is being moved is a thing to throw away, not a
  thing to test.
* No re-implementation of a rule. `oracle_mesh_read_poll`, `…_renew`, `…_cancel`,
  `…_busy` and the store code are imported as they are; the queue's own files are
  assembly, transport and the allowlist.
* No new confirmation step and no new limit on execution.
* #6073 and the `.ps1` -install / Program Files lane belong to 아스트라1 and
  아스트라3; this runbook does not touch either.
