# PC user helper EXE release procedure (2026-11-07)

> Source-only procedure for `#7117` PR-4. This PR does **not** upload an EXE,
> change the COM2 or Worker environment, create a bucket, or deploy anything.
> The CTO runs the commands below after the merge order is complete.
>
> **Operating authority:** while `chat.padiem.net` is served by
> `padiem-chat-front`, the COM2 Chat host (`padiem-chat-com2`) is the authority
> for pairing and the one-click install response. The Python Worker
> `padiem-chat` is a read-only fallback and is not updated by the default
> release path. See the #7121 request-topology decision on `main`
> (`docs/operations/CHAT_PADIEM_NET_REQUEST_TOPOLOGY_20261108.md`).

## 0. One-time R2 bucket and custom domain (CTO, before the first release)

The release bucket and `downloads.padiem.net` are created once. Use the
PADIEM Cloudflare account `9be14bb7b8974e65d0afba647ab16932`; do not create a
second bucket if the first command says the name already exists.

```powershell
$env:CLOUDFLARE_ACCOUNT_ID = "9be14bb7b8974e65d0afba647ab16932"

wrangler r2 bucket create padiem-pc-helper-releases
wrangler r2 bucket list
```

Connect the custom domain. `wrangler r2 bucket domain add` requires the zone ID
of `padiem.net`; copy it from Cloudflare Dashboard -> `padiem.net` -> Overview.

```powershell
$zoneId = "<padiem.net zone id>"
wrangler r2 bucket domain add padiem-pc-helper-releases `
  --domain downloads.padiem.net `
  --zone-id $zoneId `
  --min-tls 1.2

wrangler r2 bucket domain list padiem-pc-helper-releases
```

Do not use the `r2.dev` development endpoint for a production install link.
After the first upload, `GET https://downloads.padiem.net/...` must return the
exact bytes and SHA-256.

## 1. Decision: where the helper EXE is served

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

The CTO requested R2 + `downloads.padiem.net` for this helper. The transport
matches decision 2 of
`docs/operations/PADIEM_CONNECTOR_INSTALLER_DISTRIBUTION_20261015.md`
(immutable, version-named R2 objects behind a custom domain, never the
application Worker, D1, or a website host). That document's 2026-10-28 header
replaces the old *Connector* installer with MeshCentral; this user-session
helper is a separate release artifact, so the R2 transport remains the CTO's
chosen path for it. The document says `downloads.padiem.net` is not claimed to
exist; this PR selects it as the target and treats creation as a CTO
prerequisite, not an already-live fact.

Why not the alternatives:

- **MeshCentral** (`PC_AGENT_INSTALL_URL`, `apps/padiem-chat/wrangler.toml:199`)
  serves the MeshAgent installer, not arbitrary release artifacts. It is not a
  general upload host and offers no versioned helper path.
- **Worker assets** would require the reviewed EXE to enter exact-main source or
  the generated assets bundle on every deploy. Repository policy keeps the
  generated helper out of Git (`.gitignore`, `#7108` entry) and adding a binary
  would make the artifact a second source of truth that can drift.
- **GitHub Releases** is not guaranteed anonymous for a private repository and
  is not the existing PADIEM distribution host.

## 2. Where the two values go (file:line)

The values are **plain-text entries in the COM2 Chat EnvironmentFile**, not
Cloudflare Worker variables.

| Location | Role |
| --- | --- |
| `/opt/padiem/chat-com2/.env` | live COM2 environment file; the release target |
| `deploy/host-com2/chat/padiem-chat-com2.service:15` | `EnvironmentFile` loads that file into the service |
| `apps/padiem-chat/app/local_cpython.py:642-647` | reads both into `pc_pairing_user_helper_url` / `_sha256` |
| `apps/padiem-chat/app/pc_device_pairing_routes.py:597-617` | handoff response carries the pair |
| `apps/padiem-chat/app/pc_device_pairing_routes.py:932-977` | signed-in one-click install file carries the pair |

The COM2 path is the **operating authority**, not a local-development-only
read. The Python Worker declares the same names at
`apps/padiem-chat/wrangler.toml:207-208` and reads them at
`apps/padiem-chat/worker.py:1695-1700`, but that Worker is the fallback/rollback
lane only.

### Fallback Worker decision (evidence)

The current production front is `padiem-chat-front`; its
`apps/padiem-chat-front/wrangler.toml:24` sets `COM2_CANONICAL=writes`. For a
write it cannot reach COM2, `apps/padiem-chat-front/worker.mjs:335-351` returns
a 503 `write_com2_canonical_refused` and **does not** call the Python Worker
fallback. The install-file route is a session-authenticated POST
(`apps/padiem-chat/app/pc_device_pairing_routes.py:932-977`), so pairing is a
write. Therefore the Python Worker does not handle pairing in the current
production topology, and the default release **must not** update its variables.

B62 is not used for this release. Its `set_var` input
(`.github/workflows/b62-production-code-deploy-gate.yml:140-144`) is for a
Worker code deploy, and its custom-domain assertion still requires the `chat.padiem.net` Worker
service to be the old `padiem-chat` Worker at
`.github/workflows/b62-production-code-deploy-gate.yml:806` and `:1645`, which
is stale after the domain moved to `padiem-chat-front` and currently fails. A
future rollback that moves the Custom Domain back to the Python Worker must set
the Worker pair separately after that assertion is corrected; it is not part of
this release.

