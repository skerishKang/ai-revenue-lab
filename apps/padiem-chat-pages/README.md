# padiem-chat-pages — the parallel pages.dev entry for Chat

`https://padiem-chat.pages.dev` serves the same Chat front door as
`https://chat.padiem.net`, from the same proxy code, against the same origin
(`https://chat-com2.padiem.net`, the cloudflared tunnel to 컴2).

## Why a second host

Measured 2026-11-05 from 컴1로컬6:

| host | colo | cold TTFB | warm TTFB |
|---|---|---|---|
| `chat.padiem.net` | LAX | 0.78s | 0.33–0.36s |
| `*.pages.dev` | ICN | 0.081s | 0.033s |

The `padiem.net` zone lands this ISP on the LAX colo; a `*.pages.dev` hostname
lands on ICN. The pages.dev entry therefore removes the trans-Pacific leg of
the first byte. `#6850` decided to run both addresses side by side — nothing
about `chat.padiem.net` changes.

## Layout

```
wrangler.jsonc   Pages config: name, pages_build_output_dir, vars (no secrets)
build.mjs        assembles ./dist from the reviewed sources (nothing generated is committed)
test/            node --test contracts for the assembly and the proxied handler
```

`dist/` after a build:

* the files of `apps/padiem-chat/static` (Pages serves these directly),
* `_worker/worker.mjs`, `_worker/edge-proof.mjs`, `_worker/error-copy.mjs` — copies of
  `apps/padiem-chat-front`, so there is one proxy implementation, not two,
* `_worker.js` — the advanced-mode entry, which re-exports that module.

## Deploy

```bash
node apps/padiem-chat-pages/build.mjs
cd apps/padiem-chat-pages
npx wrangler pages deploy dist --project-name padiem-chat --branch <branch>
```

`--branch main` publishes the production address; any other branch publishes a
preview deployment at `https://<hash>.padiem-chat.pages.dev`.

Secrets are **not** in `wrangler.jsonc`. The project needs the same
`PADIEM_COM2_EDGE_SECRET` as the `padiem-chat-front` Worker, because COM2
verifies the edge proof on every non-`/health` request (a request without it
answers 403 today). Set it once:

```bash
printf '%s' "$PADIEM_COM2_EDGE_SECRET" | npx wrangler pages secret put PADIEM_COM2_EDGE_SECRET --project-name padiem-chat
```

`wrangler pages deploy` replaces the project's vars with `wrangler.jsonc`, so
pass `--keep-vars` for a code-only redeploy.

## Login

Chat keeps the #6259 authority: `padiem-auth` is the only login. Cookies are
host-scoped, so each address runs its own login round trip:

* `chat.padiem.net` → `https://chat.padiem.net/auth/shared/callback`
* `padiem-chat.pages.dev` → `https://padiem-chat.pages.dev/auth/shared/callback`

Both URIs are registered for client `b62` in `apps/padiem-auth/wrangler.toml`.
Google is unchanged: the only URI registered with Google is still
`https://auth.padiem.net/oauth/google/callback`.

A session on one address does not sign the user in on the other.
