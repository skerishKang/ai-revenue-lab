# COM2 Cloudflare Tunnel runbook

Scope: COM2 Ubuntu 24.04 WSL2, Cloudflare account **Charliekant**. Related: #5881, #5891. Prepared 2026-10-26 KST; **not started, not enabled, no login/token/DNS action**.

## Prepared state and verification

| Item | State |
|---|---|
| Package | Existing dpkg-installed `cloudflared 2025.8.1`; service pins `/usr/bin/cloudflared`, avoiding the separate `/usr/local/bin` copy. |
| Official apt source | `/etc/apt/sources.list.d/cloudflared.list`: signed-by `/usr/share/keyrings/cloudflare-main.gpg`, `https://pkg.cloudflare.com/cloudflared any main`; signed repository update succeeded. Installation/upgrade attempt exited 100 because dpkg was already interrupted. No upgrade success is claimed. |
| Apt blocker | `libpython3.12-dev:amd64` and `python3.12-dev` are unpacked/unconfigured; `man-db` has pending triggers. No blanket `dpkg --configure -a`, unrelated package repair or service restart was performed. Resolve this package-manager state separately before relying on future apt upgrades. |
| Unit | `/etc/systemd/system/cloudflared-padiem.service`; systemd syntax verification PASS; daemon-reload done; **inactive / disabled**. |
| Owner input | `/opt/padiem/cloudflared/.env`: root-owned, mode **0600**, **0 bytes**; parent mode 0700. |
| Ingress example | `/opt/padiem/cloudflared/config.yml.example`; offline `ingress validate` PASS, no edge connection. Proposed hostnames only: `files.padiem.net` → `http://127.0.0.1:8788`, `b14.padiem.net` → `http://127.0.0.1:8789`, final `http_status:404`. No active `config.yml` was created. |
| Existing operation | Executor active, PID **256491** unchanged; MeshCentral active, PID **693** unchanged. Existing SSH tunnels, Mesh, executor and existing Tunnel configuration were not changed. |

The new unit uses `DynamicUser=yes`, systemd `EnvironmentFile=/opt/padiem/cloudflared/.env`, and `ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate --loglevel warn run`. A shell built-in condition checks whether `TUNNEL_TOKEN` is set without putting the value in process arguments; an empty file prevents connector execution. It has no `--token VALUE` argument, no implicit configuration example loading, and no installation into the generic `cloudflared.service`.

## 1. Owner: one credential handoff

In **Charliekant**, create/select the dedicated **remotely managed** COM2 tunnel and obtain its connector token. On COM2 Ubuntu, use `sudoedit /opt/padiem/cloudflared/.env` and enter the systemd environment assignment named `TUNNEL_TOKEN` with the token as its value. Keep mode 0600. Do not paste the token into chat, a command argument, a screenshot, an issue or a PR. Tell Astra only that the private entry is complete and identify the intended tunnel/account without the token.

This prepared unit is the **token path**: browser `tunnel login` is unnecessary. If Owner instead chooses a locally managed login/certificate tunnel, Owner performs that login; Astra must prepare its tunnel UUID, credentials-file and corresponding reviewed unit configuration before starting. Login alone does not satisfy the current unit's token condition.

## 2. Astra after Owner handoff: activation, routing, health

1. Confirm the intended tunnel/account and that the two origin services are installed and listening on loopback 8788/8789. Verify each service's documented local health endpoint; endpoints for the future file-lane package must be confirmed from its actual release. Recheck existing DNS records and snapshot them; stop on a conflicting hostname rather than overwriting it.
2. For the selected remote/token tunnel, configure the **Cloudflare-managed ingress** with the two example mappings and terminal 404, then add the matching proxied DNS routes to that tunnel. `files.padiem.net` and `b14.padiem.net` are proposals based on Chat's existing `chat.padiem.net`; they are not reserved or approved active records. Keep existing authentication contracts. Do not expose unrelated origins or alter existing SSH/Mesh routes.
3. Token mode uses the remotely managed ingress. The local `config.yml.example` documents the intended mapping; copying it to `config.yml` does **not** configure token-mode routes. Local/login mode uses its own UUID/credentials configuration and, only in that selected mode, `cloudflared tunnel route dns <UUID-or-name> <hostname>`.
4. After the origin and route checks, start **only** `sudo systemctl start cloudflared-padiem.service`; verify active state, the intended connector's connected status and DNS/TLS/HTTP through both hostnames. Enable this unit for subsequent WSL boots only after acceptance. WSL startup at Windows boot is a separate existing-host concern, not created here.
5. Report status/code/boolean evidence only. Never print `.env`, process environment, token-bearing installation commands, raw headers or unfiltered logs. Query service state/PID rather than environment dumps. Confirm existing executor/Mesh PIDs and SSH paths are unchanged. A prepared connector is not proof that the origins or public routing are healthy.

## 3. Recovery

On failed activation, stop/disable **only** `cloudflared-padiem.service`. Restore only DNS/ingress changes recorded for this new connector, or remove only newly created records after checking ownership; do not delete or modify any existing Tunnel/SSH/Mesh/executor path. Keep credential files private and report the failure. No recovery action is being executed by this preparation task.

## References

- [Cloudflare official signed apt repository](https://pkg.cloudflare.com/index.html)
- [Run parameters: TUNNEL_TOKEN and token mode](https://developers.cloudflare.com/tunnel/reference/run-parameters/)
- [Locally managed configuration and ingress validation](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/)
- [COM2 host facts](COM2_HOST_FACTS_20261026.md)

## MeshCentral 설정 변경 기록 (2026-10-28)

"이 PC 연결" 설치 흐름(mesh.padiem.net:443 에이전트)을 위한 COM2 MeshCentral server 설정 변경. 각 키는 원본 설정 파일을 타임스탬프 접미사 백업 사본으로 보존한 뒤 변경했고, 토큰·비밀 값은 이 문서에 적지 않는다.

| Key | Value (구조만) | 비고 |
|---|---|---|
| cert | `mesh.padiem.net` | 공개 모드(사설 터널 전용에서 공개 인증서 모드로) |
| ignoreagenthashcheck | enabled | 에이전트 해시 체크 해제 — 설치 파일 표식 연결 방식 |
| agentping | 60 | 에이전트 응답 주기(초) |
| aliasport | 443 | 에이전트 별칭 포트 |
| agentaliasdns / agentaliasport | mesh.padiem.net / 443 | 에이전트가 접속할 별칭 DNS·포트 |

현재 설치 흐름의 정본 문서: `PADIEM_CONNECTOR_INSTALLER_DISTRIBUTION_20261015.md` 상단 대체 블록, 추적은 #6008.
