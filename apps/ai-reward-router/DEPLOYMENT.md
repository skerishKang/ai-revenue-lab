# B64 dedicated Worker deployment boundary

Issue: #1160  
Parent product gate: #1112

## Purpose

B64 now has a product-local Cloudflare Worker deployment target for the already-merged P0 consumer HTTP surface.

The deployment target is intentionally **account-independent and fail-closed**. It does not create provider accounts, inject provider credentials, activate reward inventory, approve incentive traffic, enable payouts, or unlock P1-P4.

## Runtime

- Worker name: `b64-ai-reward-router`
- Worker module: `dist/src/worker.js`
- Public runtime endpoints: `GET|HEAD /`, `GET|HEAD /earn`, `GET|HEAD /healthz`
- Candidate supply at this stage: empty by design
- Expected health truth: `supplyActivation=OWNER_ACTION_PENDING`, `providerPermissionGranted=false`
- Expected consumer truth with zero live supply: `NO_LIVE_REWARD_SUPPLY`

`src/worker.ts` delegates to `createEmptySupplyConsumerHttpHandler()`. Live provider supply must be wired only in a separately authorized activation task after provider/policy evidence is accepted.

## Deployment isolation

`wrangler.jsonc` is product-local and declares only the independent workers.dev target. It deliberately declares no:

- `routes` or custom domains
- account ID
- production worker alias
- DNS mutation
- provider secrets or variables

`PADIEM_B64_PUBLIC_BASE_URL` (the reviewed mutation origin for the same-origin
guard, declared in `wrangler.jsonc` as `https://chat.padiem.net`) is an
operational configuration var, not a provider credential.

The existing `ai-revenue-korean-ai-platform` production Worker is not a B64 deployment target and must not be modified as a side effect of this config.

## Verification before any deployment

From `apps/ai-reward-router`:

```sh
npm ci
npm run build
npm run typecheck
npm test
```

Then use the environment's approved Cloudflare Wrangler CLI with `wrangler.jsonc`. Cloudflare authentication/account selection remains an operator action; this repository does not embed credentials.

## Owner activation remains separate

The following remain OWNER ACTION and continue to block real consumer reward supply:

- #1116 ayeT publisher onboarding / Korea rewarded-video live proof
- #1117 Adscend cash-video approval / Korea inventory proof
- #1118 Tremendous Korea reward fulfillment production proof

Until those gates are satisfied, a successful Worker deployment proves only the HTTP/runtime shell. It must never be described as proof that ads, rewards, payouts, or provider inventory are live.

## Income pipeline authentication and storage bindings (issue #987)

The `/pipeline` and `/income` lanes authenticate through the **existing PADIEM
consumer login** — the signed `padiem_session` cookie minted and verified by
the B62 chat product (`apps/padiem-chat/app/auth.py`, purpose
`padiem-chat/session/v1`). B64 introduces no second login scheme, and no
client-controlled header, query parameter, or body field can select the user.

Required server-owned bindings on this Worker (all fail closed when absent):

