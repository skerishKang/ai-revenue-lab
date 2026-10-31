# COM2 host facts and empty landing areas — 2026-10-26

Observed directly on COM2 on 2026-10-26 KST. Related: #5881. This is an environment snapshot, not a service rollout or Tunnel cutover.

## Environment facts (10 items)

| # | Item | Observed fact |
|---|---|---|
| 1 | Host OS / virtualization | Microsoft Windows 10 Home, 10.0.19045, 64-bit. Ubuntu is running under **WSL2**, not native Linux or a separately administered conventional VM. |
| 2 | Linux / kernel | Ubuntu 24.04.4 LTS; kernel `6.18.54.1-microsoft-standard-WSL2`. |
| 3 | systemd | Available; `systemctl is-system-running` returned `running`. Executor and Linux MeshCentral units are active. |
| 4 | Python / environments | Python 3.12.3. Existing executor venv: `/opt/padiem/oracle-mesh/venv`. New isolated venvs: `/opt/padiem/file-lane/venv`, `/opt/padiem/b14/venv`; both report Python 3.12.3. |
| 5 | cloudflared installation | Installed on both Windows (WinGet package) and WSL (`/usr/local/bin/cloudflared`); both report 2025.8.1. Windows build timestamp 2025-08-21 15:34 UTC; Linux 15:35 UTC. |
| 6 | Tunnel / ingress | No running cloudflared process was found in Windows or WSL, no matching running Docker container was found, and no cloudflared Windows service/Tunnel scheduled task was found. **Current ingress hostname list: UNKNOWN**, not verified empty. No active config path or token/config mode could be established; see bounded search below. |
| 7 | C: / NVMe | Disk 0: Samsung NVMe, physical size 128,035,676,160 bytes. C: NTFS, volume size 126,986,207,232 bytes; free about **46.35 GiB** (49,770,045,440 bytes). WSL mount: `/mnt/c`. |
| 8 | 2 TB HDD / Linux storage | Disk 1: Hitachi SATA HDD, physical size 2,000,398,934,016 bytes; D: NTFS size 2,000,396,742,656 bytes; free **1,293.12 GiB / 1.26 TiB** (1,388,483,428,352 bytes). WSL mount `/mnt/d`. Ubuntu storage base is `D:\Docker\wsl\Ubuntu`; Linux / reports a ~1 TiB virtual filesystem with ~893.8 GiB free. This virtual free space is not an additional physical disk. |
| 9 | Listening ports | See TCP/UDP snapshot below. These are local listening/bound ports, not proof of Internet reachability or firewall allowance. No listener or firewall rule was changed. |
| 10 | Executor unit | `/etc/systemd/system/padiem-oracle-mesh-executor.service`; active. MainPID 256491 before and after preparation. Linux MeshCentral: `/etc/systemd/system/padiem-meshcentral.service`, active, MainPID 693 at final check. No existing service was installed, stopped, restarted or reconfigured by this task. |

## Listening-port snapshot

Windows TCP: `22, 80, 81, 135, 139, 443, 445, 2342, 3000, 3001, 3002, 4000, 4443, 5040, 5357, 5678, 7680, 8082, 8083, 8084, 8085, 8090, 8096, 8123, 8506, 8600, 8920, 9000, 9090, 11000, 11010, 11020, 11984, 18554, 18555, 18717, 18731, 18764, 24443, 46810, 49664–49672, 52800, 64847`.

Windows UDP: `53, 137, 138, 500, 1900, 2177, 3702, 4500, 5050, 5353, 5355, 41641, 49664, 50239, 50241, 50243–50245, 50249, 53300–53302, 53471, 54983–54985, 54986–54990, 60311–60312`.

WSL TCP: `53, 2342, 3001, 4443, 5678, 8085, 8096, 8123, 8600, 8920, 11984, 18554, 18555, 40000`. Loopback-only listeners include 53, 4443, 11984 and 18554; 40000 is bound to WSL interface addresses. Other listed WSL TCP listeners include wildcard bindings.

WSL UDP: `53, 323, 1900, 5353, 16989, 33765, 43494, 47933, 55598, 57665, 60877`. Ephemeral ports can change. Windows and WSL observations are separate network views; overlapping numbers are not an inventory of distinct applications.

## Prepared landing areas (no service installation)

| Purpose | Application / venv | HDD data and logs |
|---|---|---|
| File lane | `/opt/padiem/file-lane`; `venv/bin/python` | `/mnt/d/padiem/file-lane`; `logs/` |
| B14 | `/opt/padiem/b14`; `venv/bin/python` | `/mnt/d/padiem/b14`; `logs/` |

Created only empty application/data/log directories, isolated standard-library venvs and inactive templates. No application package, service unit, auto-start task, dependency installation, secret or listener was added. Directories/venvs are root-owned staging areas; runtime identity and data permissions must be set as part of the separately authorized service installation. HDD data is on Windows NTFS exposed through WSL; Linux permission semantics require verification before activation.

Each application directory contains `logrotate.conf.example`, pointing only at its corresponding HDD `logs/*.log`:

```text
/mnt/d/padiem/<file-lane-or-b14>/logs/*.log {
    daily
    rotate 7
    maxsize 50M
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

Both were parsed successfully with `logrotate --debug --state /dev/null <template>`. No logs exist yet; no rotation or state write occurred. Templates were **not** installed into `/etc/logrotate.d`; the rotation interval/maxsize take effect only after a future authorized installation and scheduler configuration. These are file-log templates, not global journald changes.

## Tunnel structure: verified limits

Read-only checks covered Windows cloudflared processes/services/scheduled tasks, WSL processes/systemd units, running Docker containers, and these candidate configuration locations:

- WSL: `/etc/cloudflared/config.yml`, `/etc/cloudflared/config.yaml`, `/root/.cloudflared/config.yml`.
- Windows: current-user `.cloudflared/config.yml`, `C:\Users\user\.cloudflared`, `C:\ProgramData\cloudflared`, and the systemprofile `.cloudflared/config.yml`.
- Existing COM2 runtime directories: `D:\padiem-cloudflare-com2` and `D:\PADIEM-Servers\.com2-runtime`. The source renderer `D:\padiem-cloudflare-com2\scripts\ops\com2_tunnel.py` exists, but no deployed ingress configuration was found in this search.

A renderer/source document is not proof of an active tunnel. The expected generated path documented by the existing runtime material is `D:\PADIEM-Servers\.com2-runtime\cloudflared-ingress.yml`; it was not found.

**Ingress-addition verdict: NOT_CONFIRMED.** No active tunnel configuration was located, so local YAML management versus remotely managed token mode and the current hostname list remain UNKNOWN. No Cloudflare account query, token read, tunnel creation/start, ingress edit or existing Tunnel change was performed. Before adding ingress, locate the actual active tunnel's owner/host and configuration source; a locally managed tunnel would use its existing YAML, while a remotely managed tunnel would require its existing dashboard/API configuration authority. Neither path was changed here.

## Validation and scope

- Observations: Windows CIM/disk/volume/listener queries; WSL OS/kernel/Python/systemd/mount/listener queries; bounded cloudflared metadata/config-path inspection.
- Preparation: both venv interpreters execute; both inactive logrotate templates pass dry-run parsing.
- Existing executor remains active with unchanged MainPID 256491; MeshCentral remains active.
- No model call, deployment, D1 change, service installation/restart, existing environment edit, Tunnel modification or secret/token/header output.
- Blocker for future ingress work: active Tunnel location/configuration and hostname inventory have not been established. Landing areas themselves are prepared.
