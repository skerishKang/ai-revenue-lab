# PC user helper EXE release procedure (2026-11-07)

> Source-only procedure for `#7117` PR-4. This PR does **not** upload an EXE,
> change a Worker variable, create a bucket, or deploy anything. The CTO runs
> the commands below after the merge order is complete.

## Decision: where the helper EXE is served

The helper EXE is served from a **dedicated public Cloudflare R2 Standard
bucket with a custom download domain**:

| Item | Value |
| --- | --- |
| Bucket | `padiem-pc-helper-releases` |
| Public origin | `https://downloads.padiem.net` |
| Object key | `pc-helper/<CONNECT_VERSION>/padiem-user-helper.exe` |
| Example | `https://downloads.padiem.net/pc-helper/0.3.0-rc1/padiem-user-helper.exe` |
| Checksum object | same key + `.sha256` |
| Cache | `public, max-age=31536000, immutable` |

This follows the repository's existing distribution policy for Windows release
binaries: immutable, version-named objects on R2 with a custom domain, never
the application Worker, D1, or a website host
(`docs/operations/PADIEM_CONNECTOR_INSTALLER_DISTRIBUTION_20261015.md`, decision 2).
The example domain in that document was explicitly unclaimed; this PR makes it
the chosen target and treats its creation as a CTO prerequisite, not as an
already-live fact.

Why not the alternatives:

- **MeshCentral** (`PC_AGENT_INSTALL_URL`, `apps/padiem-chat/wrangler.toml:199`)
  serves the MeshAgent installer, not arbitrary release artifacts. It is not a
  general upload host and offers no versioned helper path.
- **Worker assets** would require the reviewed EXE to enter exact-main source or
  the generated assets bundle on every deploy. Repository policy keeps the
  generated helper out of Git (`.gitignore`, `#7108` entry) and the B62 gate
  deploys exact main; adding a binary would make the artifact a second source of
  truth that can drift.
- **GitHub Releases** is not guaranteed anonymous for a private repository and
  is not the existing PADIEM distribution host.

## Where the two values go (file:line)

The values are **plain-text variables of the `padiem-chat` Cloudflare Worker**,
not COM2 environment settings.

| Location | Role |
| --- | --- |
| `apps/padiem-chat/wrangler.toml:207` | declares `PC_USER_HELPER_INSTALL_URL` |
| `apps/padiem-chat/wrangler.toml:208` | declares `PC_USER_HELPER_SHA256` |
| `apps/padiem-chat/worker.py:1695-1700` | reads both into `pc_pairing_user_helper_url` / `_sha256` |
| `.github/workflows/b62-production-code-deploy-gate.yml:140-144` | `set_var` workflow input for explicit overrides |
| `.github/scripts/b62_cloudflare_production_deploy_config.py:248-265` | merges `set_var` over live plain-text values; values are never emitted |
| `apps/padiem-chat/app/local_cpython.py:641-647` | optional local/COM2 development read; not the production authority |

`PC_AGENT_INSTALL_URL` remains the MeshCentral URL at
`apps/padiem-chat/wrangler.toml:199` and is **not changed** by this release.

The values are injected at deploy time and are never committed. The B62 gate
preserves existing live plain-text values unless an explicit `set_var` changes
them, so the release command must send both names together.

## One-time prerequisites (CTO)

Run these once, from an authenticated `wrangler` session with access to the
PADIEM Cloudflare account:

```powershell
wrangler r2 bucket create padiem-pc-helper-releases
```

Then, in Cloudflare Dashboard → R2 → `padiem-pc-helper-releases` → Settings →
Custom Domains, connect `downloads.padiem.net`. Cloudflare creates the DNS
record for the same zone. Do not use the `r2.dev` development endpoint for a
production install link.

Required local tools:

- `wrangler` authenticated (`wrangler whoami`);
- `gh` authenticated with workflow dispatch permission (`gh auth status`);
- `python` and network access for the PyInstaller build;
- a checkout of `main` that contains `#7117`.

