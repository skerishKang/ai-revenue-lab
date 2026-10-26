# COM2 file-lane installation and recovery (#5881)

Code/runbook only. Execute the following operations only after Owner's service
installation/activation instruction. No operation below has been performed by
this PR. User login/session/ticket issuance remains in Cloudflare Chat.

References: [host facts](COM2_HOST_FACTS_20261026.md),
[Tunnel runbook](COM2_TUNNEL_RUNBOOK.md),
[Chat file contract](../../apps/padiem-chat/FILE_LANE.md),
[file service](../../apps/padiem-file-lane/README.md).

## Fixed COM2 layout

COM2 is Windows 10 hosting Ubuntu 24.04 **WSL2** with systemd. This package uses
Linux systemd, not the optional native Windows SCM wrapper.

| Purpose | Path / identity |
|---|---|
| Application and venv | `/opt/padiem/file-lane`, `/opt/padiem/file-lane/venv/bin/python` |
| Private environment | `/opt/padiem/file-lane/.env`, root:root, mode 0600 |
| HDD storage | `/mnt/d/padiem/file-lane` on mounted D: NTFS/DrvFS |
| Unit / account | `padiem-file-lane.service` / `padiem-file-lane` |
| HTTP | `127.0.0.1:8788`; `/health` returns only `{"ok":true}` |
| Shared Tunnel unit | `cloudflared-padiem.service`, as prepared in the Tunnel runbook |

The existing executor `padiem-oracle-mesh-executor.service`, MeshCentral
`padiem-meshcentral.service`, B14, SSH and other Tunnel paths are outside this
operation. Do not restart WSL/Windows or those services. The D: mount must
actually exist; a bare `/mnt/d` directory on the Linux root disk is not a
substitute. Existing root-owned landing areas are staging, not an installation.

## 1. Install the reviewed package and unit

Use a dedicated persistent checkout on COM2 (for example
`/opt/padiem/file-lane/repo`), fetched to the exact approved release SHA. Do not
use an uncommitted worktree or mutate the executor's checkout. Record the
previous file-lane release SHA and active state for recovery. A first install
has no previous file-lane release. Confirm 8788 is unused or belongs to the
reviewed file-lane process; do not kill an unknown listener to obtain the port.

From the reviewed checkout root, first print the non-mutating plan:

```bash
bash deploy/host-com2/file-lane/install.sh --dry-run
```

After the separate installation GO, run:

```bash
sudo bash deploy/host-com2/file-lane/install.sh --apply --source-root "$PWD"
```

The installer refuses an active `padiem-file-lane.service`; stop only that unit
in an approved update window before installing a new release. It checks the
HDD mount, creates the dedicated non-login account, reuses/creates the prepared
venv, installs hash-pinned runtime dependencies exported from the service's
`uv.lock`, then installs the reviewed local package without resolving another
runtime dependency set. It copies only this unit/health/config checker and
calls daemon-reload. It **never starts/enables a service or edits a Tunnel**.
No apt/dpkg repair or unrelated package installation is included.

The installer creates `.env` only if absent and never replaces existing values.
The example contains names only. Enter the dedicated HMAC value privately with
`sudoedit /opt/padiem/file-lane/.env`, using the variable
`FILE_LANE_TICKET_SECRET` (at least 32 characters). Configure
`FILE_LANE_ALLOWED_ORIGINS` with the exact deployed Chat origin for credentialed
browser CORS. Do not use `*`. Do not paste values into chat, commands, logs,
screenshots, issues or PRs; do not run `cat .env`, `printenv`, `set -x` or
`systemctl show ... Environment`.

ROOT/HOST/PORT are fixed by the reviewed unit. Do not override them in `.env`.
The ExecCondition checks these settings, secret presence/length and data write
access, printing one boolean only. An empty/unready environment skips startup
rather than entering a restart loop. NTFS/DrvFS ownership semantics vary: the
installer proves that the actual service identity can create/remove a private
probe. If this fails, report the permission failure and fix the D: ACL/mount
configuration separately; do not silently move data onto C: or weaken all users'
permissions. This check does not claim that Linux chmod alone establishes
Windows NTFS ACL isolation.

## 2. Start only the file service and check local HTTP

After the activation GO and private configuration:

```bash
sudo systemctl start padiem-file-lane.service
systemctl is-active padiem-file-lane.service
/opt/padiem/file-lane/venv/bin/python /opt/padiem/file-lane/health.py
```

The health command performs one read-only request with a 5-second probe timeout
and prints only `health_ok`/HTTP status. It does not print a URL, headers, body,
exception or token, follow redirects, retry, or restart anything. A healthy
HTTP endpoint does not prove that upload tickets, parsing or public ingress
work. An inactive unit with `FILE_LANE_CONFIG_READY=0` needs its private config
corrected, not a restart of other services. `Restart=always` applies once the
valid service is running. Enable `padiem-file-lane.service` for later WSL boots
only after acceptance and the corresponding GO. Windows-to-WSL boot supervision
remains the existing host concern; this package does not create a Windows task.

