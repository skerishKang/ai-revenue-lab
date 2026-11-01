# COM2 Chat staging package (port 8801)

This package is the execution base for plan ①-1 in
`docs/operations/CHAT_COM2_MIGRATION_RESUME_PLAN_20261031.md`. It is a staging
profile of the existing `deploy/host-com2/chat` package, not a second app.

**Status: package only.** This PR does not install, start, enable, or expose
anything. The CTO decides when to install and start it.

## What it runs

| Item | Value |
| --- | --- |
| Unit | `padiem-chat-staging.service` |
| Listener | `127.0.0.1:8801` (loopback only) |
| App root | `/opt/padiem/chat-staging` |
| Data root | `/mnt/d/padiem/chat-staging` (staging SQLite + objects) |
| Queue | `http://127.0.0.1:8830`, unit `padiem-mesh-queue-staging.service` |
| Queue secret | path only: `/opt/padiem/mesh-queue-staging/service-secret.txt` |
| Shared login | `PADIEM_CHAT_SHARED_LOGIN_ENABLED=true` (staging profile) |

The staging data root is separate from the production `/mnt/d/padiem/chat-com2`.
The queue is the staging queue on 8830; the production queue on 8797 is never
used. The staging DB starts empty (or from an approved D1 copy later); this
package does not read or write production D1.

## Files

- `padiem-chat-staging.service` — systemd unit template.
- `start-staging.sh` — starts only this unit, checks 8801 and the 8830 queue,
  then calls the loopback health check.
- `stop-staging.sh` — stops only this unit; never disables it.
- `status-staging.sh` — read-only unit/health/queue status.
- `.env.staging.example` — names only; copy to `/opt/padiem/chat-staging/.env`
  (0600) and fill. Never commit or print values.
- `check_config_staging.py` — `ExecCondition`; fails closed on a bad staging
  shape and never prints a value.
- `install-staging.sh` — dry-run by default; `--apply` installs files and the
  unit, creates the venv/data root, and runs `daemon-reload`. It never starts
  or enables the unit, never changes the queue unit, and never touches the
  tunnel/Cloudflare.

## Preconditions

1. Port 8801 is free on both WSL and Windows (the plan's port table).
2. `padiem-mesh-queue-staging.service` is active and its `/health` is ok.
3. The service user `padiem-chat` can read the queue secret file. The
   installer checks readability as that user but does not change the file's
   owner or mode.
4. The staging auth client registration and any public staging hostname are
   owned by the auth/entry lanes. Do not reuse production auth values.

## Install (not performed by this PR)

```bash
sudo bash deploy/host-com2/chat/install-staging.sh --dry-run
sudo bash deploy/host-com2/chat/install-staging.sh --apply
sudoedit /opt/padiem/chat-staging/.env   # fill names; keep mode 0600
```

`--apply` does not start the service. Fill `PADIEM_CHAT_AUTH_MODE` and the
session secret before starting.

## Start, stop, status

```bash
sudo /opt/padiem/chat-staging/start-staging.sh
sudo /opt/padiem/chat-staging/stop-staging.sh
/opt/padiem/chat-staging/status-staging.sh
```

`start-staging.sh` fails if the 8830 queue unit is not active, if 8801 is
occupied, if `check_config_staging.py` says no, or if the loopback `/health`
does not answer. It never enables the unit. `stop-staging.sh` never disables
it. Neither script restarts or changes the queue.

Manual status equivalents:

```bash
systemctl is-active padiem-chat-staging.service
systemctl is-active padiem-mesh-queue-staging.service
/opt/padiem/chat-staging/venv/bin/python /opt/padiem/chat-staging/health.py \
  --url http://127.0.0.1:8801/health
```

## Queue contract

The package sets:

```text
PC_QUEUE_BACKEND=com2
PC_QUEUE_ORIGIN=http://127.0.0.1:8830
PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP=1
PC_QUEUE_SERVICE_SECRET_FILE=/opt/padiem/mesh-queue-staging/service-secret.txt
```

The queue client is https-only by default. The staging profile opts in to a
bare loopback http origin; only `127.0.0.1`/`localhost`, an explicit port, and
no path/userinfo/query are accepted. The service reads the secret value from
the named file at boot; the value is never written to the env file or printed.
`check_config_staging.py` rejects an inline `PC_QUEUE_SERVICE_SECRET`, a
non-8830 origin, and an unreadable file.

The CPython host wires the queue-backed pairing, presence, and dispatch
history stores only when `PC_QUEUE_BACKEND=com2`. With the switch absent it
keeps the existing D1 path, so the production profile is unchanged.

## Shared login (staging gap)

The staging profile turns the flag on, but the current shared-login flow still
hardcodes `client_id=b62` and the production callback
`https://chat.padiem.net/auth/shared/callback`, and the CPython host does not
mount the shared-login routes. The `b62-staging` client registration, callback
and client-id parameterization are auth-lane work. Until that lands, this flag
does not make the staging login flow work, and this package must not be
pointed at production auth values.

This is the known gap between plan ①-1 (package) and the ① completion criterion
(login through a padiem-auth staging client). It is recorded here rather than
hidden behind a passing config check.

## Staging database from the daily sync generation

An empty `chat.sqlite3` verifies the wiring but not the data. The 04:20 sync
(#5508) already publishes one immutable generation per day, so the staging
database is built from `snapshots/current_generation.json` →
`snapshots/generations/<generation>/chat.sqlite3` on the COM2 host
(`D:\PADIEM-Servers\infrastructure\storage-migration\snapshots`):

```bash
python3 .github/scripts/chat_staging_db_from_generation.py \
  --pointer "D:/PADIEM-Servers/infrastructure/storage-migration/snapshots/current_generation.json" \
  --generations-dir "D:/PADIEM-Servers/infrastructure/storage-migration/snapshots/generations" \
  --out /mnt/d/padiem/chat-staging/chat.sqlite3
```

The tool prints counts and a parity verdict only, opens the generation
read-only, and refuses when `chat_copy_parity` against that generation is not
`MATCH`. Two extra refusals matter here: the generation's `d1_migrations`
ledger must match `apps/padiem-chat/migrations` (001–080), and the output must
not already exist unless `--force` is passed.

Queue-authority and broker tables are copied **empty**: the staging queue on
8830 owns pairing/presence/dispatch, and Stage 2-C owns `local_agent_*`, so
production pairing codes, presence rows and command material never land in the
staging root. The local migration ledger is seeded from the export, so the
service starts on the copied schema instead of replaying 001–080 over
populated tables.

## Rollback

Stop the unit with `stop-staging.sh`. Do not disable or delete the queue unit.
The staging data root can be left in place or removed by the CTO after the
staging window; this package never deletes files.
