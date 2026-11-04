# Deploy bundle boot tests (#6855)

CI already ran source tests, but a host bundle could still fail on first start
because a module was left out of the staging list, a file was root-only, or the
service account could not read the tree. These jobs build the bundle from the
deploy scripts and boot it from a bundle-only directory as a non-privileged
account.

| Job | Staging source | Boot | Health |
|---|---|---|---|
| `b14-bundle-boot` | `apps/korean-ai-platform/deploy.sh` module loops | Wrangler dry-run outdir, CPython `asgi:app` | `/health` 200 |
| `chat-bundle-boot` | `deploy/host-com2/chat/install.sh` required + symlink lists | `app.local_server` | `/health` 200 |
| `p01-bundle-boot` | `deploy/host-com2/p01/stage_code.sh` (called directly) | `uvicorn asgi:app` | `/internal/v1/health` 200 |

Each job also runs two negative controls against a copy of the same bundle:

1. delete one staged module and require the import to fail;
2. narrow the tree to root-only `0600/0700` and require the service account to
   be denied.

A job fails if a negative control unexpectedly succeeds. This is what proves
the positive result is sensitive to the two failures #6855 records.

## #6855 regression case

The 2026-11-05 00:19 B14 failure cause is still being investigated by
컴2로컬1. When the CTO provides the old/fixed pair, add it as a regression case:

- keep the old bundle shape as a fixture under this directory;
- assert the old fixture fails at boot/import;
- assert the current `deploy.sh` bundle passes.

Until then these jobs are the frame: they already fail for a missing module or
an unreadable bundle, and they name the exact staging source in their output.

## Boundary

- No Cloudflare deploy, no systemd start, no tunnel, no real credential.
  Fake values are generated inside the job (`common.fake_hex`).
- The health wait exists only to let a booting process finish its imports and
  migrations; it is not an application time limit or a size ceiling.