| Binding | Meaning | When missing |
|---|---|---|
| `PADIEM_SESSION_SECRET` (secret) | Same value as the chat product's `PADIEM_CHAT_SESSION_SECRET`; lets this Worker verify the session cookie with the B62 authority algorithm | No request is authenticated (pipeline stays anonymous) |
| `PADIEM_CHAT_SERVICE` (service) | REQUIRED for the income path. Binding to the deployed chat product worker, declared like the existing reference bridge (`reference/business-66-padiem-quote-v1/_worker.js`). Forwards the session cookie to chat's revocation-aware `GET /api/auth/status` so logged-out/revoked canonical sessions are blocked | Cookie-authenticated access is DENIED (fail closed). The deployed B64 path never falls back to signature-only verification; that helper exists only for isolated tests |
| `PADIEM_B64_PUBLIC_BASE_URL` (var) | Exact reviewed public origin of this deployment, e.g. `https://chat.padiem.net`; required by the cookie-authenticated mutation same-origin guard (#3476 policy) | Cookie-carrying POSTs are denied 503 `origin_guard_unavailable` |
| `B64_INCOME_DB` (D1) | Cloudflare D1 database `padiem-b64` for user income records | Pipeline storage answers 503 `storage_unavailable`; the non-durable in-memory prototype is never used as a production fallback |

The repository contract (`UserIncomeRepository`) has no global "delete everything"
operation by design: every production statement is scoped to one `user_id`, and
test fixtures reset their own test-only stores.

Deployment operations that remain OWNER/operator actions:

1. Provision the `padiem-b64` D1 database and apply
   `migrations/d1/0001_b64_user_income.sql` via the dispatch-only
   `B64 Income D1 Provision Gate` workflow, then replace the placeholder
   `database_id` in `wrangler.jsonc` with the real id the gate prints.
2. `wrangler secret put PADIEM_SESSION_SECRET` with the chat product's
   session secret value.
3. Serve this Worker under the chat origin (route on the same host) or make
   an explicit owner decision about cookie scope: the `padiem_session` cookie
   is `HttpOnly; Secure; SameSite=Lax` with **no Domain attribute**, so it is
   host-only for the chat origin and does not reach a different host such as
   `b64-ai-reward-router.<account>.workers.dev`. Until the cookie actually
   reaches this Worker, verification code is correct but no request can
   authenticate.
4. Confirm with the chat product owner that routing B64 liveness checks
   through `PADIEM_CHAT_SERVICE` to `GET /api/auth/status` is acceptable
   load-wise; the endpoint is the same one the reference B66 bridge already
   calls.

## Operational connection runbook (2026-10-26 measured, read-only)

All facts below were measured read-only on the **Charliekant** account
(`9be14bb7b8974e65d0afba647ab16932`, OAuth `ACCOUNT_MATCH` per
`docs/operations/CLOUDFLARE_CREDENTIAL_OPERATIONS.md` §0):

- **D1 inventory (7 databases):** padiem-b14-call-ledger, cgi_quotes,
  padiem-connector-acceptance-4139, padiem-b66-cgi-qa-261011,
  padiem-browser-owner-p01, padiem-engine (`6b77ad02…`), padiem-chat-db
  (`702bb62b…`). **No `padiem-b64` database exists** — the provision gate's
  create-or-reuse flow cannot collide, and the other products' databases must
  NOT be reused by B64 (product isolation).
- **Deployed workers:** `padiem-chat` is active (deployment 2026-10-25, name
  matches the declared `PADIEM_CHAT_SERVICE` target) and
  `b64-ai-reward-router` exists on the account (uploaded 2026-10-23 — the P0
  shell; redeploying the integrated code is a CENTRAL step below).
- **chat.padiem.net** is served through Cloudflare (`Server: cloudflare`) and
  `GET /api/auth/status` answers `200` — the liveness relay target is live.
- **Path-collision audit:** chat's FastAPI route table contains NONE of B64's
  consumer paths (`/`, `/earn`, `/today`, `/browse`, `/detail`, `/pipeline`,
  `/income`, `/healthz`); no `padiem_session`-conflicting `/healthz` exists.
- No route declarations for chat.padiem.net exist in-repo (serving is
  dashboard-side); LOCAL has no zone-read scope, so the dashboard route table
  itself is UNKNOWN here and is not asserted.

CENTRAL execution steps (exact commands; nothing below has been executed by
LOCAL; run `d1` commands from the **repository root** so the `--file` paths
below resolve, or adjust them to the working directory):

1. Provision the D1 database — dispatch the `B64 Income D1 Provision Gate`
   workflow and use the REAL `database_id` it prints (create-or-reuse is safe
   because no `padiem-b64` exists). Do NOT dispatch a second gate run for the
   same database, and do NOT run `wrangler d1 create` manually in addition to
   a dispatched gate. Then replace the PLACEHOLDER `database_id` in
   `apps/ai-reward-router/wrangler.jsonc` with that real id.
2. Apply the schema (if the gate did not already):
   `npx wrangler@4 d1 execute padiem-b64 --remote --file=apps/ai-reward-router/migrations/d1/0001_b64_user_income.sql`
   (replay-safe `IF NOT EXISTS`; no existing B64 table can conflict).
3. Bind the session secret (same value as chat's
   `PADIEM_CHAT_SESSION_SECRET`; never paste the value into logs, PRs or
   issues):
   `wrangler secret put PADIEM_SESSION_SECRET --name b64-ai-reward-router`.
4. Configure the mutation origin: `PADIEM_B64_PUBLIC_BASE_URL` is already
   declared in `wrangler.jsonc` (`vars`) as the reviewed origin
   `https://chat.padiem.net` and takes effect at deploy time. Without it,
   cookie-authenticated POSTs are DENIED (`origin_guard_unavailable`, fail
   closed) — it is required BEFORE any live writes.
5. Deploy the integrated Worker — the `[[services]]` binding
   `PADIEM_CHAT_SERVICE → padiem-chat` is already declared in
   `wrangler.jsonc` and matches the measured worker name:
   `wrangler deploy` (from `apps/ai-reward-router`).
6. Post-deploy binding verification (from `apps/ai-reward-router`):
   `npx wrangler@4 versions list --name b64-ai-reward-router` — the active
   version's bindings must show ALL of:
   `PADIEM_CHAT_SERVICE → padiem-chat`, `B64_INCOME_DB → padiem-b64`,
   `PADIEM_SESSION_SECRET (secret)`,
   `PADIEM_B64_PUBLIC_BASE_URL = https://chat.padiem.net (var)`.
7. Cookie delivery route — the ONLY remaining auth prerequisite: add
   dashboard routes on **chat.padiem.net** for the B64 paths
   (`/earn*`, `/today*`, `/browse*`, `/detail*`, `/pipeline*`, `/income*`)
   targeting `b64-ai-reward-router`, keeping `/`, `/api/*` and `/healthz`
   on `padiem-chat`. The `padiem_session` cookie is host-only for
   chat.padiem.net, so serving B64 under that host is the only
   no-new-login delivery path; a workers.dev host cannot receive it.
8. Run the live E2E after steps 1–7, then record `AUTH_LIVE_VERIFIED` /
   `D1_LIVE_VERIFIED` / `LIVENESS_LIVE_VERIFIED` evidence on #987.

**Dashboard route checklist (verify before step 7 — do not skip):**
`DASHBOARD_ROUTE_COLLISION=UNKNOWN` until the zone's existing routes are read
through authorized access; the FastAPI route audit above is NOT zone-level
evidence. For EACH B64 path pattern, record in #987:

- the chat route it must coexist with (`/`, `/api/*`, `/healthz`, assets);
- whether a zone wildcard `chat.padiem.net/*` already exists — if it does,
  the new specific routes must actually take precedence for B64 paths
  (Cloudflare applies the most specific matching route), and `/` plus
  `/api/*` MUST still resolve to `padiem-chat`;
- the smoke result after adding it: B64 path serves the B64 page AND
  `chat.padiem.net/api/auth/status` still answers from chat.
No overall "collision = 0" claim may be made from the FastAPI audit alone.

**Verification boundaries:** `chat.padiem.net`'s anonymous `200` on
`/api/auth/status` proves endpoint presence only. `LIVENESS_LIVE_VERIFIED=NO`
until a REAL chat session is carried through B64 end-to-end (login-verified
read AND a revoked-session denial both observed live). `D1_LIVE_VERIFIED=NO`
until the migration is applied and a live record round-trip is observed.
