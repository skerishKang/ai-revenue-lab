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

Since #82 the queue also serves the read-only lane-status leg
(`/api/claw/connector/mesh-reads/lane-status`) — the same route function the Chat
Worker mounts, behind a separate read secret (`MESH_QUEUE_WATCH_READ_SECRET_FILE`,
optional). Counters and ages can be handed to a monitor without handing anything that
claims, renews, cancels or consumes.

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
| Its own source | `/opt/padiem/mesh-queue/src` — a worktree of main, see section 3 |
| Database (SQLite, WAL) | `/opt/padiem/mesh-queue/queue.sqlite3` |
| Private environment | `/opt/padiem/mesh-queue/queue.env`, mode 0600 |
| Channel secret (reused) | `/opt/padiem/oracle-mesh/channel-secret.txt`, mode 0600 |
| Service-to-service secret | `/opt/padiem/mesh-queue/service-secret.txt`, mode 0600 |
| Watch read secret (optional) | `/opt/padiem/mesh-queue/watch-read-secret.txt`, mode 0600 |
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

The queue installs from **its own worktree of main**, not from the host's shared
checkout. That checkout (`/opt/padiem/oracle-mesh/repo`) is what the file lane, b14 and
the other units' paths read; moving it forward to today's main would move their running
source as a side effect of installing this one service. A worktree costs nothing to keep
and nothing else to touch:

```bash
sudo -u padiem-mesh git -C /opt/padiem/oracle-mesh/repo worktree add \
  --detach /opt/padiem/mesh-queue/src origin/main
sudo PADIEM_REPO=/opt/padiem/mesh-queue/src \
  bash /opt/padiem/mesh-queue/src/apps/padiem-mesh-queue/deploy/install.sh
```

`install.sh` copies into `/opt/padiem/mesh-queue` with `rsync --delete`, so its own
source — `$ROOT/src` — is excluded from deletion and any other source nested under the
install root is refused before anything moves (`source_nested_refused`). Re-running the
installer is the documented way to pick up a new main: refresh the worktree
(`git -C /opt/padiem/mesh-queue/src fetch && git -C … checkout <sha>`) and run it again.

