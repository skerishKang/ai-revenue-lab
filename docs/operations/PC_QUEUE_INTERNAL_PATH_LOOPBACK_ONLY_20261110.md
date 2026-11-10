# PC queue internal path — loopback-only (2026-11-10)

State: **applied**. The 컴2 PC queue (`apps/padiem-mesh-queue`) serves its internal
path on the host loopback only. The Cloudflare tunnel that used to carry that host
no longer has a route for it, so the path has no public address at all.

## Rule

1. The queue listens on `127.0.0.1:8797` and nowhere else. Its internal path
   exists for the two callers on the same host — the Chat host
   (`PC_QUEUE_ORIGIN=http://127.0.0.1:8797`) and the executor
   (`ORACLE_MESH_QUEUE_ORIGIN`).
2. No tunnel ingress, Worker route, reverse proxy or DNS-based path rule may be
   added for this service. Its authentication is designed for one in-host caller,
   not for the internet, and publishing it turns a host-local authority into a
   remote one.
3. The Cloudflare Python Worker (`apps/padiem-chat`, the static-fallback era
   deployment) cannot reach loopback, so its PC lane stays on its own D1
   (`PC_QUEUE_BACKEND = "d1"`, empty `PC_QUEUE_ORIGIN` in `wrangler.toml`). The
   canonical PC-lane authority remains the 컴2 host.

## What changed

| Item | Before | After |
|---|---|---|
| Tunnel config (`/opt/padiem/cloudflared/config.yml`) | two rules for the queue host: a path-scoped rule to the service, then a 404 | both rules removed; only the final `http_status:404` remains |
| Queue hostname, public | path existed (`GET /internal/store` answered 405, `POST` answered 403) | `GET`, `POST`, `/`, and query variants all answer 404 |
| Queue hostname, last 24h | — | 0 requests (zone analytics; the previous 7 days carry 5, all from the cutover's own checks) |
| Other tunnel hostnames | files, b14, mesh, lovetree | unchanged |
| Host loopback | health 200, door unchanged | health 200, door unchanged |

The tunnel was restarted with `systemctl restart cloudflared-padiem.service`
after a validated config swap; the original file is kept beside it as
`config.yml.bak-20261110-queue-ingress` (mode 600).

## How to re-check

```bash
# on the 컴2 host
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8797/health          # 200
grep -c 'hostname: queue' /opt/padiem/cloudflared/config.yml                   # 0

# from anywhere else
curl -s -o /dev/null -w '%{http_code}\n' https://queue.padiem.net/internal/store  # 404
```

A 405/403 on the public hostname means a route was re-added: remove it.

## Why it was published in the first place

The 2026-10-29 cutover moved the PC-lane state to this host while the Chat
runtime was still the Cloudflare Python Worker, which can only reach another host
over the internet. The 2026-11-08 move of Chat to the 컴2 host removed that need:
both callers are now on the same machine, and the public route had no consumer
left.
