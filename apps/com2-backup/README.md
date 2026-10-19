# COM2 backup transfer Worker (#5093)

Private Worker that stores a COM2 backup archive in the existing R2 service and
lets the operator verify it before a restore. It is the transfer/verification
slice only.

## What this slice does

| Route | Purpose |
| --- | --- |
| `PUT /internal/v1/com2-backup/{machine}/{backup_id}/payload` | Bounded archive upload with `X-Padiem-Content-Sha256` |
| `PUT /internal/v1/com2-backup/{machine}/{backup_id}/manifest` | Validated JSON manifest |
| `GET .../payload`, `GET .../manifest` | Download for a local restore check |
| `POST .../verify` | Recompute the stored checksum and compare it with the manifest |
| `GET /internal/v1/com2-backup/capabilities` | Contract limits only |

The operator-side commands live in `scripts/ops/com2_backup.py`:

```text
inventory     read-only COM2 data/settings/state inventory (no secret values)
backup        build a deterministic payload.tar.gz + manifest.json
upload        upload payload, manifest, then verify
verify        compare the remote payload with the manifest (and optional local copy)
restore-check download, verify, extract into an empty target, verify every file
```

## Encrypted payloads (COM2-side only)

The operator can encrypt the archive before it leaves COM2. The Worker and the
manifest contract stay unchanged: it still stores opaque bytes at the same key
and still verifies SHA-256 over the stored (ciphertext) payload.

- Envelope: `PADIEM-CBE1\n` magic, a 1-byte key-id length, the ASCII key id, a
  12-byte random nonce and the AES-256-GCM ciphertext with its 16-byte tag.
  The non-secret key id is also printed as `key_id=...`.
- AAD binds the header, `machine` and `backup_id`, so a payload cannot be
  replayed under another machine or backup id.
- Keys are 32 bytes, supplied as 64 hex characters or unpadded base64url in
  `COM2_BACKUP_ENCRYPTION_KEY` (`--key-env` overrides the variable name). The
  key value is never printed, written to the manifest or sent to the Worker.
- Store the key in the existing DPAPI secret store and let `run` inject it:

```bash
python D:/PADIEM-Servers/infrastructure/secret-store/store.py run -- \
  python scripts/ops/com2_backup.py backup --out-dir build/com2-backup \
  --key-env COM2_BACKUP_ENCRYPTION_KEY --key-id com2-2026-10
```

- `verify --key-id ...` rejects a payload whose header does not carry the
  expected key id. `restore-check --key-env ... [--key-id ...]` authenticates
  and decrypts before extracting; a missing key, wrong key, wrong key id or a
  broken GCM tag stops the restore before the target is created.
- Payloads without the envelope remain readable, so existing plaintext
  generations and their SHA-256 evidence are unaffected.

## Safety properties

- **Fail closed.** `COM2_BACKUP_ENABLED` must be the literal `"true"` and the
  bearer token must resolve; otherwise every route answers 503/401.
- **No overwrite.** An existing object is never replaced. Identical bytes answer
  `already_present`; different bytes answer `backup_conflict_no_overwrite`.
- **No delete.** There is no delete route and no lifecycle rule.
- **No secret values.** The local inventory emits metadata and hashes only.
  Secret-like paths and files containing high-confidence credential markers are
  excluded from the archive, and the manifest records only exclusion counts.
- **No production database or original-data mutation.** `backup` reads files;
  `restore-check` writes only into an explicitly supplied empty target.
- **No retention or cost decision.** The transfer bound
  (`MAX_PAYLOAD_BYTES`) is a memory-safety limit, not a lifecycle policy.
  `capabilities` reports `retention_policy: "undecided"`.

## Deployment

The Worker deploys with plain `wrangler deploy` from this directory. The
committed config keeps `COM2_BACKUP_ENABLED = "false"`; enabling the transfer
path is a separate, authorized deployment step:

```bash
cd apps/com2-backup
wrangler deploy --var COM2_BACKUP_ENABLED:true
printf '%s' "$COM2_BACKUP_WRITE_TOKEN" | wrangler secret put COM2_BACKUP_WRITE_TOKEN
```

- `routes` exposes only `https://com2-backup.padiem.net` (custom domain,
  bearer-authenticated). `workers_dev` and `preview_urls` stay `false`, so
  there is no `*.workers.dev` or preview ingress.
- `disable_python_external_sdk` makes `from workers import ...` resolve to the
  runtime-provided SDK; without it `wrangler deploy` fails validation with
  `ModuleNotFoundError: workers`.
- Rollback the transfer path by deploying again without `--var`: the committed
  `"false"` gate is restored and every route answers 503.
- The R2 binding reuses the existing private `padiem-workspace-files` bucket
  under the `com2-backup/v1/` key prefix; no new bucket is provisioned.

The COM2 recovery assessment that records this status and the adjacent
Cloudflare asset snapshot procedure is
[docs/operations/CLOUDFLARE_ASSET_RECOVERY_AND_SYNC_20261019.md](../../docs/operations/CLOUDFLARE_ASSET_RECOVERY_AND_SYNC_20261019.md).

## Focused tests

```bash
python -m pytest -q apps/com2-backup/tests
python -m pytest -q scripts/ops/tests/test_com2_backup.py
```

The operator tests need the `cryptography` package (CI installs it explicitly).