`PC_AGENT_INSTALL_URL` remains the MeshCentral URL at
`apps/padiem-chat/wrangler.toml:199` and is **not changed** by this release.

The values are never committed. The COM2 file is root-owned `0600`; the release
script backs it up before replacing the two keys.

## 3. Release: build -> upload -> verify -> write COM2 env -> restart -> verify

From the repository root, after `#7117` is merged into `main`:

```powershell
git fetch origin main
powershell -NoProfile -ExecutionPolicy Bypass `
  -File apps/claw-connect/release-windows-helper.ps1
```

From a snapshot extracted with `git archive` there is no `.git`, so the script
cannot discover the source revision and prints
`HELPER_RELEASE_SOURCE_SHA=UNKNOWN`. Pass `-SourceSha` explicitly in that case:

```powershell
git fetch origin main
$sha = (git rev-parse origin/main)
git archive --format=tar $sha apps/claw-connect | tar -x -C E:\helper-release-main
powershell -NoProfile -ExecutionPolicy Bypass `
  -File E:\helper-release-main\apps\claw-connect\release-windows-helper.ps1 `
  -SourceSha $sha -DryRun
```

`-SourceSha` accepts only an exact 40-hex commit. When it is omitted the script
falls back to the builder receipt, then `git rev-parse`, then `UNKNOWN`. Use
`-ArtifactPath <exe> -Version <version>` as well when the snapshot has no
builder or Python build environment.

The script does all of the following:

1. Runs `apps/claw-connect/build-windows-helper.ps1` and reads its JSON receipt
   (version, byte length, SHA-256, source SHA).
2. Uploads `pc-helper/<version>/padiem-user-helper.exe` and its `.sha256`
   sidecar to `padiem-pc-helper-releases` with the immutable cache policy.
3. Downloads the public URL again and compares the served SHA-256 and byte
   length with the built artifact. It stops before touching COM2 on drift.
4. Writes a temporary bash updater, uploads it with `scp` to the COM2 Windows
   user's home, and runs it as root inside WSL:

   ```text
   ssh -i C:\Users\limone\.ssh\id_rsa -o BatchMode=yes user@192.168.0.101
     wsl.exe -d Ubuntu -u root --exec bash /mnt/c/Users/user/<updater>.sh ...
   ```

   The defaults are `SshKey=C:\Users\limone\.ssh\id_rsa`,
   `SshTarget=user@192.168.0.101`, `WslDistro=Ubuntu`,
   `RemoteWindowsHome=C:/Users/user`, `Com2EnvFile=/opt/padiem/chat-com2/.env`,
   `Com2Service=padiem-chat-com2.service`, and
   `Com2HealthUrl=http://127.0.0.1:8798/health`. Override a parameter only when
   the host actually differs.
5. Backs up `/opt/padiem/chat-com2/.env` to
   `.env.bak-<UTC timestamp>-<pid>` (root:root `0600`, byte-compare before
   continuing).
6. Atomically replaces exactly `PC_USER_HELPER_INSTALL_URL` and
   `PC_USER_HELPER_SHA256`, preserving every other line and deduplicating any
   old copies.
7. Restarts `padiem-chat-com2.service`, waits for it to become active, runs the
   loopback health check with the same readiness ladder as `wait_for_health` in
   `deploy/host-com2/deploy_from_main.sh` (first probe immediately, then every
   2 s for up to 60 s, printing `COM2_HEALTH_ATTEMPTS`), and reads
   `/proc/<MainPID>/environ` to prove the running process received the exact URL
   and SHA-256.
8. Checks that the unauthenticated `POST /api/pc/pairings/install-file` route is
   alive and returns `401` (the session gate, not a broken route), then prints
   `PAIRING_RESPONSE_VERIFY=REQUIRED_SIGNED_IN_OWNER`.

Dry run first; it performs no network mutation, no SSH, and prints the exact
plan:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File apps/claw-connect/release-windows-helper.ps1 -DryRun
```

Expected dry-run markers:

```text
PLAN_COM2_ENV=...
PLAN_COM2_TRANSPORT=...
PLAN_COM2_RESTART=...
PLAN_COM2_ENV_READBACK=...
PLAN_PAIRING_RESPONSE=...
PLAN_WORKER_FALLBACK=NOT_UPDATED
PRODUCTION_MUTATION=0
```

Expected successful run markers:

```text
HELPER_RELEASE_R2_VERIFIED=PASS
COM2_ENV_BACKUP=/opt/padiem/chat-com2/.env.bak-...
COM2_ENV_VALUES=PASS
COM2_SERVICE_ACTIVE=PASS
COM2_HEALTH_ATTEMPTS=<n>
COM2_HEALTH=PASS
COM2_PROCESS_ENV=PASS
COM2_PAIRING_ROUTE=401_UNAUTHENTICATED
HELPER_RELEASE_ENV_SET=PASS
HELPER_RELEASE_RESTART=PASS
HELPER_RELEASE_HEALTH=PASS
HELPER_RELEASE_PAIRING_SOURCE=PASS
PAIRING_RESPONSE_VERIFY=REQUIRED_SIGNED_IN_OWNER
```

### Required owner-session pairing check

The script cannot call the install-file endpoint as the owner because that
endpoint is session-authenticated; it verifies the exact process environment
the endpoint reads, but it does not forge an owner session. After the script
succeeds, the CTO must:

1. Sign in to `https://chat.padiem.net` as the owner.
2. Request `POST /api/pc/pairings/install-file` from the browser/DevTools (or
   use the visible one-click flow).
