# COM2 Mesh recovery — boot recovery hardening

Versioned home for the COM1 → COM2 MeshCentral forward and its watchdog. The
running copies were previously unversioned files in the operator profile; this
directory is the source of truth from now on. Nothing here is applied to a
machine by the test suite.

## Files

| File | Role |
|---|---|
| `com2_mesh_recovery.ps1` | Recovery engine: probes, classifies, acts, records |
| `com2_mesh_recovery_selftest.ps1` | Fixture-driven selftest for the engine |
| `background-tunnel.vbs` | Task entry point; owns the wrapper lifetime |
| `padiem-tunnel-wrapper.cmd` | Single-instance guard, start/exit logging, exit code |
| `padiem-tunnel.cmd` | The `ssh -L 4443` forward worker |
| `tests/test_tunnel_launcher.ps1` | Launcher lifetime / exit-code / duplicate-start tests |

## What changed, and what kind of change it is

Split into changes that only alter what is recorded and observed, and changes
that alter recovery behaviour. The first group cannot change any decision.

### A. Observability only (no decision changes)

| Change | Before | After |
|---|---|---|
| Fault clocks | One `first_fault` used for everything | `first_fault` = whole episode; new `class_started_at` / `class_age_sec` = current failure class |
| Engine runtime | `elapsed_sec` ambiguously read as "time to recover" | `elapsed_sec` kept, plus explicit `engine_elapsed_sec` |
| Action timing | none | `action_started_at`, `action_finished_at`, `verify_window_sec` |
| First HTTP 200 | `recovery_at` only | `http200_observed_at`, `http200_first_observed_sec`, `http200_observed_basis` |
| Remote failure | `remote_http=000` left unexplained | `remote_http_reason` = `remote_http_no_response` / `remote_http_code` / `remote_probe_failed` |
| Health log line | 20 fields | Same fields, with the new ones inserted **before** `error=` / `detail=` |

`com2_mesh_down` record-only detail no longer says the keeper and unit "both look
healthy"; it states the HTTP observation and the keeper/unit values it actually
saw. A `000` remote response is never recorded as a stopped unit or a broken
server.

### B. Recovery behaviour changes

| Change | Before | After |
|---|---|---|
| Failed verification | `RECOVERY_FAILED_HTTP_000` immediately, no recheck | `RECOVERY_PENDING_HTTP_000`: bounded wait, rechecked next cycle |
| Pending expiry | n/a | `RECOVERY_FAILED_PENDING_EXPIRED` after `max_pending_seconds` |
| Repeated action | next 5-minute check could act again | a live pending window suppresses a second action |
| Class change | pending verdict silently reused | pending is invalidated (`pending_invalidation=class_changed`) |
| Launcher lifetime | task ended in <1 s, ssh detached | task instance lives exactly as long as ssh |
| Duplicate start | possible (IgnoreNew inert) | IgnoreNew is effective **and** the wrapper holds a lock directory |

## Pending is not success

`recovery_ok = pending` means only this: the action ran and **no HTTP 200 was
observed inside the verification window**. It is not a recovery claim.

* `max_pending_seconds` (default `900`, i.e. three 5-minute cycles) is the
  maximum wait. It is recorded as `pending_deadline`.
* Recheck happens on the next watchdog cycle. A live pending window performs
  **no** new action and records `RECOVERY_PENDING_AWAITING_VERIFY`.
* Failure transition: `RECOVERY_FAILED_PENDING_EXPIRED` once the deadline
  passes without an observed 200. The next cycle may act again.
* The next cycle may observe the 200. That observation becomes
  `RECOVERED_HTTP200_OBSERVED_AFTER_PENDING`, and `recovery_at` /
  `http200_observed_at` are the **observation time**. The true recovery instant
  is unknown and is not back-dated; `http200_first_observed_sec` is an upper
  bound measured from the end of the action.
* If the failure class changes while pending, the pending verdict is discarded
  and the new class starts its own clock.

### Consumer compatibility

The two consumers are operator-side files and are deliberately **not modified**
by this change: `com2-mesh-health.ps1` (maps the engine record into the status
screen) and `com2-mesh-alert.ps1` (alert fan-out).

* All fields the existing consumers read are unchanged in name and type:
  `class`, `com2_ssh`, `tunnel_tcp`, `mesh_http`, `remote_ok`, `remote_http`,
  `remote_keeper`, `remote_unit`, `first_fault`, `attempt`, `planned_action`,
  `action`, `executed`, `recovery_ok`, `recovery_at`, `elapsed_sec`,
  `fault_age_sec`, `code`, `error`, `detail`.
* New fields are additive. `com2-mesh-health.ps1` maps only known fields, so it
  needs no change; it will render `recovery_ok=pending` verbatim.
* `com2-mesh-alert.ps1` never reads `recovery_ok` / `recovery_state`. Its
  `healthy` predicate is the tunnel/HTTP state, not the recovery verdict. While
  an action is pending the path is still `mesh_http != 200`, so alert behaviour
  is **identical** to the previous `RECOVERY_FAILED` path. No alert is sent by
  this change or by its tests.