Stdout/stderr go to journald. No access log is enabled. Do not dump unfiltered
journals or environments. Existing inactive HDD file-log rotation templates
from the host-facts preparation are not installed by this package; no global
journald/logrotate configuration is changed.

## 3. Connect the approved Tunnel route

Follow `COM2_TUNNEL_RUNBOOK.md` using Cloudflare account **Charliekant**. Its
prepared remote/token unit is `cloudflared-padiem.service`, with private token
handoff at `/opt/padiem/cloudflared/.env`. This installer never reads or copies
that token. `files.padiem.net` is a proposal until Owner selects/reserves it;
recheck active ingress/DNS and snapshot any new records before changing them.

Route the selected file hostname to `http://127.0.0.1:8788`; keep the existing
B14 `8789` mapping and terminal 404. Token mode uses Cloudflare-managed ingress;
copying a local `config.yml.example` does not configure it. Start/enable the
prepared connector only under its own activation instruction; do not overwrite
or restart a generic existing cloudflared/Tunnel service.

Keep Cloudflare authentication contracts. Chat authenticates the user and
issues the scoped HMAC capability; every file GET/POST requires that capability.
Do not expose an unsigned file API or add a second credential authority. If an
existing edge policy instead presents an SSO/service-token challenge to server
reads, stop and report that policy mismatch: the current Chat client sends
only the signed file capability and does not invent Access credentials or
forward user cookies. Do not disable an existing access policy to make a probe
pass. Resolve the approved routing/auth composition before activation.

For the approved public hostname, the same health script can be called with
`--url https://<approved-file-host>/health`. It refuses credential-bearing URLs,
redirects and arbitrary plaintext remote hosts. Report booleans/status only;
TLS/HTTP success alone is not proof of authenticated file access.

## 4. Configure the two Chat variables

Only after the origin/Tunnel is ready, use the existing authorized Chat
configuration/secret-management path for these **two names**:

- `PADIEM_CHAT_FILE_LANE_ORIGIN`: the exact approved HTTPS root origin, with no
  path/query/userinfo; it is not the loopback origin.
- `PADIEM_CHAT_FILE_LANE_TICKET_SECRET`: the same dedicated HMAC value as the
  COM2 `FILE_LANE_TICKET_SECRET`, privately provisioned through the trusted
  Worker binding/Secrets Store. Never reuse the session/B14/provider secret.

No value belongs in Git. The Worker reads its own trusted binding rather than
process-environment fallbacks. Chat code with PR-2 (#5893) must be in the
approved deployment. Deploy/reload Chat only under Owner's release instruction,
using its existing deployment path and preserving unrelated bindings. Adding
these names in a dashboard is not by itself proof that the running version
loaded them. No Parser Service attach/binding is required for the COM2 path.

### Engine reads the same lane (stage 3, #5881)

Stage 3 moves the text read behind the Engine document path, so the Engine
Worker carries one additional plain var and no new Secret:

- `FILE_LANE_ORIGIN`: the same approved HTTPS root origin, with no
  path/query/userinfo. Unset leaves document admission on its existing inline
  path and a `file_id` reference fails closed 503 `file_lane_unavailable`.

The Engine holds no ticket secret: Chat signs the read ticket and the Engine
forwards the three `X-Padiem-File-*` values unchanged. Setting this name does
not by itself deploy anything; the Engine release stays under the Owner's
release instruction.

## 5. Confirm the basic path

In the Owner's authenticated Chat session, confirm file-lane capability is ready
and upload one TXT/MD/CSV/PDF at least 10 MB. Confirm a returned `file_id`,
SHA-256/size metadata and a normal answer using the document. The original File
must go browser -> COM2 and the Chat POST must contain only the file reference.
Do not output the ticket, document contents or request/response headers. Record
only success/failure, the reviewed source SHA and relevant status/code. The
existing inline path stays available when the new origin is not configured.
OOXML/images retain their existing inline path in this phase. No repeated
stress/large-file/model experiment is required by this runbook.

## 6. Recover without touching other services/data

If this new lane fails, stop further uploads and record the fixed failure code.
Under the recovery instruction, remove/clear only the new Chat origin setting
(and, if directed, its dedicated ticket binding) through the existing safe
configuration path, then release the reviewed previous Chat configuration as
in the existing Chat rollback procedure. A blank/unbound file origin disables
automatic file-lane routing and keeps the original inline behavior. Never
replace the complete Worker binding set just to remove this lane.

For a file-service regression, stop **only** `padiem-file-lane.service`, reinstall
the recorded previous reviewed checkout with the same installer, then start and
perform the single local health check. Keep `/mnt/d/padiem/file-lane` and the
private `.env`; no data migration/deletion or secret rotation is automatic.
On a first-install failure without a previous package, leave this unit stopped
and disabled and report it. Do not invent a previous release or delete data.

Revert only the newly recorded file-host DNS/ingress change if directed. Do not
stop a healthy shared `cloudflared-padiem.service` carrying B14 just to recover
one file route; preserve the B14 route, existing Tunnel/SSH/Mesh and executor.
A failed connector activation follows the separate Tunnel runbook's recovery
for that newly activated connector. No recovery action is being executed here.
