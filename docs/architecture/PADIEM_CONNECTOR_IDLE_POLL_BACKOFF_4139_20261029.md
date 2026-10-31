# #4139 Connector — the idle executor asks the lane less often (2026-10-29 KST)

**Status:** the schedule and its numbers · executor-side only · no Chat route, no queue
route and no dispatch semantics were changed · deployment and executor restart are Qoder's.

## 0. The rule this sits under

Work carries no time ceiling; communication waits do. An idle poll is pure communication,
so it is the thing that may wait longer. Nothing here can delay a command that is already
running, and nothing here shortens a deadline a PC is working against.

## 1. What the loop did, and what it costs

`main()` in `local_agent_oracle_mesh_executor.py` polled, and after a round that returned
nothing it slept **one second** — whatever the lane had said. The lane itself holds a poll
open five seconds and answers the moment a dispatch exists
(`apps/padiem-chat/app/oracle_mesh_read_return_routes.py:1883`, capped to five by #5479
after a twenty-second wait "held a Worker request open … re-reading D1 every couple of
seconds, so concurrent polls piled onto one event loop"), and it re-reads the dispatch
table on a two-second cadence inside that hold (`:1892`).

So one quiet round cost five held seconds plus one second of gap, and up to three table
reads:

| | before | after (settled at rest) |
|---|---|---|
| gap after an empty answer | 1 s, always | 1 → 2 → 4 → 8 → 16 → 32 → 60 s, ceiling 60 |
| period of one quiet round | 6 s | 65 s |
| **polls per minute, one executor at rest** | **10.0** | **0.92** |
| dispatch-table reads per minute | ~30 | ~2.8 |
| meshctrl enumerations per minute (N named devices) | 10·(2N+1) | 0.92·(2N+1) |
| first claim, dispatch arriving mid-gap | ≤ 3 s | ≤ 63 s at the ceiling |

`2N+1` is measured, not inferred: with two named devices and one tagged candidate a single
quiet round ran five full `meshctrl.js listdevices` enumerations, because the beat asks
`is_connected` and `name_of` per device and `pairing_candidates` once, and each of those
starts its own enumeration (`local_agent_mesh_failover.py:518-573`). Bringing that to one
enumeration per round is the second half of this assignment and a separate PR; this row is
the before-number for it.

Ten times fewer rounds, and the same ten times fewer held requests at the edge before the
COM2 cutover — after it, the identical count lands on the loopback queue instead, which
mounts the *same* `oracle_mesh_read_poll` (`apps/padiem-mesh-queue/service.py:71,189`), so
this schedule is what protects the local host too.

## 2. Where the ceiling comes from (it is not a taste number)

The presence beat that tells the server "this executor is alive and this PC was reachable"
**rides the poll body**. Lowering the poll rate therefore lowers the beat rate, and two
existing bounds judge that:

* `MESH_PRESENCE_MAX_AGE_SECONDS = 180` — `apps/padiem-chat/app/claw_local_access_source.py:102`.
  This is a product judgement, not a monitor's: a presence row older than it is not
  treated as a reachable PC.
* `BEAT_STALL_SECONDS = 300` — `.github/scripts/connector_lane_watch.py:59`, whose own
  comment says the product bound is 180 s and the monitor deliberately picks it up later.

A round can leave a beat at most `60 + 5 = 65` seconds old: 2.8× inside what the product
acts on and 4.6× inside what the watch alarms on. That is the whole reason the ceiling is
60 and not 300: nothing in the executor wants to be the reason a PC looks unreachable.
The tests in `apps/korean-ai-code-agent/tests/test_4139_idle_poll_backoff.py` assert both
ratios, so a future change to either bound has to move the ceiling on purpose rather than
by accident.

The cost of the ceiling is the last row of the table: a dispatch that arrives while the
lane is quiet waits up to 63 s (its own gap, then at most one of the lane's two-second
re-checks — never a multiple of either). Inside the hour after traffic stops the gaps
start at 1, 2, 4, 8, 16, so a burst that lands just after work is claimed within about
18 s, and the first claim of a *new* busy period is the only thing that pays the ceiling.

## 3. Which rounds may stretch, and which may not

The loop now reads a field, not a text: `OracleMeshExecutor.last_round` is set by
`run_once()` to `ROUND_IDLE` (the lane answered "nothing waiting"), `ROUND_WORKED` (a
dispatch was claimed — set before the command runs, so a round that dies mid-command still
says the queue was not empty), or `ROUND_SKIPPED` (this host asked for nothing: the
failover gate closed, or a held result is still waiting to be sent).

Only `ROUND_IDLE` buys a longer wait. `ROUND_SKIPPED` and `ROUND_WORKED` reset to one
second, because a skipped round proves nothing about the queue — and the moment that most
needs speed is a failover landing on a host that had been standing by: it must start
claiming on the next second, not the next minute. A channel refusal keeps sleeping the
operator-named `ORACLE_MESH_POLL_SECONDS` (default 5) and also resets, so a lane that will
not complete rounds is never mistaken for a quiet one.

## 4. Interactions checked before writing this

* **Claim lease (60 s, `apps/padiem-chat/app/history.py:38-45`).** A claim whose response
  never arrived is re-offered when `claimed_until` passes; that timer is server-side and
  unchanged. What changes is that the executor may be up to 60 s from asking again, so such
  a re-delivery is *noticed* up to ~120 s after the lost response instead of ~61 s — still
  inside the 600 s dispatch TTL (`oracle_mesh_read_return_routes.py:118`). The Chat-side
  comment that derives the lease "a host … re-requests about a second after an empty or
  dead round" is now stale in its second clause; the value stays right and the comment
  belongs to the cutover lane, so it is recorded here rather than edited from this lane.
* **Owner's stop.** The cancel check runs while a command executes
  (`CANCEL_PATH`, same channel secret), not on the idle cadence, so `그만` reaches a
  running command exactly as fast as before.
* **#82 monitoring.** `connector_lane_watch` reads `lane-status`/`busy` over a *read-only*
  secret and its own `*/10` schedule; it never counts executor polls, so a quieter loop
  does not blind it — the one thing it could trip on is the beat, which is §2.
* **Canary.** `pc_connector_canary.py` submits its own dispatch and waits up to 600 s for
  the result, so its worst case moves from ~3 s to ~63 s of claim latency; its reported
  round-trip will honestly show that if a quiet lane is what it hits.
* **Legacy consumers.** `wait_seconds = 0` when the `X-Oracle-Mesh-Wait` header is absent,
  and `ORACLE_MESH_POLL_SECONDS` still governs a refused channel, so a Chat that answers
  immediately is still awaited at the old interval, not at the ceiling.

## 5. Operator knob, for measurement rather than for behaviour

`ORACLE_MESH_IDLE_POLL_MAX_SECONDS` (default 60, bounded 1…300 like the existing poll
interval). Setting it to `1` reproduces the pre-backoff cadence verbatim — which is how
the two rows of §1 can be compared on a live host instead of only in the test. It is not a
feature flag for behaviour: with the default unset, the behaviour is the schedule above.

## 6. What Qoder should read after the executor is updated

Per executor host, before and after, from the journal:

```bash
journalctl -u padiem-oracle-mesh-executor --since "-1h" --no-pager | grep -c "oracle-mesh-executor"
```

plus the lane's own numbers (Chat Worker request count, or the queue's 5-minute
`padiem-mesh-queue-health` record after the cutover), and one measured dispatch: create a
PC request at a known second after the lane has been quiet for ten minutes and record the
`claimed_until` stamp — that is the real "작업 시작 지연" against the ≤63 s above. If the
beat then reads stale anywhere, the ceiling comes down before anything else does; the
schedule's shape does not.