The installer is re-runnable and refuses to guess material: it prints
`MESH_QUEUE_STEP=service_secret_missing`, `channel_secret_missing` or
`ownership_map_missing` instead of creating an empty file, then it rsyncs the queue,
links the modules the queue imports (`app`, `padiem_ai_core`, `padiem_control_plane`)
rather than copying them into a shape that can drift, builds the venv from
`requirements.txt`, installs the units and the timers, and answers `/health` once.
`MESH_QUEUE_WATCH_READ_SECRET_FILE` is optional and left unset until the monitor's own
install hands that file over (#82): with no file the queue keeps the channel-secret-only
behaviour rather than failing to start a read it cannot serve.

`MESH_QUEUE_REQUEST_LOG` is the store door's own answer to a question this operation has
already had to ask twice: whether a Chat call reached the queue at all. `off` (the written
default) is today's behaviour; `refusals` prints one line per non-2xx answer, so a healthy
lane prints nothing; `all` is for a bounded window during a switch. The line carries five
fields — `path`, the allowlisted method name, `status`, `ms`, and whether the presented
proof matched — and never the secret, the header, the body or any argument, because an
argument can name a customer's path. The installer preserves whatever value `queue.env`
already holds, so a re-install cannot silently turn the instrument back off mid-window.

Restarting the queue is a normal event, and it has not always been. `schema.apply()` used
to run its nine migration files at *every* open, which the files cannot survive: 048 ends
with `ALTER TABLE … ADD COLUMN kind`, and 063 and 070 rebuild their table with `DROP` plus
`RENAME`. A database that had those columns could therefore only ever be opened by a
process that was already running — the first restart of the 컴2 queue after its state copy,
on 2026-10-30, crash-looped on `duplicate column name: kind` and served nobody until the
database was rebuilt from a fresh generation. `queue_schema_applied` is the ledger that
fixes it: each file runs once per database and is recorded, a database built before the
ledger is backfilled rather than replayed, and the shape the stores read is verified at the
end of every open so a tolerated statement can never hide a missing column. An operator
refreshing the worktree to a main that adds migration 075 or later should expect `apply` to
run only the new file; a file that was edited after it ran is skipped and named on stderr,
because that is exactly how the queue would otherwise disagree with D1 about a schema.

Order that matters:

1. `provision_service_secret.sh` creates `service-secret.txt` (`umask 077`, mode
   0600). It never prints the value; the same text is handed to the Cloudflare side
   from the file, on stdin, never as a shell argument.
2. The Cloudflare side is set through the deploy gate: `PC_QUEUE_SERVICE_SECRET` (the
   same text), `PC_QUEUE_ORIGIN` (the hostname section 5 opens, https origin, bare) and
   `PC_QUEUE_BACKEND=d1` so the adapter stays off. A secret is not logged, echoed or
   committed on either side, and neither value is compared by printing it — the Chat
   side's first successful call *is* the verification. `PC_QUEUE_ORIGIN` can wait for
   the cutover step; nothing before it needs the hostname.
3. `install.sh` runs last, because the service refuses to start without the files.

**No tunnel hostname is created in this section.** Installing, verifying `/health` and
copying state all happen on loopback; the only thing that needs a public route is the
Worker's store call, and that opens at cutover with the path restriction in section 5.

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
4. Open the tunnel route **for the store door only**, with the path rule first —
   `cloudflared` matches ingress rules in order and stops at the first hit, so a
   hostname catch-all placed before the path rule would silently expose everything:

   ```yaml
   ingress:
     - hostname: queue.padiem.net
       path: ^/internal/store$
       service: http://127.0.0.1:8797
     - hostname: queue.padiem.net
       service: http_status:404
   ```

   Every other path on that hostname — `poll`, `renew`, `cancel`, `busy`,
   `lane-status`, `/health` — is answered `404` by the tunnel and never reaches the
   process. The claim legs do not need a public route: the executor calls loopback on
   this host, and so does the host-side health/monitor read. Proving it costs one
   request: `curl -s -o /dev/null -w '%{http_code}' https://queue.padiem.net/api/claw/connector/mesh-reads/poll`
   must say 404 before the flag is set, not after.

   *Optional second barrier (Owner decision, applied at this step if chosen):* put a
   Cloudflare Access application on the hostname with a service-token policy — free at
   this scale, and it means a leaked `PC_QUEUE_SERVICE_SECRET` alone is not enough to
   reach the door. The cost is real: the Worker's call then has to present the service
   token headers, which is a code change on the Chat side (`queue_store_proxy`), not a
   config line. Without that change an Access policy would simply break the store call,
   so it must not be switched on beside the running lane.
5. Set `PC_QUEUE_BACKEND=com2` (and `PC_QUEUE_ORIGIN=https://queue.padiem.net`) on the
   Chat Worker through the deploy gate, publish, and confirm the Worker's own start-up
   line `PC_QUEUE_BACKEND=com2`.
6. Give the executor the queue as its claim lane, in its `executor.env`:

   ```
   ORACLE_MESH_QUEUE_ORIGIN=http://127.0.0.1:8797
   ```

   and restart `padiem-oracle-mesh-executor.service`. Only the claim legs move —
   poll, renew, cancel, busy. The **result submission stays with the Chat Worker**
   (`CHAT_ONLY_PATHS`), because framing the answer and writing the conversation rows
   are not the queue's job. `ORACLE_MESH_CHAT_ORIGIN` keeps its current value, which
   is what makes the rollback in section 6 a one-line removal rather than a
   reconfiguration.
7. Watch for 30 minutes: one short read, one `find` that returns a completed result,
   one pairing. Record the counts before and after.

Steps 4 through 6 are one move, in that order. A queue origin set while the Worker still
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

The tunnel route is not part of the rollback. A path-restricted hostname whose only
passable path is a door the Worker stops knocking on carries no traffic, and pulling an
ingress rule is a second live change made while the first is still being judged. Close it
deliberately, later, as its own step.

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
아스트라1's handover (#82). What this lane owes that handover is two things and nothing
more: the queue already answers the read-only `lane-status` leg, and `install.sh` wires
`MESH_QUEUE_WATCH_READ_SECRET_FILE` into `queue.env` when — and only when — the monitor
has put its 0600 file at
`/opt/padiem/mesh-queue/watch-read-secret.txt`. Installing the monitor itself (its
`install.sh`, its `.env`, its own unit) is that lane's script, not this one's.

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

## 9. Retiring the legacy ownership-map lane

The deployment map (`ORACLE_MESH_OWNERSHIP_MAP`) named a Mesh target for a TXT request
before the owner's linked PC did. Its value lives in a write-only store, so a successor
(`…_V2`) cannot be authored by reading it — and history cannot reproduce it either: one
relative path in production already carries two distinct targets, and the map's
`command_exec` grants leave no trace in dispatch rows.

Measured use (2026-10-17 → 2026-10-29, read-only): **40 dispatches** went through the map
lane (7 TXT reads + 33 commands), the last one at **2026-10-20T11:30Z**; every one targeted
the single node that is now an active linked PC, and both kinds of work have a native
route (open the file from 내 컴퓨터 연결; run the command from the same window). No case
was found where the native lane could not do the same job.

The lane is therefore retired by a switch, not by recreating a map:

| Where | Key | Today | Retired |
|---|---|---|---|
| Chat Worker | `ORACLE_MESH_LEGACY_MAP_LANE` | absent / `on` | `off` |
| Queue service | `MESH_QUEUE_LEGACY_MAP_LANE` (installer preserves it) | `on` | `off` |

With `off`:

* a request that names a file for the map is answered **409
  `oracle_mesh_map_lane_retired`** with the sentence "이 방식은 더 이상 쓰지 않아요 — 내
  컴퓨터 연결에서 폴더를 고르세요." — a guidance error, never a 403 about a file that is
  the owner's;
* the channel source composes **without reading an ownership map at all**, so the queue's
  cutover does not wait for a `V2` that nobody will use (`test_the_queue_runs_without_an_
  ownership_map_when_the_lane_is_retired`), and poll/renew/cancel/busy keep working;
* the existing map value is untouched; turning the flag back to `on` is the rollback.

### Turning it off, and what to watch for 30 minutes

1. Chat: set `ORACLE_MESH_LEGACY_MAP_LANE=off` through the deploy gate and publish.
2. Queue: set `MESH_QUEUE_LEGACY_MAP_LANE=off` in `queue.env`, then restart that one unit.
3. Watch, and write the numbers down:
   * count of `oracle_mesh_map_lane_retired` (should appear only for a caller still using
     the old path; zero from the browser lane),
   * PC reads through 내 컴퓨터 연결 (browse → open file): success rate and latency,
   * any new `oracle_mesh_ownership_unverified` 403 (should be zero — that would mean
     something still expects the map),
   * channel 5xx / `exceededCpu` from the tail lane, and the queue `/health` three counts.
4. Rollback: set the flag back to `on` (gate publish; queue `queue.env` + restart). No data
   moves, so the rollback is a configuration change only.

The authored `ownership-map-v2.json` stays at `/opt/padiem/mesh-queue/` as 0600 material,
marked unused beside it; it is never uploaded, and the live `ORACLE_MESH_OWNERSHIP_MAP` is
not overwritten.

## 10. What is deliberately not here

* No JS Worker. The `padiem-mesh-channel` port was cancelled: a second
  implementation of a channel that is being moved is a thing to throw away, not a
  thing to test.
* No re-implementation of a rule. `oracle_mesh_read_poll`, `…_renew`, `…_cancel`,
  `…_busy` and the store code are imported as they are; the queue's own files are
  assembly, transport and the allowlist.
* No new confirmation step and no new limit on execution.
* #6073 and the `.ps1` -install / Program Files lane belong to 아스트라1 and
  아스트라3; this runbook does not touch either.
