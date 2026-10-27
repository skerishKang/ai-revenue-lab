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

`B64_PUBLIC_BASE_URL` (the reviewed mutation origin for the same-origin guard,
declared in `wrangler.jsonc` as B64's own serving host) is an operational
configuration var, not a provider credential. It names no other product's
origin: B64 is an independent business (owner decision 2026-10-27).

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

Required server-owned configuration on this Worker (all fail closed when absent):

| Binding | Meaning | When missing |
|---|---|---|
| `B64_INCOME_DB` (D1) | Cloudflare D1 database holding B64 income records (`b64_user_income`), B64 members (`b64_member`) and B64 sessions (`b64_session`) | Pipeline storage and the account endpoints answer 503; the non-durable in-memory prototype is never used as a production fallback |
| `B64_PUBLIC_BASE_URL` (var) | B64's own reviewed public origin — the host this Worker actually serves — required by the same-origin guard on cookie mutations (#3476 policy) | Cookie-carrying POSTs are denied 503 `origin_guard_unavailable` |
| `B64_SESSION_SECRET` (secret) | B64's own session signing key, minted for B64. Cookies carry the B64 purpose string, so a B64 token is not accepted by any other product's verifier and vice versa | Nobody authenticates: `/pipeline` stays anonymous and account mutations answer 503 `identity_unavailable` |

There is deliberately **no `services` block**. B64 is an independent business
(owner decision 2026-10-27), so its login path must not depend on another
product's Worker staying up. `CONTROL_PLANE_IDENTITY`, `PADIEM_CHAT_SERVICE` and
`PADIEM_SESSION_SECRET` — the couplings #5954 and #5853 introduced — are out of
the target set, and `.github/binding_baselines/b64-ai-reward-router.json`
records that.

The repository contract (`UserIncomeRepository`) has no global "delete everything"
operation by design: every production statement is scoped to one `user_id`, and
test fixtures reset their own test-only stores.

Deployment operations that remain OWNER/operator actions:

1. Mint a B64 session key and register it:
   `wrangler secret put B64_SESSION_SECRET --name b64-ai-reward-router`
   (run from `apps/ai-reward-router`). Any high-entropy value works; nothing is
   copied from another product, and rotating it logs every B64 session out by
   invalidating its signatures — the `b64_session` rows stay, so no data moves.
2. Apply the new schema to the existing database, without recreating it:
   `wrangler d1 migrations list padiem-b64 --remote --config apps/ai-reward-router/wrangler.jsonc`
   then `wrangler d1 migrations apply padiem-b64 --remote --config apps/ai-reward-router/wrangler.jsonc`.
   `0002_b64_member.sql` only adds tables; `b64_user_income` rows are untouched.
3. Deploy from the exact merged SHA through
   `.github/workflows/b64-cloudflare-worker-production-deploy-gate.yml`. It
   reads the binding set back and prints `B64_SESSION_SECRET_BINDING=` so a
   missing key is visible instead of looking like a broken login.
4. A member cookie is host-scoped (`Secure`, `HttpOnly`, `SameSite=Lax`, no
   `Domain`), so B64 login works on whatever host `B64_PUBLIC_BASE_URL` names.
   Moving to B64's own registered domain is that one variable plus a redeploy —
   no code change, and no other product's cookie is involved.

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

## Independent identity as deployed (2026-10-27, issue #987)

This section supersedes the "Authentication wiring as deployed (#5864)" text
that #5954 added here. The owner decision of 2026-10-27 makes B64 an
independent business of ai-revenue-lab, so the
`CONTROL_PLANE_IDENTITY` / `PADIEM_CHAT_SERVICE` coupling that section described
is removed, and the `chat.padiem.net` route rollout it was preparing is
cancelled.

B64 answers its own two questions:

| Question | Answered by |
|---|---|
| Did B64 issue this cookie, and is it unexpired? | HMAC-SHA256 over the B64 purpose string `b64-reward/session/v1` with `B64_SESSION_SECRET` |
| Has this session been logged out or revoked? | the `b64_session` row in B64's own D1 (`revoked_at IS NULL`) |
| Which member is this? | the token's `mid`, cross-checked against that row's `member_id` — never a client-asserted value |

Both must hold. A correctly signed token whose row is gone resolves to nobody,
and a token naming a member id the client picked has no row behind it, so it
resolves to nobody too. Passwords use the repository's reviewed stored format
(`pbkdf2_sha512$220000$<salt>$<digest>`), and
`tests/identity-credentials.test.ts` proves the port both ways against the real
Python implementation.

### Order of operations for a working login (CENTRAL)

1. Register B64's own key (nothing is copied from another product):
   `wrangler secret put B64_SESSION_SECRET --name b64-ai-reward-router`
   from `apps/ai-reward-router`.
2. Apply the additive schema to the existing database — list first, apply only
   if pending, never recreate:
   `wrangler d1 migrations list padiem-b64 --remote --config apps/ai-reward-router/wrangler.jsonc`
   `wrangler d1 migrations apply padiem-b64 --remote --config apps/ai-reward-router/wrangler.jsonc`
3. Dispatch `.github/workflows/b64-cloudflare-worker-production-deploy-gate.yml`
   with `target_sha=<merged main SHA>` and
   `confirmation=DEPLOY_B64_AI_REWARD_ROUTER`. It refuses a config that declares
   service bindings or routes, and prints `B64_SESSION_SECRET_BINDING=` so a
   missing key is visible instead of looking like a broken login.
4. Browser E2E on `https://b64-ai-reward-router.charliekant.workers.dev/pipeline`:
   join → save one record → reload and see it back → the amount stays
   `지급 확인 전` until the status is `지급 완료` → log out and confirm the same
   tab returns to the join/login gate and the record is gone from view. Steps
   1-3 passing is wiring, not this check.
5. Domain: no `chat.padiem.net` routes are created. When B64's own registered
   domain is confirmed by a read-only Cloudflare inventory, changing
   `B64_PUBLIC_BASE_URL` and redeploying is the whole move — the cookie is
   host-scoped and B64 issues it itself.

### Cancelled or retired by the owner decision

- The `chat.padiem.net/{earn,today,browse,detail,pipeline,income}` route
  rollout prepared under #5864. `b64-cloudflare-zone-route-readonly-probe.yml`
  stays as a read-only diagnostic; nothing assigns B64 to that origin.
- `PADIEM_SESSION_SECRET` registration and
  `b64-session-secret-activation-gate.yml` are on no path to a working login.
  They are left in place as history for CENTRAL to retire deliberately rather
  than deleted as a side effect of this change.
- Account copy now says `B64 계정` instead of pointing at a PADIEM login. The
  wider brand wording across the consumer surface is a separate pass and is not
  part of this change.

## Google sign-in through B64's own OAuth client (2026-10-27, issue #987 reuse)

The owner instruction for this step was to reuse what is already built rather
than start a second auth engine. What is reused is the **contract** the
repository already proved in `apps/padiem-chat/app/auth.py` — authorization-code
flow, the same parameter set, a random state kept in a purpose-signed HttpOnly
cookie and compared constant-time, and identity taken from `userinfo` with
`verified_email` — plus B64's own existing session minting, session row and
member id. What is reused is **not** another product's endpoint, client, cookie
or account table, and no new signing or hashing engine was written: both token
types now go through one primitive, `src/identity/hmac.ts`.

| Piece | B64's own value |
|---|---|
| OAuth client | `B64_GOOGLE_CLIENT_ID` / `B64_GOOGLE_CLIENT_SECRET` — B64's credentials, registered on B64's origin |
| Redirect URI | `B64_PUBLIC_BASE_URL` + `/auth/google/callback`, derived from server config, never from the request Host |
| State cookie | `b64_oauth_state`, purpose `b64-reward/oauth-state/v1`, 600s, single-use |
| Session cookie | `b64_session`, purpose `b64-reward/session/v1` — unchanged, and the same row `b64_session` that logout revokes |
| Member id | `b64m_…` minted by B64; the Google `sub` is linked in `b64_member_google` (`0003`, additive) |

Email address is **not** an account key. Signing in with Google for an address
that already has an email/password member creates a separate B64 member rather
than merging the two, because merging would put one person's ledger in another
person's account. Google-only members have no row in `b64_member`, so they have
no password to guess.

Required configuration, all fail closed when absent:

| Binding | Kind on the Worker | When missing |
|---|---|---|
| `B64_GOOGLE_CLIENT_ID` | secret_text | No `Google 로그인` entry is rendered; `/auth/google/*` answers 503 `auth_unavailable` |
| `B64_GOOGLE_CLIENT_SECRET` | secret_text | same |
| `B64_SESSION_SECRET` | secret | same (it signs the state as well as the session) |
| `B64_INCOME_DB` | D1 | the state is signed and Google is reached, but the login completes 503 `storage_unavailable` and the state is spent |
| `B64_PUBLIC_BASE_URL` | var | same — there is no origin to name as the redirect URI |

Neither Google binding is declared in `wrangler.jsonc`, and
`.github/binding_baselines/b64-ai-reward-router.json` is unchanged: a credential
value never belongs in a reviewed config file, and both are delivered as
`secret_text` by the activation gate below.

### Order of operations for a working Google login (CENTRAL / OWNER)

1. Create the OAuth client in Google Cloud for B64 (LOCAL cannot and did not).
   Authorized redirect URI: `https://b64-ai-reward-router.charliekant.workers.dev/auth/google/callback`
   — exactly the value `B64_PUBLIC_BASE_URL` plus the callback path, and a new
   client entry is required whenever that origin changes.
2. Register the client's two values as **`production` environment secrets** on
   this repository, named exactly `B64_GOOGLE_CLIENT_ID` and
   `B64_GOOGLE_CLIENT_SECRET`. A value is never pasted into a terminal, an
   Issue, a PR or this file; the environment store is the only place it lives.
3. Apply the schema **and** bind the credentials by dispatching
   `.github/workflows/b64-independent-identity-activation-gate.yml`. It runs
   `0003_b64_google_identity.sql` after `0002`, counts
   `b64_user_income` / `b64_member` / `b64_session` rows before and after and
   fails if any decreased, then pipes each environment secret through stdin into
   `wrangler secret put` and reads both bindings back as `secret_text`. If one
   of the two secrets is missing it writes **nothing** and says so, because a
   client id without its secret would render the entry and then fail
   mid-round-trip. It mints no OAuth client, rotates no key and deploys no
   Worker revision.
   Registering the GitHub secrets alone binds nothing — this step is what
   reaches the Worker. Both values are `secret_text` rather than a config `var`
   on purpose: `wrangler.jsonc` and
   `.github/binding_baselines/b64-ai-reward-router.json` stay untouched, and
   deploy run 40578410849 proved an out-of-band secret binding
   (`B64_SESSION_SECRET`, absent from the config file) survives a later
   `wrangler deploy`. The application reads `env.B64_GOOGLE_CLIENT_ID` as a
   plain string either way.
4. Deploy through `b64-cloudflare-worker-production-deploy-gate.yml`.
5. Live E2E, which is the only proof that the client is correct: `/pipeline` →
   `Google 로그인` → choose an account → back on `/pipeline` as a member → save
   one record → reload and see it → log out → reload and see the gate. Until
   step 1 exists this cannot be run, and no amount of passing unit tests stands
   in for it: `B64_GOOGLE_LOGIN_LIVE_E2E=NOT_RUN`.

### What this change deliberately does not do

- It does not merge PR #5985. Its PBKDF2 cost change stays open for CENTRAL's
  review, and its technical record stays in #5986. Google sign-in needs no KDF,
  which is why it is the path that works inside the free-plan CPU budget today.
- It does not add a service binding, an outbound call to another product, or any
  dependency on `chat.padiem.net` staying up. The two HTTP calls in the flow go
  to Google's own token and userinfo endpoints, from the Worker.
- It does not use Google Identity Services in the page. The consumer surface
  runs under `script-src 'none'`, so the login is a server-side redirect and one
  plain link.


## ayeT reward postback connected to the Worker and D1 (2026-10-28, issue #987)

The verification and the state rules already existed as pure functions —
`ayet-s2s-postback.ts` (signature and field contract) and `reward-events.ts`
(`applyProviderRewardEvent`: idempotency, orphan reversal, identity mismatch).
What was missing was a transport, a member link and a place to write, so a
provider could not report anything. This section records the connection, not a
new engine.

| Piece | Value |
|---|---|
| Route | `GET /callbacks/ayet/s2s` — no cookie, no browser, signature-authenticated |
| Signature | `X-Ayetstudios-Security-Hash` header, HMAC-SHA256 over the other query parameters (ayeT documents the hash as optional; B64 requires it) |
| Member link | a signed B64 subject in `external_identifier`, purpose `b64-reward/ayet-subject/v1`, ≤128 chars for the provider's own limit |
| Storage | `b64_reward_event` (`0004`, additive), keyed by `(provider_id, provider_transaction_id)` |
| Ack | `200 OK` body `OK`; refusals answer 400/403/409 and write nothing |
| Closed state | `B64_AYET_MODE` absent or `DISABLED` → 503 and the rest of the site is unaffected |

A confirmed provider event is **not** money: it never writes `b64_user_income`,
and `applyProviderRewardEvent` keeps `cashCustodyAction: 'NONE'`. The income
pipeline still counts only its own `PAID` records.

### Still owner/provider work before any ad runs

- `B64_AYET_MODE`, `B64_AYET_PUBLISHER_ID`, `B64_AYET_PLACEMENT_ID`,
  `B64_AYET_REWARDED_ADSLOT_ID`, `B64_AYET_OWNER_AUTHORIZED` and the
  `B64_AYET_PUBLISHER_API_KEY` secret are **not registered anywhere**. Their
  names are fixed by `provider-runtime-config.ts`; their values do not exist
  until the publisher account, placement and ad slot do. Nothing was guessed.
- **Callback URL to set in the ayeT Placement** (D12, from the official callback
  documentation — the macro names below are exactly what this code reads):

  ```text
  https://b64-ai-reward-router.charliekant.workers.dev/callbacks/ayet/s2s
    ?transaction_id={transaction_id}
    &external_identifier={external_identifier}
    &currency_amount={currency_amount}
    &currency_identifier={currency_identifier}
    &adslot_id={adslot_id}
    &is_chargeback={is_chargeback}
  ```

  `{transaction_id}` is the duplicate check the docs require, and `{adslot_id}`
  is the field the docs say to validate when one callback URL serves several
  adslots: once `B64_AYET_REWARDED_ADSLOT_ID` is set, a callback from any other
  adslot is refused. `callback_type` is deliberately absent — the
  rewarded-video macro table does not list it, so B64 classifies the callback
  from `{currency_amount}` and `{is_chargeback}`, and still honours an explicit
  `callback_type` when a template carries one. The signature is not a template
  field: it arrives in the `X-Ayetstudios-Security-Hash` header.
- **Response policy follows the provider's retry rule** ("your server must
  always reply with an HTTP 200 status code to our postbacks, otherwise we will
  resend the postback 12 times over a span of one hour"). A refusal a retry can
  never fix — bad or missing signature, a subject B64 never signed, a
  transaction re-pointed at another member, a changed amount, a non-reward
  callback type, a foreign adslot — is answered `200 OK` and writes nothing.
  Only genuinely recoverable cases answer 503 and let ayeT retry: storage
  failure, provider not configured, a reversal arriving before its conversion,
  and a concurrent write on the same transaction. The acknowledgement is
  transport only; the stored row is the reward decision.
- Both documented canonicalizations are accepted for the signature. The PHP
  reference (`ksort(SORT_STRING)` + `http_build_query`) escapes `*` and the
  JavaScript reference (`URLSearchParams.toString()`) does not; every other
  character encodes identically, measured. A publisher cannot tell which one the
  sending server used, and guessing wrong costs a real reward. The API key is
  secret either way, so accepting the provider's own two documented recipes
  widens no authority.
- **Showing** a rewarded video still needs the ayeT JavaScript SDK
  (`AyetVideoSdk.init(...)`), and the consumer surface runs under
  `script-src 'none'`. This PR does not open that hole: the postback route is
  reachable and testable on its own, and no ad inventory is enabled by it. The
  CSP exception for the SDK origin, plus the "Send S2S Callbacks" toggle on the
  AdSlot, is a separate reviewed decision taken with the account.

## Operator authority and the read-only status console (2026-10-28, issue #6001)

The administrator rule is the repository's existing one, ported from
`apps/padiem-chat/app/b66_member_admin.py::is_google_admin`: the administrator is
the account whose **Google-verified address** equals the configured address, a
password account can never hold it, and no client-supplied flag is ever read.
What B64 checks it against is B64's own `b64_member_google` table, so no Chat
cookie, Chat user table or Chat secret is in the path.

| Setting | Value |
|---|---|
| `B64_ADMIN_EMAIL` | the single operator address. Server configuration, registered by the owner at deploy time — never committed, never logged, never rendered |
| unset | nobody is an administrator; `/admin` answers 403 to every member (an absent allowlist is a closed door) |

Routes: `GET /admin` (HTML) and `GET /admin/status` (JSON). Both are read-only —
`POST` is refused 405 — and both are behind the session cookie **and** the
authority check, so the answers are 401 anonymous, 403 `admin_forbidden` for a
normal member, 503 `admin_unavailable` when the check or the storage cannot be
performed. A failed check is never silently answered as a denial or a grant.

The console reports counts and configuration verdicts only: members, Google
linked members, live sessions, income records, reward events by state, and the
same provider assessment `npm run supply:check` prints. No address, token,
secret or setting **value** appears in the output — environment variables are
named, never shown. It is deliberately separate from `src/admin-console/`, which
is an opportunity review workflow over its own fixture state; pointing that at
production would mean building a mutation surface this task does not ask for.

Owner action to use it: register `B64_ADMIN_EMAIL` on the Worker as a var
alongside the existing bindings, then sign in with the Google account whose
verified address matches. The address designated by the owner is
`charliekant@gmail.com`, recorded here as the setting to register rather than as
a value in source.
