# B64 AI Reward Router

Product-local W0 foundation for Business 64 (`ai-reward-router`). B64 is an online-first, globally designed AI side-income and reward router with Korea-priority initial UX.

## W0 contents

- `PRODUCT_CONTRACT.md` records identity, routing modes, trust boundaries, and non-goals.
- `src/index.ts` exports only stable product identity and routing-mode primitives.
- `tests/foundation.test.ts` verifies the bootstrap contract.
- `migrations/README.md` reserves the product-local migration boundary; no schema migration is created in W0.

## Commands

```sh
npm ci
npm run typecheck
npm test
```

`npm test` performs a clean TypeScript build into ignored `dist/` and runs the compiled foundation test. No network, provider, credential, database, or deployment call is performed by these commands.

## Scope boundary

W0 is intentionally small and product-local. Provider acquisition, source policy, normalized earning-opportunity schema, user state tracking, scoring, persistence, UI, and API work are deferred to separately authorized tasks.
