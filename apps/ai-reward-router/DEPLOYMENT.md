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

**Secret-binding verification levels (do not conflate):** the activation
gate's settings readback proves EXISTENCE and TYPE of
`PADIEM_SESSION_SECRET` only. Cloudflare secret values are write-only, so
equality with the chat product's `PADIEM_CHAT_SESSION_SECRET` can be proven
ONLY by the live signed-session E2E (a chat-issued cookie must verify in B64,
and a revoked session must be denied). Note that sharing the signing key
expands credential authority even though B64 code only verifies — the B64
worker contains no minting code, and the secret value never leaves the
approval path.

**Binding-baseline contract:** any operational binding change on this worker
follows `docs/operations/CLOUDFLARE_CREDENTIAL_OPERATIONS.md` §8 — owner
decision recorded first, a reviewed
`.github/binding_baselines/b64-ai-reward-router.json` amendment travelling
with the same PR, and the run logged (binding names/types, device, KST time,
wrangler log filename — never values, tokens or account IDs). The
activation gate's readback is evidence for that record, not a baseline
amendment by itself.

## Auth decision: Plan A confirmed — Plan B (chat-verifies-identity) is NOT implementable without changing the chat product (2026-10-26)

Measured from the current chat source:

- `apps/padiem-chat/app/history.py` — `UserProfile.public_dict()` returns
  `{"email", "name", "picture"}` ONLY; the user id (`usr_…` uid) is not part
  of any public payload.
- `apps/padiem-chat/app/auth_routes.py` — `/api/auth/status` projects exactly
  that dict as `user`, plus `authenticated` / `session_state` /
  `member_grade`.

Consequence for **Plan B** (B64 asks chat, through `PADIEM_CHAT_SERVICE`, to
verify the session and trusts the server-verified identity): the relay can
prove THAT a canonical session is live, but it cannot produce WHICH user it
belongs to. The income pipeline keys every record by `userId`, so Plan B
cannot satisfy user isolation without adding a new uid-revealing endpoint to
the chat product — a B62 authority change that is out of scope for this task
and would itself need a security review.

Therefore **Plan A stands** (already implemented and tested since #5820):
B64 verifies the signed `padiem_session` cookie locally with the shared
session secret (`PADIEM_SESSION_SECRET`, same value as chat's
`PADIEM_CHAT_SESSION_SECRET` — verify-only: B64 contains no token-minting
code) and blocks revoked sessions through the existing
`PADIEM_CHAT_SERVICE → /api/auth/status` liveness relay. The only remaining
operational step is registering that one secret on the B64 worker via the
approved secret store — no code change.

## Zone routing audit boundary (2026-10-26)

- The local wrangler OAuth session exposes scopes
  `user / offline_access / account / workers / workers_kv` — **no zone-read
  scope**, and pulling stored tokens out to call the REST API directly is
  prohibited by the credential-operations policy. So the existing
  `chat.padiem.net` route table (including any `chat.padiem.net/*`
  wildcard) remains `UNKNOWN` from this environment and must be read by
  CENTRAL through an authorized path; the route-by-route checklist above is
  the verification record.
- Cloudflare Workers routes support same-host sub-path patterns
  (`chat.padiem.net/pipeline*` etc.) as first-class route patterns, so
  sub-path serving for B64 is configuration, not a code change. The most
  specific matching route wins inside a zone — this is exactly what the
  checklist verifies per path.
- Client-side collision audit: the chat React app
  (`apps/padiem-chat-react`) renders a single view and uses NONE of B64's
  consumer paths as client routes — no client-side navigation conflict with
  `/pipeline`, `/today`, `/browse`, `/detail`, `/earn`, `/income`.

## Session secret activation — measured source situation and the decision tree (2026-10-26)

Measured facts:

- The live Cloudflare secret value CANNOT be read back through any API —
  `secret_text` bindings are write-only. Copying the existing value by API
  is impossible by design; any tooling claiming otherwise must not be used.
- The repository has NO stored source for the chat session secret:
  `gh secret list` on this repo shows `CLOUDFLARE_API_TOKEN`,
  `CLOUDFLARE_ACCOUNT_ID` and product tokens — **no
  `PADIEM_CHAT_SESSION_SECRET`**. The chat secret was registered on the
  worker without a repo-secret source.
- `PADIEM_CHAT_SESSION_SECRET` is confirmed to EXIST on the live
  `padiem-chat` worker (`secret_text` binding, verified by the b62 auth
  activation gate's settings readback pattern).

Decision tree (owner decision required — LOCAL executes none of these):

- **Option A (preferred, zero user impact)** — if the approved private store
  still holds the ORIGINAL chat session secret value: register it once as
  the repository secret `PADIEM_SESSION_SECRET_SOURCE`, then dispatch
  `.github/workflows/b64-session-secret-activation-gate.yml` (dispatch-only,
  production environment, exact-SHA check). The gate copies the value onto
  `b64-ai-reward-router` as `PADIEM_SESSION_SECRET` without ever printing
  it, and verifies existence/type via the settings API. Existing chat
  sessions stay valid.
- **Option B (rotation)** — if no original value is held anywhere: generate a
  NEW session secret, register it as `PADIEM_SESSION_SECRET_SOURCE`, update
  chat's `PADIEM_CHAT_SESSION_SECRET` with the same value, then dispatch the
  gate. Every live chat session is invalidated (all users re-login) — this
  is an owner decision with an explicit user-impact acknowledgment, and it
  must be coordinated with the chat product's release.
- **Option C (not recommended)** — a chat-side change that publishes a
  one-way derived verification key for B64. It avoids secret sharing but
  requires modifying the B62 authority product; rejected for now on
  change-cost vs. benefit.

## Zone route probe and change procedure (2026-10-26)

- `.github/workflows/b54-cloudflare-zone-route-readonly-probe.yml` is the
  in-repo precedent for AUTHORIZED zone reads: the repo secret
  `CLOUDFLARE_API_TOKEN` derives the `padiem.net` zone id from
  `/accounts/{account}/workers/domains` and reads
  `/zones/{zone}/workers/routes`. Its 2026-09-04 runs FAILED (token scope);
  since then the OAuth custom-domain work succeeded through the same
  credential path, so the scope situation may have changed — it must be
  re-measured, not assumed.
- `.github/workflows/b64-cloudflare-zone-route-readonly-probe.yml` (added
  here) runs the same GET-only pattern for `chat.padiem.net`: it prints the
  route table (pattern → script), detects an existing host wildcard, and
  lists the assignment state of every B64 path. GET-only contract enforced
  by the workflow's own source check. The output IS the
  `DASHBOARD_ROUTE_COLLISION` evidence for the #987 checklist.
- Route change (CENTRAL, after the probe passes):
  `PUT /zones/{zone_id}/workers/routes` with each B64 path pattern
  (`chat.padiem.net/earn*`, `/today*`, `/browse*`, `/detail*`,
  `/pipeline*`, `/income*`) → `b64-ai-reward-router`, keeping `/`, `/api/*`
  and `/healthz` on `padiem-chat`. If a host wildcard exists, verify the
  specific routes take precedence (most specific pattern wins) with the
  post-add smoke from the checklist.
- Rollback: `DELETE /zones/{zone_id}/workers/routes/{route_id}` for the
  added routes (record every `route_id` at add time). Because the routes
  only ADD new host paths, rollback restores the exact pre-change serving.
  The workers.dev fallback host remains enabled until live E2E passes.
