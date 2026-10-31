# COM2 Chat scheduled lane (systemd timer)

The Cloudflare Chat Worker has exactly one cron lane: `worker.py` `Default.scheduled()` →
`run_scheduled_automation_source` (Claw automation tick). This folder prepares the COM2 host
replacement — a `oneshot` service run by a `systemd` timer — without installing, starting or
enabling anything.

**Status: package only.** Nothing here runs on a host until the CTO applies it, and applying it
never starts the timer.

## Reuse, not a second scheduler

| Piece | Source |
| --- | --- |
| The tick itself | `python -m app.local_cron --once` (`apps/padiem-chat/app/local_cron.py`) |
| Entry gate | `PADIEM_CHAT_CPYTHON_HOST=1` (opened by #6356: the host mode no longer needs `PADIEM_LOCAL_DEV`) |
| Automation switch | `PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED` — the same gate `worker.py` reads |
| Config validation | `check_config_cron.py` mirrors `deploy/host-com2/chat/check_config*.py` (booleans only) |
| Injection seam | the `automation_store` / `identity_authority` / `discovery` keywords of `run_scheduled_automation_source` (#6213); the COM2 host will pass its own stores when the P01 transport lands |

The tick currently reports its honest state instead of pretending to run:
`CHAT_LOCAL_CRON=NOT_CONFIGURED reason=p01_engine_transport_unbound`. The timer is still worth
preparing: it is the only moving part of step ⑥ that does not depend on the engine bridge.

## Files

| File | Purpose |
| --- | --- |
| `profiles/staging.conf`, `profiles/production.conf` | the only difference between the two hosts: app/data root, env file, queue port, unit name |
| `padiem-chat-cron.service.template`, `padiem-chat-cron.timer.template` | systemd templates, rendered by the installer |
| `run-cron.sh` | one tick with an overlap lock (`flock -n`) and START/END journal markers |
| `check_config_cron.py` | `ExecCondition`: fails closed when the profile or env shape is wrong |
| `install-cron.sh` | dry-run by default; `--apply` writes units and copies the scripts. Never starts or enables |
| `status-cron.sh` | read-only timer/service/last-tick status |
| `cron.env.example` | names only; the values live in the host env file |
| `cron_parity.json` | the 1:1 job ↔ unit manifest the parity test reads (today: one job, the automation tick) |

## Profiles

| | staging | production |
| --- | --- | --- |
| Unit | `padiem-chat-cron-staging` | `padiem-chat-cron-com2` |
| App root | `/opt/padiem/chat-staging` | `/opt/padiem/chat-com2` |
| Data root | `/mnt/d/padiem/chat-staging` | `/mnt/d/padiem/chat-com2` |
| Env file | `/opt/padiem/chat-staging/.env` | `/opt/padiem/chat-com2/.env` |
| Queue | `http://127.0.0.1:8830` (staging queue) | `http://127.0.0.1:8797` (COM2 queue) |

The staging timer must never point at the production data root or the 8797 queue;
`check_config_cron.py` refuses both, and so does the production profile in reverse.

## Schedule

`wrangler.toml` declares no `[triggers]`/`crons`, so the deployed Cloudflare trigger is owned by
the dashboard, not by source. That means the period cannot be copied from the repository, and this
package does not guess one: `CRON_SCHEDULE` must be supplied at install time and must equal the
deployed trigger read from the dashboard at cutover. Without it the installer refuses:
`CRON_INSTALL=REFUSED reason=CRON_SCHEDULE_REQUIRED`.

A staging timer may run faster than production; only the production value has to match Cloudflare.

Cloudflare cron expressions are UTC. The timer therefore carries `Timezone=UTC`, so the expression
copied from the dashboard keeps the same wall clock instead of shifting by the host's KST offset
(+9h). `Timezone=` needs systemd ≥ 240 (Ubuntu 20.04+). `cron_parity.json` keeps the Worker's
scheduled lane and this package 1:1, and `.github/tests/test_com2_cron_parity_261031.py` fails when
they drift.

## Overlap

Two different overlaps exist and only one is prevented locally:

| Overlap | Prevention |
| --- | --- |
| A COM2 tick still running when the next one fires | `run-cron.sh` takes `flock -n` on `/run/padiem-chat-cron/<profile>.lock` and exits 0 with `CHAT_CRON_RUN=SKIPPED reason=previous_run_active`. `Type=oneshot` is the second guard: systemd will not start the same unit twice |
| A Cloudflare tick running while the COM2 timer ticks | **not preventable by this package.** Order of operations below is the only guarantee |

## Cutover order (no double tick)

1. **Cloudflare side off.** `wrangler.toml` has no `[triggers]` entry, so there are two independent
   levers and both are checked:
   - Worker variable `PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED` is absent or `false` — the scheduled
     handler returns before it touches automation storage. In source the flag is commented out
     (`wrangler.toml` `[vars]`), so read the **deployed** value, do not assume it.
   - the dashboard cron trigger is removed/disabled by the owner of the Cloudflare account.
   Confirmation: no new `claw_runs` / `claw_occurrences` rows attributable to the Worker for one
   observation window (10 minutes), plus the deployed flag readback.
2. **COM2 timer on.** `sudo systemctl start padiem-chat-cron-<profile>.timer` (the installer never
   enables or starts it). Confirmation: `status-cron.sh` shows the timer active and the journal
   shows one `CHAT_CRON_TICK=START` → `CHAT_CRON_TICK=END status=0` pair with a `CHAT_LOCAL_CRON=`
   marker.
3. **Rollback.** `sudo systemctl stop padiem-chat-cron-<profile>.timer` first, then restore the
   Cloudflare trigger and the Worker flag by the normal reviewed deploy. Never restore Cloudflare
   while the COM2 timer is still active.

`status-cron.sh` never changes state; it prints the timer state, the service state and the last
journal lines so both sides of step 1 and 2 can be recorded as evidence.

## Install (not performed by this package)

```bash
sudo bash deploy/host-com2/cron/install-cron.sh --profile staging \
  --schedule '*-*-* *:00/15:00' --dry-run
sudo bash deploy/host-com2/cron/install-cron.sh --profile staging \
  --schedule '*-*-* *:00/15:00' --apply
```

`--apply` writes `/etc/systemd/system/padiem-chat-cron-<profile>.{service,timer}`, copies
`run-cron.sh` / `check_config_cron.py` / `status-cron.sh` into the app root, and runs
`daemon-reload`. It never starts, never enables, never touches Cloudflare, and never edits the env
file it references.

## Not done here

- No install, no start, no enable on any host.
- No Cloudflare change (the trigger and the Worker flag are read-only facts for this package).
- No engine bridge: the tick keeps reporting `NOT_CONFIGURED` until the P01 transport exists.
- No new scheduler logic: the timer only calls the existing `app.local_cron` entry.
