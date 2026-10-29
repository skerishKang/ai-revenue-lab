# Retired: the COM1-era Windows Mesh tunnel layer (2026-10-29, #5643)

These twelve files were the Windows side of the old MeshCentral path: a scheduled task
on COM1 ran a single-instance `ssh -L 127.0.0.1:4443 -> 127.0.0.1:4443` supervisor, a
health probe watched the fabricated listener and its supervisor, a recovery engine
could restart the tunnel, and an observation probe recorded the auto-start evidence
for that layer. None of it is part of the current transport.

What replaced it, and must not be confused with this directory:

* the executor runs on COM2 under systemd (`padiem-oracle-mesh-executor.service`);
* MeshCentral runs on the COM2 WSL host, reached through the Cloudflare Tunnel
  (`mesh.padiem.net`, rendered by `scripts/ops/com2_tunnel.py` — **kept**, current);
* the PC lane's queue and the connector watch are the COM2 services under
  `deploy/host-com2/` and the GitHub watch (`#6140`, `#6141`).

The tunnel removes a loopback forward that nothing on the current path needs; the
Windows task and its supervisor are the retirement target of #5643.

Host cleanup was **not** performed by the change that archived these files. The task
definitions, deployed copies under `C:\Users\limone\Padiem\` and any scheduled task
still belong to the operator's hosts and are handled by
`docs/operations/COM1_LEGACY_MESH_TUNNEL_RETIREMENT_20261029.md` (read-only checks ->
stop -> disable -> delete, with rollback at each step).

The selftests in this directory were green when the layer was archived (local Windows
PowerShell 5.1, same HEAD): supervisor `PASS=66 FAIL=0`, autostart `PASS=185 FAIL=0`,
recovery `PASS=2475 FAIL=0`, health display `PASS=90 FAIL=0`. They are kept for the
record and for the rollback path; they are not run by CI.