## Release: build → upload → verify → set both Worker values

From the repository root, after `#7117` is merged into `main`:

```powershell
git fetch origin main
powershell -NoProfile -ExecutionPolicy Bypass `
  -File apps/claw-connect/release-windows-helper.ps1 `
  -TargetSha (git rev-parse origin/main)
```

The script does all of the following:

1. Runs `apps/claw-connect/build-windows-helper.ps1` and reads its JSON receipt
   (version, byte length, SHA-256, source SHA).
2. Uploads `pc-helper/<version>/padiem-user-helper.exe` and its `.sha256`
   sidecar to `padiem-pc-helper-releases` with the immutable cache policy.
3. Downloads the public URL again and compares the served SHA-256 and byte
   length with the built artifact. It stops before any Worker change on drift.
4. Dispatches `b62-production-code-deploy-gate.yml` with:

   ```json
   {
     "mode": "deploy_production_code",
     "target_sha": "<origin/main 40-hex>",
     "confirmation": "DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN",
     "set_var": {
       "PC_USER_HELPER_INSTALL_URL": "https://downloads.padiem.net/pc-helper/<version>/padiem-user-helper.exe",
       "PC_USER_HELPER_SHA256": "<lowercase sha256>"
     }
   }
   ```

5. Waits for the B62 gate unless `-NoWait` is passed, and fails the local
   command if the gate fails.

Dry run first; it performs no network mutation and prints the exact plan:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File apps/claw-connect/release-windows-helper.ps1 -DryRun
```

Expected markers on success:

```text
HELPER_RELEASE_R2_VERIFIED=PASS
HELPER_RELEASE_DEPLOY=DISPATCHED
HELPER_RELEASE_DEPLOY=PASS
```

The B62 run log must also show its existing production proof, including
`B62_DEPLOY_LIVE_PREREQ=VERIFIED` and `B62_PRODUCTION_SMOKE=PASS`.

## Post-release verification

1. `GET` the versioned URL and check the SHA-256 against
   `HELPER_RELEASE_SHA256`; the `.sha256` sidecar is public for independent
   comparison.
2. Confirm the B62 run completed on the exact `TargetSha`, not a later main.
3. As a signed-in owner, request `/api/pc/pairings/install-file` and confirm the
   response contains `PADIEMHELPERURL:` and `PADIEMHELPERSHA:` with the released
   values. The one-click `.exe` trailer carries the same pair.
4. Run one real one-click install on a Windows PC and confirm the helper task is
   registered and the executor reaches the user-session pipe. A served file and
   a green deploy are not by themselves proof of the installed helper.
5. Record the version, URL, SHA-256, byte length, R2 key, B62 run ID and source
   SHA in the release evidence.

## Rollback

The object keys are immutable. To roll back:

1. Keep the previous version's URL and SHA-256 (they remain served).
2. Re-dispatch the B62 gate with the previous pair, without rebuilding or
   repacking under the same version name:

   ```powershell
   gh workflow run b62-production-code-deploy-gate.yml --ref main `
     -f mode=deploy_production_code `
     -f target_sha=<current-main-40hex> `
     -f confirmation=DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN `
     -f set_var='{"PC_USER_HELPER_INSTALL_URL":"<previous-url>","PC_USER_HELPER_SHA256":"<previous-sha>"}'
   ```

3. Re-check the installed PC. A variable rollback does not uninstall or replace
   an already-downloaded helper; the next one-click install is the update path.

## Evidence state in this PR

```text
HELPER_RELEASE_HOST=R2_CUSTOM_DOMAIN_SELECTED
HELPER_RELEASE_BUCKET=padiem-pc-helper-releases
HELPER_RELEASE_DOMAIN=downloads.padiem.net
HELPER_RELEASE_UPLOAD=NOT_RUN
HELPER_RELEASE_VAR_SET=NOT_RUN
HELPER_RELEASE_DEPLOY=NOT_RUN
PRODUCTION_MUTATION=0
```
