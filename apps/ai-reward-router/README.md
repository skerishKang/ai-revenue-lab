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

`npm test` performs a clean TypeScript build into ignored `dist/` and runs the compiled W0/W1 tests. No network, provider, credential, database, or deployment call is performed by these commands.

## W1 source-policy domain

`src/source-policy/` contains typed `Source`, `SourceEndpoint`, `SourcePolicyReview`, and `SourceCollectionGate` records, deterministic fixtures for the 22-source registry, and a pure effective-acquisition decision function. Registry inclusion, lane, acquisition mode, policy state, endpoint metadata, and collection gates remain separate. All seeded policy reviews are `PENDING`; no live collector is enabled by this W1 slice.

## Scope boundary

W0 is intentionally small and product-local. Provider acquisition, source policy, normalized earning-opportunity schema, user state tracking, scoring, persistence, UI, and API work are deferred to separately authorized tasks.
