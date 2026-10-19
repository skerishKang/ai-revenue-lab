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

## Deployment status

Source slice only. The committed config keeps the gate OFF, no Cloudflare
deployment is performed by this change, and no secret is created. The R2
binding reuses the existing private `padiem-workspace-files` bucket under the
`com2-backup/v1/` key prefix, so no new bucket is provisioned.

## Focused tests

```bash
python -m pytest -q apps/com2-backup/tests
python -m pytest -q scripts/ops/tests/test_com2_backup.py
```