## 7. The other half of the same assignment: one device table per round

The row above (`2N+1`) is the before-number for the second PR on this lane. A quiet round
with two named devices ran **five** full `meshctrl.js listdevices` enumerations, because
the beat asked `is_connected` and `name_of` per device and `pairing_candidates` once on
top, and each of those starts its own official client on this host
(`local_agent_mesh_failover.py:518-584`).

Now `_PresenceBeat` takes the table once per round and both halves of the beat read it:
the named devices' reachability and names, and the whole table's tagged connected devices
as pairing candidates - the #5573 scope is unchanged, a name without a tag still never
travels.

| | before | after |
|---|---|---|
| enumerations per round, N named devices | 2N+1 (5 at N=2) | 1 |
| at rest (0.92 rounds/min), N=2 | ~4.6 official-client runs/min | ~0.92 |
| during work (10 rounds/min), N=2 | ~50/min | ~10/min |

Two things were kept on purpose:

* the share lasts no longer than the loop's own shortest gap, **and** the round boundary is
  stated out loud (`presence_round_begin`, called before either provider is read). A busy
  lane, which does not sleep between rounds at all, must not report last round's PC as
  this round's answer.
* a presence object that cannot hand over one table is answered `None` and the caller
  falls back to the per-device questions it always had. The beat is evidence; a narrower
  probe is not worth a wrong statement about a machine.

`tests/test_4139_lighter_poll_beat.py` counts the enumerations (11 tests), and the real
`MeshCentralDevicePresence` was measured directly: one run for the shared table, two more
for the two per-device questions it replaced.

## Sources

- `apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py` — the loop,
  `IDLE_POLL_*`, `ROUND_*`, `last_round`.
- `apps/korean-ai-code-agent/tests/test_4139_idle_poll_backoff.py` — the schedule, the
  ratios, and both measured rows.
- `apps/korean-ai-code-agent/tests/test_4139_lighter_poll_beat.py` and `_PresenceBeat` —
  the enumeration count per round, §7.
- `apps/padiem-chat/app/oracle_mesh_read_return_routes.py:1879-1892`,
  `apps/padiem-chat/app/claw_local_access_source.py:102`,
  `apps/padiem-chat/app/history.py:38-45`,
  `.github/scripts/connector_lane_watch.py:55-59`,
  `apps/padiem-mesh-queue/service.py:71,189`.

COM2 local-queue drop-in example: `Environment=ORACLE_MESH_IDLE_POLL_MAX_SECONDS=8` — loopback polling has low overhead; the default remains 60 seconds.
