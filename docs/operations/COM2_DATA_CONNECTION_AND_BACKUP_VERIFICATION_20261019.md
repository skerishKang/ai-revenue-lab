# COM2 data connection and backup verification — 2026-10-19

LOCAL A closeout for data, settings, credentials and backup. This record covers
the live encrypted R2 backup path and the prepared Chat D1/R2 bindings. It does
not change Cloudflare production configuration and contains no secret values.

## 1. Live encrypted backup (#5093)

The merged operator path (`scripts/ops/com2_backup.py`, #5117) was run end to end
against the live backup Worker at `https://com2-backup.padiem.net`.

```text
backup_id=20261019t1030z-5093
machine=com2
algorithm=AES-256-GCM key_id=com2-20261019
source_files=15 source_bytes=4263397
payload_bytes=352455
payload_sha256=73565daad31af9f2c4a11a83dc7b55d25141983b6bcacf89cdbaa74e4d7cfcaf
```

| Step | Result |
| --- | --- |
| `inventory` | 15 files, 4,263,397 bytes, 2 secret-content exclusions, no secret paths |
| `backup` | encrypted payload produced; header `PADIEM-CBE1`, not gzip |
| `upload` | `UPLOAD_OK`; Worker produced and stored both artifacts, then verified |
| `verify` | remote payload SHA-256 matched the local manifest |
| `restore-check` | 15 files, 4,263,397 bytes recovered into an empty target |
| independent restore check | 0 file-hash mismatches |
| wrong-key control | `decryption_failed` |

The Worker's capabilities route reports `overwrite_policy=STOP_NO_OVERWRITE` and
`delete_route=false`; no remote object was overwritten or deleted. The key is
stored as `COM2_BACKUP_ENCRYPTION_KEY` in the existing DPAPI store and is never
printed, written to the manifest, or sent to the Worker.

Local artifacts (private):

```text
D:\PADIEM-Servers\backups\com2-backup\20261019t1030z-5093
D:\PADIEM-Servers\backups\com2-restore\20261019t1030z-5093
```

## 2. Prepared Chat D1/R2 binding

Current D1 generation: `20261019T084722757869Z` (Cloudflare remote export,
`production_bound=false`, 57 tables, integrity `ok`, foreign-key violations 0).
A writable COM2 seed was created without modifying the previous seed:

```text
D:\PADIEM-Servers\b62-chat-api\runtime\generation-store\chat-20261019T084722757869Z.sqlite3
bytes=2052096
sha256=5a3fa7395d8b9de419e52e3562274c8b45905bfcd78925b48b8e38b1e08b28b7
```

Current R2 generation: `20261019T005000763982Z` (workspace 40, b66 3, media 105
objects). A read through `r2_staging_config.build_overlay(..., mode=generation)`
matched the generation manifest hash.

A local readiness probe composed the same stores as the Chat generation candidate
and served `GET /health` on loopback:

```text
history_store_bound=true
project_file_store_bound=true
saved_output_store_bound=true
canonical_identity_bound=true
identity_shadow_bound=true
quota_store_bound=true
auth_configured=false
```

`auth_configured=false` is the only remaining gap and is caused by running with
`PADIEM_CHAT_AUTH_MODE=off`, not by the D1/R2 binding.

The current COM2 candidate still pins the previous D1 seed and R2 generation in
`D:\PADIEM-Servers\b62-chat-api\runtime\local_b62_generation.py` (lines 18 and 22).
With staging mode `generation`, the stale R2 check raises
`unexpected_r2_generation`. The current values are published to LOCAL A's
`generation-store\current_generation.json` for the owning runtime worker to
consume. This repository change does not edit that runtime file.

## 3. Cloudflare configuration inventory

A read-only snapshot of the whole account was captured at `2026-10-19T10:13:47Z`:
42 Workers deployed, 5 D1 databases, 4 R2 buckets. Every Worker's current
version, binding names and resource identifiers were recorded; secret values and
plain-text values were dropped by the capture tool. The snapshot is a private
local artifact and is not committed:

```text
D:\PADIEM-Servers\backups\cloudflare-assets\20261019T1013Z-all.json
D:\PADIEM-Servers\backups\cloudflare-assets\INVENTORY_SUMMARY_20261019T1013Z.md
```

An earlier snapshot (`20261019T0055Z.json`) is stale for the current Chat secret
binding names and must not be used as current evidence.

## 4. Backup direction switch (COM2 -> Cloudflare R2)

The client and Worker already support the intended direction: COM2 builds and
encrypts the payload, the Worker stores it under the existing R2 bucket, and
`verify`/`restore-check` read it back. Activation requires only the already
stored write token and encryption key; it does not require a Worker change, DNS
change or traffic change.

Rollback is to stop invoking `upload` from COM2 and keep the existing D1/R2
periodic sync running. No delete or retention route exists, so disabling the
caller leaves the uploaded backup objects intact.

## 5. Owner-only inputs

Three values exist only as Cloudflare secrets and cannot be read back. Register
each once through the DPAPI store with the value on stdin:

```text
PADIEM_CHAT_SESSION_SECRET
PADIEM_CHAT_GOOGLE_CLIENT_SECRET
PADIEM_GITHUB_APP_CLIENT_SECRET
```

After registration, enabling `PADIEM_CHAT_AUTH_MODE=hybrid` with the public base
URL and the public Google client id makes `auth_configured=true` without a code
change. The non-secret values are prepared separately in LOCAL A's private
`com2-env` directory.

B14 provider credentials are already present in the existing DPAPI store. The
GitHub client id and Google client id are public identifiers; their secrets are
not.

## 6. Unchanged scope

- No production D1 restore, schema change or table change.
- No remote R2 object overwrite, delete or retention change.
- No Worker, Secret, DNS or traffic change.
- No secret value was read, printed, committed or uploaded to this repository.
- The previous D1 seed, previous generations and LOCAL B runtime files were not
  modified.
