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
