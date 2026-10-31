# Windows runtime retirement (2026-10-31)

This is a future procedure, not authorization to execute it. Inventory:
`docs/operations/WINDOWS_RUNTIME_RETIRE_INVENTORY_20261031.md`.
PADIEM-Mesh-Tunnel is outside this scope. Confirm task path and action before
any change; an inaccessible or missing task is not proof of a safe shutdown.

| Task | Registration source / role | COM2 replacement |
| --- | --- | --- |
| PADIEM-Local-AI-OnLogon | Registration script not in repository; starts local AI on sign-in. | Chat, B14 and P01 systemd units, restart-policy and boot-recovery; verify actual units. |
| PADIEM-Local-AI-Watchdog | Registration script not in repository; periodically starts local AI. | systemd restart-policy and boot-recovery; verify actual units. |
| PADIEM-COM2-Runtime-Supervisor | `scripts/ops/com2_runtime.py` install-task; supervises Windows runtime. | systemd restart-policy and boot-recovery; verify actual units. |
| PADIEM-COM2-D1-R2-Sync | `scripts/ops/com2_periodic_sync.py`; publishes D1/R2 sync outputs. | No equivalent publisher/timer verified. Do not disable until replacement and consumers are independently verified. |

| PADIEM-COM2-Backup | scripts/ops/com2_backup_schedule.py; schedules COM2 backup. | No replacement verified; preserve pending backup continuity verification. |

## 1. Confirm replacements

On COM2, inspect the installed units and timers with
`systemctl list-units --type=service --type=timer` and
`systemctl show <unit> -p ActiveState -p SubState -p Restart`.
Check the approved health endpoints and the documented boot-recovery status.
Confirm the replacement publisher, its schedule, and downstream inputs before
touching D1/R2 Sync. If verification fails, stop and keep Windows tasks enabled;
rollback at this stage is to leave the current configuration unchanged.

## 2. Disable, do not delete

After separate authorization and recording each exact task path and enabled
state, inspect with `Get-ScheduledTask -TaskName <name>`. Disable only the
approved task with `Disable-ScheduledTask -TaskName <name> -TaskPath <path>`.
Confirm with `Get-ScheduledTask -TaskName <name> -TaskPath <path>`.
To undo, `Enable-ScheduledTask -TaskName <name> -TaskPath <path>` only for a
task that was enabled before this step. Disabling a task does not stop an
already running process.

## 3. Listener confirmation

Run `scripts/ops/windows_runtime_retire_check.ps1` on the authorized target;
check TCP listeners 18764, 18717 and 18731 explicitly. An unknown or
inaccessible result is not a pass. If a listener remains, identify its owner
and stop the procedure; do not terminate an unknown process. If service is
needed again, restore the previously enabled task and follow its documented
startup procedure.

## 4. Observe and preserve rollback

Observe COM2 service health, restart counts and boot-recovery across the
owner-approved observation window. If unhealthy, restore the previously
enabled tasks and use the separately approved traffic/data handback plan.
Do not assume stopping Windows tasks switches traffic or restores data.

## 5. Delete only with separate approval

After the observation window, back up the task definitions, confirm the exact
names and task paths, and obtain separate approval. Only then use
`Unregister-ScheduledTask -TaskName <name> -TaskPath <path>`.
To restore, import the backed-up definition with `Register-ScheduledTask`,
then restore its prior enabled state. Do not delete the sync task without a
verified replacement and verified consumer continuity.
