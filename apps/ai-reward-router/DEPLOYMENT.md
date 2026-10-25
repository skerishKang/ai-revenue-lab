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
| `PADIEM_CHAT_SERVICE` (service) | Binding to the deployed chat product worker, declared like the existing reference bridge (`reference/business-66-padiem-quote-v1/_worker.js`). Forwards the session cookie to chat's revocation-aware `GET /api/auth/status` so logged-out/revoked canonical sessions are blocked | Offline signature + expiry verification only (same posture as the `padiem-designer` precedent); revocation blocking is inactive until the binding is configured |
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
