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
| Non-actionable class | `record_only` branch kept the old pending verdict and never reset the class clock | class clock resets and the verdict is closed (`class_changed` / `class_not_actionable`) |
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

### Why 900 seconds

`max_pending_seconds` is bounded from both sides by the watchdog cadence, not by
recovery speed.

* **Lower bound: must exceed one watchdog cycle (300 s).** The obligation is
  rechecked on the next `PADIEM-COM2-Mesh-Health` run. A deadline shorter than
  300 s would expire before the next check can possibly observe the 200, which
  would turn every slow-but-successful recovery into a guaranteed failure.
* **900 s = 3 cycles.** One cycle for the recheck, two more for a second chance
  and for jitter in the trigger (`PT5M` + variable probe duration). The one real
  episode on record needed well under one cycle: action at 01:00:16, HTTP 200
  observed at 01:05:06 (293.9 s after the fault was first recorded). 900 s keeps
  a factor of three over the only measured case.
* **Upper bound: alerting latency, not runtime.** A pending verdict costs nothing
  in a run (it performs no action), so the 90 s engine bound in
  `com2-mesh-health.ps1` and the 120 s task limit are unaffected. The cost of a
  larger value is purely how long a genuinely dead forward can sit without a
  failure verdict. 900 s caps that at three cycles while still producing
  `RECOVERY_FAILED_PENDING_EXPIRED` inside a single working session.
* It is **not** a substitute for `verify_timeout_seconds`. The verification window
  stays at its configured 20 s; pending only says what happens after it.

### Pending release conditions

The verdict is released in exactly four ways. Three are automatic and one is an
explicit operator action.

| Condition | Result | `pending_invalidation` |
|---|---|---|
| An HTTP 200 is observed (any later cycle) | `recovered`, `RECOVERED_HTTP200_OBSERVED_AFTER_PENDING` | (empty) |
| The failure class changes | verdict dropped, class clock restarts, next cycle may act | `class_changed` |
| The class stays the same but permits no action (`record_only`) | verdict dropped — the condition that justified the action is gone | `class_not_actionable` |
| The deadline passes with no observed 200 | `failed`, `RECOVERY_FAILED_PENDING_EXPIRED`, next cycle may act | `pending_expired` |
| Operator deletes `com2-mesh-recovery-state.json` after confirming no process holds the recovery lock | verdict dropped | n/a |

"Fault worsens" is the third row. When the probe degrades from an actionable
class (for example `tunnel_broken`) to a class that permits no automatic action
(`com2_ssh_unreachable`, or `com2_mesh_down` with a healthy keeper and unit), the
old pending verdict is closed immediately instead of being carried into a fault
it never described. Both rows are covered by tests.

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

## Install mapping

Every deployed file keeps its current name, so no task action, health script path
or config key changes. The mapping is repo path → operator path, both under the
same directory that `padiem-tunnel-wrapper.cmd` resolves with `%~dp0`.

| Repo path | Operator path | Used by | Deploy order |
|---|---|---|---|
| `scripts/ops/com2_mesh/padiem-tunnel-wrapper.cmd` | `C:\Users\limone\Padiem\padiem-tunnel-wrapper.cmd` | task action (via VBS) | 1 (same step) |
| `scripts/ops/com2_mesh/padiem-tunnel.cmd` | `C:\Users\limone\Padiem\padiem-tunnel.cmd` | wrapper | 1 (same step) |
| `scripts/ops/com2_mesh/background-tunnel.vbs` | `C:\Users\limone\Padiem\background-tunnel.vbs` | `PADIEM-Mesh-Tunnel` task action | 1 (same step) |
| `scripts/ops/com2_mesh/com2_mesh_recovery.ps1` | `C:\Users\limone\Padiem\com2_mesh_recovery.ps1` | `com2-mesh-health.ps1` | 2 |
| `scripts/ops/com2_mesh/com2_mesh_recovery_selftest.ps1` | `C:\Users\limone\Padiem\com2_mesh_recovery_selftest.ps1` | operator test run | 2 |
| `scripts/ops/com2_mesh/com2_mesh_config.template.json` | reference only — the live `com2-mesh-config.json` is **not** replaced | operator | none |
| `scripts/ops/com2_mesh/tests/test_tunnel_launcher.ps1` | any working directory | operator test run | none |

Not deployed by this change: `com2-mesh-health.ps1`, `com2-mesh-alert.ps1`,
`com2-mesh-config.json`, `padiem-tunnel-target.txt`, and the scheduled task XML.

**Config note:** `max_pending_seconds` has a code default of 900. Adding it to
the live `com2-mesh-config.json` is optional and is an operator edit, not part of
this change. If it is added with a value below 300, the deadline can expire
before the next check and every slow recovery becomes a failure.

## Apply plan (operator, not performed here)