* The health log line keeps `code=`, `error=` and `detail=` in their previous
  relative order, with the new tokens inserted before them.

## Launcher lifetime contract

```
Task Scheduler (PADIEM-Mesh-Tunnel, MultipleInstances=IgnoreNew)
 └ wscript //B background-tunnel.vbs
    └ Run(wrapper, 0, TRUE)        <- task instance lives as long as ssh
       └ padiem-tunnel-wrapper.cmd  (lock dir, START/EXIT log, exit code)
          └ call padiem-tunnel.cmd
             └ call ssh.exe -N -T -L 127.0.0.1:4443:...   <- exit code
```

Three defects this fixes:

1. `sh.Run(..., False)` detached the forward, so the task finished in under a
   second. `MultipleInstances=IgnoreNew`, `RestartCount=3/PT1M` and
   `LastTaskResult` were all inert, and a dead ssh stayed invisible until the
   next 5-minute check (observed: ssh died 00:58:05, detected 01:00:13).
2. The wrapper logged `%ERRORLEVEL%` of its own `echo`, and the worker's
   `exit /b %ERRORLEVEL%` sat inside a parenthesised block where cmd expands the
   variable at parse time. The ssh exit code never reached the task. Now the
   worker branches with labels and the wrapper does `exit /b %RC%`.
3. A racing or manual start could add a second forward. The wrapper now takes a
   `padiem-tunnel.lock.d` lock and returns `3` with `TUNNEL SKIP
   rc=already-running`.

## M1 — repetition activation (prepared, NOT applied)

The registered `PADIEM-Mesh-Tunnel` task has `interval=PT5M` but `duration=P1D`
from a `2026-10-18` start, so its repetition ended on 2026-10-19 and
`NextRunTime` is empty. Today only the boot trigger and the watchdog's
`Start-ScheduledTask` can start it.

Enabling repetition requires the lifetime and duplicate protections above to be
deployed **first**, otherwise every repetition adds a competing forward:

1. Deploy the three launcher files (see apply plan).
2. Confirm `LastTaskResult` now reflects the ssh exit code and that a second
   start returns `3`.
3. Only then change the trigger, e.g.

```xml
<TimeTrigger>
  <Repetition>
    <Interval>PT5M</Interval>
    <Duration>P3650D</Duration>   <!-- was P1D -->
    <StopAtDurationEnd>false</StopAtDurationEnd>
  </Repetition>
  <StartBoundary>2026-10-18T00:00:00+09:00</StartBoundary>
  <Enabled>true</Enabled>
</TimeTrigger>
```

Applying task XML is an operator action and is out of scope for this change.

## Apply plan (operator, not performed here)

1. Snapshot: copy `C:\Users\limone\Padiem\com2_mesh_recovery.ps1`,
   `padiem-tunnel-wrapper.cmd`, `padiem-tunnel.cmd`, `background-tunnel.vbs`
   to a dated backup directory.
2. Deploy the launcher trio first (low risk, no decision change). Run
   `powershell -NoProfile -ExecutionPolicy Bypass -File tests/test_tunnel_launcher.ps1`
   from the deployed directory and require `FAIL=0`.
3. Deploy `com2_mesh_recovery.ps1`. Run
   `powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_recovery_selftest.ps1`
   and require `FAIL=0`.
4. Verify on the next natural watchdog cycle **without** restarting anything:
   the new fields appear in `com2-mesh-recovery.jsonl`, the existing fields keep
   their names, and `com2-mesh-status.json` still parses.
5. Do **not** shorten the 5-minute interval and do not raise
   `verify_timeout_seconds` in this step. If the window is raised later, the
   ceiling is about 45 s: `com2-mesh-health.ps1` bounds the engine at 90 s and
   the task has `ExecutionTimeLimit=PT2M`, so a longer window turns a slow
   recovery into an `ENGINE_ERROR` with no status file.

## Rollback plan

1. Stop here if any selftest reports `FAIL>0`.
2. Restore the four files from the backup directory (byte-identical originals).
3. The added record fields are additive; the previous engine ignores them, so no
   state-file migration is needed. `com2-mesh-recovery-state.json` written by
   the new engine carries `class_started_at` / `pending_*`; the old engine reads
   only `first_fault`, `last_class`, `last_ts`, `last_code`.
4. To clear a stuck pending state during rollback, delete
   `com2-mesh-recovery-state.json` **only** after confirming no recovery process
   holds `com2-mesh-recovery.lock`.
5. Task XML was not changed by this PR, so no trigger rollback is required.

## Tests

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_recovery_selftest.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tests/test_tunnel_launcher.ps1
```

Both are offline: fixtures and a stub stand-in for `ssh`. Neither opens a
network connection, sends an alert, touches a scheduled task, or starts/stops a
process outside its temporary directory.

## Out of scope

* Applying task XML, changing triggers, restarting or killing any process.
* Raising `verify_timeout_seconds`.
* Adding automatic COM2 unit restart (the existing `restart_mesh_service`
  decision is unchanged and still only reachable when the remote probe reports a
  non-active unit).
* Deciding `com2_mesh_down` from a `000` HTTP code alone.
* Native connector / web UI state work.
