# COM2 unattended backup operations (2026-10-19)

Scope: #5093 operational closeout. This document covers the unattended runner
added on top of the existing encrypted backup client and Worker. It does not
change the backup Worker, Cloudflare traffic, D1 content or the LOCAL B runtime.

## Existing state before this change

- `PADIEM-COM2-D1-R2-Sync` is a daily **D1 refresh / R2 delta sync** task at
  04:20. It is not a backup task and it does not encrypt or upload backups.
- No scheduled task, cron job or service invoked `com2_backup.py`.
- The encrypted backup path itself was already verified live
  (`20261019t1030z-5093`: 15 files, AES-256-GCM, remote SHA-256 match, restore
  into an empty directory, wrong-key control).

## What the unattended runner adds

`scripts/ops/com2_backup_schedule.py` reuses `com2_backup.py` for archive
build, upload, remote verification and restore checks. It adds:

| Concern | Behavior |
| --- | --- |
| Overlap prevention | `backup.lock` in the state directory; a fresh lock returns exit 3; a lock older than `--stale-minutes` is replaced |
| Retry | Bounded attempts (`--retries`, default 3) only for transport and integrity codes; each attempt uses a new backup id (`-r2`, `-r3`) so the Worker's no-overwrite rule is preserved |
| Success criterion | After upload, the runner downloads the manifest and payload again, recomputes the stored SHA-256, compares it with the local manifest and requires the expected key id. Upload alone is not success |
| Failure record | `backup-status.json` records failed stage, stable error code, `recoverable`, `operator_action_required`, the failed attempt ids, and `consecutive_failures` |
| Last success | `last_success_utc` / `last_success_backup_id` are carried forward across failed runs. `status --max-age-hours N` fails only when that explicit bound is given |
| Generation drift | `--generation-pointer` plus `--generations-dir` resolve the current D1 snapshot from `current_generation.json`; a missing snapshot fails the run instead of backing up an old generation |
| Chat + Engine coverage | The run follows the generation published by the 04:20 sync and requires both D1 seeds to match it before any build: the published `chat.sqlite3` and `engine.sqlite3`. A stale runtime pointer is recorded as `runtime_lag`; an unknown one fails the run |
| Restore verification | `restore-verify` is operator-invoked only. It verifies remote integrity, decrypts, extracts into a throwaway directory, verifies every file hash and then removes that directory |
| Scheduling | `install-task` writes a launcher and registers a Windows task. The time is a required argument; the installer does not choose a cadence |

No retention, storage-class or cost rule is implemented. Local backup
directories are not pruned, and the Worker has no delete route.

## Scheduled execution

The task runs through the existing DPAPI wrapper:

```text
py -3 <secret-store>\store.py run <python> <repo>\scripts\ops\com2_backup_schedule.py run ...
```

The wrapper injects `PADIEM_COM2_BACKUP_WRITE_TOKEN` and
`COM2_BACKUP_ENCRYPTION_KEY` from the user-scoped DPAPI store. Neither value is
placed in the launcher, the status file or the log.

Example registration (dry run first):

```text
py -3 scripts/ops/com2_backup_schedule.py install-task \
  --state-dir D:\PADIEM-Servers\backups\com2-schedule \
  --repo <repo> \
  --endpoint https://com2-backup.padiem.net \
  --key-id com2-20261019 \
  --root "C:\Users\<user>\AppData\Local\Padiem" \
  --root "D:\PADIEM-Servers\b62-chat-api\runtime\generation-store" \
  --root "D:\PADIEM-Servers\.com2-runtime" \
  --generation-pointer "D:\PADIEM-Servers\b62-chat-api\runtime\generation-store\current_generation.json" \
  --generations-dir "D:\PADIEM-Servers\infrastructure\storage-migration\snapshots\generations" \
  --time 05:30 --dry-run
```

The operator chose 05:30 for the initial registration because the established
D1/R2 sync starts at 04:20 and the backup must read the published generation
after that sync. This is a sequencing choice, not a new retention or cost
policy.

## D1 generation coverage

The 04:20 sync publishes `snapshots/current_generation.json` and the matching
`generations/<id>/` directory for `chat` (`padiem-chat-db`) and `engine`
(`padiem-engine`) together. That publication is the handoff the 05:30 run
follows; the backup does not need a manually refreshed runtime pointer to find
the newest pair. Before building, a run validates:

1. the published pointer names both databases and `production_bound` is false;
2. `chat.sqlite3` and `engine.sqlite3` in the generation directory match the
   published byte size and SHA-256;
3. when the runtime pointer names the same generation, the Chat seed it names
   matches the same size and SHA-256.

When the runtime pointer still names an older generation that exists on disk,
the run backs up the published generation and records
`generation.runtime_lag=true` in `backup-status.json`. That is a visible
runtime lag, not a data contradiction. A runtime pointer naming a generation
with no published snapshot fails closed.

`backup-status.json` records the validated pair under `databases` and the
publication/runtime ids under `generation`. Stable failure codes:
`generation_manifest_missing`, `generation_manifest_invalid`,
`generation_pointer_mismatch`, `generation_chat_missing`,
`generation_engine_missing`, `generation_chat_integrity_failed`,
`generation_engine_integrity_failed`, `generation_chat_seed_missing`,
`generation_chat_seed_integrity_failed`, `generation_snapshot_missing`. They
are non-recoverable because a retry cannot fix a stale or incomplete
generation. A failed run keeps `last_success_utc` and
`last_success_backup_id` from the previous good backup.

## Failure handling

- A failed run never stops the runtime, the Worker or the daily D1/R2 sync.
- Missing DPAPI entries, invalid roots or a missing generation snapshot are
  recorded as non-recoverable so the next run does not hide an operator action.
- Network, 5xx/429, transport size and integrity failures are recorded as
  recoverable and retried within the same run.
- A later successful run resets `consecutive_failures` but keeps the previous
  failure fields for audit.

## Operator restore verification

```text
py -3 store.py run py -3 scripts/ops/com2_backup_schedule.py restore-verify \
  --state-dir D:\PADIEM-Servers\backups\com2-schedule \
  --endpoint https://com2-backup.padiem.net \
  --key-id com2-20261019 \
  --backup-id <backup_id>
```

The target is a fresh directory under the state directory. Nothing is restored
over an operational database or over a source root, and the scratch tree is
deleted after the hash comparison. The result is written to
`restore-check-status.json`; it is not scheduled automatically.

## Boundaries

- No Worker, D1, R2-object deletion/overwrite, Secret, DNS, Tunnel or traffic
  change.
- No modification of `D:\PADIEM-Servers\b62-chat-api` runtime files.
- No modification of LOCAL D BYOK code.
- No secret value in source, logs, status files or this document.