3. Confirm the response text contains
   `PADIEMHELPERURL:<HELPER_RELEASE_URL>` and
   `PADIEMHELPERSHA:<HELPER_RELEASE_SHA256>` with the released values.
4. Run one real one-click install on a Windows PC and confirm the helper task is
   registered and the executor reaches the user-session pipe. A served file and
   a green restart are not by themselves proof of the installed helper.

Do not put a browser cookie or session token in the repository, the release
script, or a command line. The process-env readback plus this signed-in check
is the evidence chain.

## 4. Post-release verification

1. `GET` the versioned URL and check the SHA-256 against
   `HELPER_RELEASE_SHA256`; the `.sha256` sidecar is public for independent
   comparison.
2. Confirm `padiem-chat-com2.service` is active and the loopback health check
   passes.
3. Confirm the signed-in pairing response pair, as described in section 3.
4. Run one real one-click install and the user-session pipe check.
5. Record the version, URL, SHA-256, byte length, R2 key, COM2 backup path and
   source SHA in the release evidence.

## 5. Rollback

The object keys are immutable; keep the previous version's URL and SHA-256.
To roll back the COM2 environment:

```bash
backup=/opt/padiem/chat-com2/.env.bak-<timestamp>
install -m 0600 -o root -g root "$backup" /opt/padiem/chat-com2/.env
systemctl restart padiem-chat-com2.service
systemctl is-active --quiet padiem-chat-com2.service
runuser -u padiem-chat -- /opt/padiem/chat-com2/venv/bin/python \
  /opt/padiem/chat-com2/health.py --url http://127.0.0.1:8798/health
```

Then repeat the signed-in pairing response check and record the restored
version. A variable rollback does not uninstall or replace an already-downloaded
helper; the next one-click install is the update path.

Do not dispatch B62 as part of this rollback; the Worker fallback is not the
current authority, and the B62 domain assertion still expects the pre-cutover
`padiem-chat` custom domain. If the Custom Domain is deliberately moved back to
the Python Worker, set the Worker pair in a separate, reviewed step after that
assertion is corrected.

## 6. Evidence state in this PR

```text
HELPER_RELEASE_HOST=R2_CUSTOM_DOMAIN_SELECTED
HELPER_RELEASE_BUCKET=padiem-pc-helper-releases
HELPER_RELEASE_DOMAIN=downloads.padiem.net
HELPER_RELEASE_UPLOAD=NOT_RUN
HELPER_RELEASE_ENV_SET=NOT_RUN
HELPER_RELEASE_RESTART=NOT_RUN
HELPER_RELEASE_PAIRING_VERIFY=NOT_RUN
WORKER_FALLBACK_UPDATE=NOT_RUN
PRODUCTION_MUTATION=0
```

## Replacing the source-installed helper on the operator PC (no Python)

`\Padiem\PadiemUserSessionHelper` currently runs the #7105 source install
(`python -m claw_connect.user_helper_service --device-id <id> --secret-file
C:\ProgramData\Padiem\helper.secret`). To move that task to the single-file
EXE — same CLI contract, and the pipe name derives from the device id, so the
agent-side path is unchanged:

1. Download the released EXE and verify SHA-256 against the `.sha256` object.
2. Place it at `C:\ProgramData\Padiem\padiem-user-helper.exe`.
3. `schtasks /end /tn "\Padiem\PadiemUserSessionHelper"` — stop the running
   python helper instance.
4. `schtasks /change /tn "\Padiem\PadiemUserSessionHelper" /tr "\"C:\ProgramData\Padiem\padiem-user-helper.exe\" --device-id <same device id> --secret-file \"C:\ProgramData\Padiem\helper.secret\""` — swap the task action to the EXE.
5. `schtasks /run /tn "\Padiem\PadiemUserSessionHelper"`.
6. Pipe check: the name is `padiem-user-helper-dev_<32 hex>` from
   `claw_connect.user_session_helper.pipe_name(<device id>)`; confirm it exists
   (`[System.IO.Directory]::GetFiles("\.\pipe\")`) and that the executor
   reaches it (the whoami roundtrip). Rollback = repeat 3-5 with the old
   `python -m ...` action line.
   - One-shot diagnosis of this whole chain (task, binary, secret-file ACL,
     pipe, process, agent → VERDICT; read-only, no admin): run
     `apps/claw-connect/tools/check-user-helper.ps1` (add `-DeviceId <raw
     device id>` to pin the id; `-PrintPipeNameOnly` for just the name).