Prerequisite: none of these steps restarts the task, a service, a process or the
machine. Each step has an explicit gate; stop at the first failed gate.

**Step 0 — snapshot (required for rollback)**

```bat
set BK=C:\Users\limone\Padiem\backup-20261023
mkdir "%BK%"
copy "C:\Users\limone\Padiem\com2_mesh_recovery.ps1"      "%BK%\"
copy "C:\Users\limone\Padiem\padiem-tunnel-wrapper.cmd"   "%BK%\"
copy "C:\Users\limone\Padiem\padiem-tunnel.cmd"           "%BK%\"
copy "C:\Users\limone\Padiem\background-tunnel.vbs"       "%BK%\"
```

Gate 0: the four files exist in `%BK%` and `certutil -hashfile` compares equal to
the originals.

**Step 1 — launcher trio (no decision change)**

Copy the three launcher files from the repo to `C:\Users\limone\Padiem\`, then:

```powershell
cd C:\Users\limone\Padiem
powershell -NoProfile -ExecutionPolicy Bypass -File tests\test_tunnel_launcher.ps1
```

Gate 1: `LAUNCHER SELFTEST PASS=… FAIL=0`.

**Step 2 — recovery engine**

Copy `com2_mesh_recovery.ps1` and `com2_mesh_recovery_selftest.ps1`, then:

```powershell
cd C:\Users\limone\Padiem
powershell -NoProfile -ExecutionPolicy Bypass -File com2_mesh_recovery_selftest.ps1
```

Gate 2: `SELFTEST PASS=… FAIL=0`.

**Step 3 — passive verification (do not force a cycle)**

Wait for the next natural 5-minute check. Then confirm:

* `com2-mesh-recovery.jsonl` last line parses and carries `recovery_state`,
  `class_started_at`, `class_age_sec`, `engine_elapsed_sec`, `remote_http_reason`;
* `com2-mesh-status.json` still parses and `com2-mesh-health.log` still matches
  `recovery_ok=` and `code=`;
* nothing in the record set disappeared.

Gate 3: all three hold, and the task was never restarted by hand.

**Not in this step:** shortening the 5-minute interval, raising
`verify_timeout_seconds`, enabling the repetition trigger. If the window is
raised later the ceiling is about 45 s: `com2-mesh-health.ps1` bounds the engine
at 90 s and the task has `ExecutionTimeLimit=PT2M`, so a longer window turns a
slow recovery into an `ENGINE_ERROR` with no status file.

## Rollback plan

Trigger any line below; each is independent and none needs a reboot.

1. **Gate failed before any copy** — do nothing; the machine is unchanged.
2. **Gate 1 failed** (launcher) — copy the three launcher files back from `%BK%`.
   The next scheduled start uses the original behaviour. The running ssh forward
   is not touched; it keeps serving until its own `ServerAlive*` settings end it.
3. **Gate 2 failed** (engine) — copy `com2_mesh_recovery.ps1` back from `%BK%`.
4. **Gate 3 failed** (passive verification) — copy both the engine and the
   launcher trio back. The engine reads only `first_fault`, `last_class`,
   `last_ts`, `last_code` from state, so extra keys written by the new engine
   (`class_started_at`, `pending_*`) are ignored. No state migration is needed.
5. **Stuck pending after rollback** — delete
   `C:\Users\limone\Padiem\com2-mesh-recovery-state.json` **only** after
   confirming no process holds `com2-mesh-recovery.lock`. This clears the episode
   and class clocks; the next check starts a new episode.
6. **Task XML** was not changed by this PR, so no trigger rollback is required.

Rollback does **not** need: a reboot, a task restart, a service restart, a
config edit, or a re-registration.

## Required CI

`main` is not covered by classic branch protection (the API returns
`Branch not protected`); enforcement comes from repository ruleset `25431914`,
which requires exactly one status check:

* **`COM2 full policy`** — `strict_required_status_checks_policy: false`.

How that status is produced: `com2-pr-policy-trigger.yml` (job `COM2 policy
dispatch`, no checkout) fires on `pull_request`, which lets
`com2-pr-auto-sandbox.yml` run on the trusted default branch and post
`COM2 full policy` (pending, then success/failure) against the **exact PR head
SHA**.

The sandbox suite runs an explicit list: `docs/operations/tests` plus named
`.github/tests/*.py` files. **The PowerShell suites in this directory are not in
that list.** They are local operator evidence only; CI passing does not prove
them, and they cannot fail CI. Adding them to the COM2 suite is a separate
change.

Other checks on a PR here are non-blocking for this change:
`Operating policy consistency` is skipped for same-repository PRs,
`Pull request contract report` is report-only unless dispatched with
`enforce_pr_contract=true`, and the browser-QA canaries skip on paths that do
not touch their surfaces.

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
