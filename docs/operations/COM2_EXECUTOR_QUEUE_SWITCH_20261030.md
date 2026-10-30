# 컴2 queue switch — the executor side (prepared 2026-10-30, not executed)

One page for the half of the 대기열 전환 that lives on this host: pointing the executor's
queue legs at the loopback service. Nothing in this file has been run. The Chat half
(`PC_QUEUE_BACKEND`, `PC_QUEUE_ORIGIN`, #6216 and its secret) is 아스트라2's, and the
switch itself waits for the CTO's `전환 시작`.

Read the whole operation before step 3: steps 3 and 4 restart the executor, and a restart
during a running command abandons that command's claim until its lease expires.

## 0. What is already true (verified read-only on 2026-10-30, ~07:00 KST)

| Fact | Evidence |
|---|---|
| The queue answers on loopback | `ss -ltn` shows `127.0.0.1:8797`; `curl -s http://127.0.0.1:8797/health` → `{"ok":true,"queue":"mesh","pending_unclaimed":0,"pending_claimed":0,"received":0}` |
| The queue unit is up | `padiem-mesh-queue.service` active since Thu 2026-10-29 18:29:57 KST |
| The installed executor already carries the queue channel | `ORACLE_MESH_QUEUE_ORIGIN` and `_is_loopback_channel_origin` both present in `/opt/padiem/oracle-mesh/kagent-src/kagent/local_agent_oracle_mesh_executor.py` (87,782 bytes, mtime 2026-10-29 14:42) |
| That file is the one the service imports | `executor.env` sets `PYTHONPATH=/opt/padiem/oracle-mesh/kagent-src`, and the venv resolves `kagent.local_agent_oracle_mesh_executor` to exactly that path |
| A loopback origin is legal there | the installed code accepts `http://` only for `127.0.0.1`, `::1`, `localhost`; every other origin must be https |
| No queue value is set on the host today | `grep -i queue /opt/padiem/oracle-mesh/executor.env` → nothing |
| Poll cadence in effect | `ORACLE_MESH_POLL_SECONDS=5` (#6212's adaptive cadence is *not* in the installed copy) |

So the switch is a configuration change on a service that already understands it — no code
refresh is a prerequisite. Re-run the two `grep -c` checks above if the executor is
refreshed between now and the switch; a copy that lacks them must be refreshed first.

## 1. Which leg moves, and which does not

`_origin_for(path)` sends every executor leg to the queue **except** the result:

| Leg | Path | After the switch |
|---|---|---|
| poll (claim) | `/api/claw/connector/mesh-reads/poll` | `http://127.0.0.1:8797` |
| lease renew | `/api/claw/connector/mesh-reads/renew` | `http://127.0.0.1:8797` |
| cancel check | `/api/claw/connector/mesh-reads/cancel` | `http://127.0.0.1:8797` |
| busy | `/api/claw/connector/mesh-reads/busy` | `http://127.0.0.1:8797` |
| **result submit** | `/api/claw/connector/mesh-reads/result` | **unchanged — `https://chat.padiem.net`** |

Framing the answer and writing the conversation stay in the Worker (that was the ownership
answer (가)); the executor only asks the queue for the atomic consume decision. Measure
submit failures separately from claim failures after the switch, exactly as the cutover
runbook says.

## 2. Order: Chat first, executor second

**Judgement — switch the Chat backend before the executor, never the other way round.**

`PC_QUEUE_BACKEND=com2` does not merely move where a dispatch is *written*. The Worker
wraps its history store in `QueueForwardingHistoryStore`, and the dispatch names it
forwards include `oldest_pending_oracle_mesh_dispatch`, `claim_oracle_mesh_dispatch`,
`renew_oracle_mesh_claim`, `consume_oracle_mesh_dispatch` and the cancel pair — which is
exactly the pair the poll route calls (`oracle_mesh_read_return_routes.py:1926,1937`). So
after the Chat switch the Worker still answers the executor's poll; it just answers it
*from the queue*. Nothing the executor does has to change at that moment, and the lane keeps
working with one extra hop.

The reverse order is an outage, not a delay: an executor polling a queue that nobody writes
to finds nothing, while the Worker goes on writing new dispatches to D1. Commands would sit
unclaimed until the second switch lands, and every dispatch created in that window is a
customer-visible hang.

Safe sequence:

1. Chat deploy with `PC_QUEUE_BACKEND=com2`, `PC_QUEUE_ORIGIN=https://queue.padiem.net`,
   `PC_QUEUE_SERVICE_SECRET` (#6216 merged, secret written at that deploy, value piped from
   the file — never printed).
2. Prove the lane still works with the *executor untouched*: one real PC command completes
   end to end. This is the step that isolates "the queue is the authority now" from "the
   executor changed too".
3. Then the executor legs (this page, steps 3–4 below).
4. Observe 30 minutes.

## 3. Put the value on the service (a drop-in, not the env file)

Exact location — the unit already has a drop-in directory, created for the restart policy:

```
/etc/systemd/system/padiem-oracle-mesh-executor.service.d/padiem-restart.conf   (exists)
/etc/systemd/system/padiem-oracle-mesh-executor.service.d/padiem-queue-origin.conf   (new)
```

Content — four lines, and the value is not a secret (a loopback address, no credential):

```ini
# /etc/systemd/system/padiem-oracle-mesh-executor.service.d/padiem-queue-origin.conf
[Service]
Environment=ORACLE_MESH_QUEUE_ORIGIN=http://127.0.0.1:8797
```

```bash
sudo install -m 0644 -o root -g root /tmp/padiem-queue-origin.conf \
  /etc/systemd/system/padiem-oracle-mesh-executor.service.d/padiem-queue-origin.conf
sudo systemctl daemon-reload
```

Why the drop-in and not `executor.env`: the env file is the deployment's own config and is
the thing a refresh rewrites (there are already `executor.env.pre-*` backups on the host
from exactly that), while a drop-in is the host-level override systemd is designed for and
is the pattern this unit already follows. A rollback of one file that no installer knows
about is a rollback that cannot be undone by a refresh.

`daemon-reload` alone does not move a running process. The value is live only after the
restart in step 4.

## 4. Restart and prove it

```bash
sudo systemctl restart padiem-oracle-mesh-executor.service
```

Four checks, in this order, all read-only:

1. **The value is in the process**, not just on disk:
   `systemctl show -p Environment --value padiem-oracle-mesh-executor.service` → the line
   contains `ORACLE_MESH_QUEUE_ORIGIN=http://127.0.0.1:8797`.
2. **The leg is actually loopback** — with a 5-second cadence, a 25-second sample is enough:
   ```bash
   timeout 25 ss -tntp state established '( dst 127.0.0.1:8797 )' | grep -c oracle-mesh
   ```
   A non-zero count is the direct answer to "is the poll going to the queue?" — the queue
   runs uvicorn with `log_level=warning`, so there is *no* per-request access line to count,
   and the executor does not log which origin a request used. If the CTO wants that to be a
   one-line journal grep instead, it is a small PR (a startup line naming the channel); not
   run without it.
3. **The queue is being read**: `curl -s http://127.0.0.1:8797/health` before and during a
   real PC command — `pending_claimed` goes to 1 while the command runs and back to 0 when
   the result lands.
4. **The end-to-end lane**: one command on one PC, and its answer in the conversation. The
   executor's own proof lines are
   `journalctl -u padiem-oracle-mesh-executor.service --since "-10 min" | grep oracle-mesh-command`
   (`phase=...`, never customer text) and the submit line
   `grep "result ok="`.

Where to look when something is wrong:

| Thing | Where |
|---|---|
| executor | `journalctl -u padiem-oracle-mesh-executor.service` |
| queue process | `journalctl -u padiem-mesh-queue.service` (watchdog and start/stop lines only — request logging is off by design) |
| queue health record, every 5 min | `journalctl -u padiem-mesh-queue-health.service` |
| queue backup | `journalctl -u padiem-mesh-queue-backup.service`, files in `/opt/padiem/backups/mesh-queue` (0700 `padiem-mesh`, 7 kept) |
| the rows themselves | `/opt/padiem/mesh-queue/queue.sqlite3` — open read-only: `sqlite3 "file:/opt/padiem/mesh-queue/queue.sqlite3?mode=ro" ...`, never a write |

## 5. One line back

```bash
sudo rm /etc/systemd/system/padiem-oracle-mesh-executor.service.d/padiem-queue-origin.conf \
  && sudo systemctl daemon-reload && sudo systemctl restart padiem-oracle-mesh-executor.service
```

Roll back only when `curl -s http://127.0.0.1:8797/health` shows `pending_claimed` and
`received` both at 0. A command whose claim the queue holds renews at the queue; if the
executor goes back to the Worker mid-flight, that renewal asks a different authority and the
running command loses its lease — which is exactly the race the zero-flight rule in the
cutover runbook exists to prevent. Keep the removed file rather than losing it
(`mv … /root/padiem-queue-origin.conf.removed-$(date +%s)`) so a second attempt is the same
four lines, not a fresh guess.

## 6. The baseline this should improve (measured 2026-10-30 07:05 KST)

The Cloudflare leg is not reliable today, which is the argument for the switch:

| Window | Refusals | Attempts at 5 s | Rate |
|---|---|---|---|
| last 10 min | 6 | ~120 | 5.0% |
| last 30 min | 25 | ~360 | 6.9% |
| last 60 min | 204 | ~720 | **28.3%** |

`journalctl -u padiem-oracle-mesh-executor.service | grep -c "chat channel refused the
poll"` — bursty, not constant: a burst around 06:00–06:35 KST, then near-silent minutes.
The same refusals were present on 2026-10-29 from 06:53 KST onward, so this is not new with
the queue work, and no dispatch was created after 2026-10-29 07:27:35Z so nothing was
customer-visible this morning. This is #82's evidence and part of #84's measurement: the
monitoring PR should read the same counter, and after the switch the poll/renew/cancel/busy
legs stop crossing the internet while the result leg keeps doing so — which is why the two
must be counted separately.

## 7. Deliberately not here

- No ceiling is added to a running command by any of this. The claim lease (#5895), the
  renewal (#5997) and "no time limit on execution" are unchanged.
- The queue's public ingress, the service token, the ownership map retirement and the D1
  state copy belong to `COM2_PC_DISPATCH_QUEUE_CUTOVER_20261029.md`.
- Nothing in this file was executed. Running it requires `전환 시작`.
