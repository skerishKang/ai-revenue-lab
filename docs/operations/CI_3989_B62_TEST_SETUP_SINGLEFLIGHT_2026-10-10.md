# #3989 — Reuse identical expensive test setup while preserving real authentication / UI safety (2026-10-10 KST)

## Verified source inventory

On source `main` `09970fea2e215de2ebd132b81da61afc1affb42b`, the B62 password authorization suite `tests/test_password_auth.py` calls the real `hash_password("correct horse battery staple")` in **22** independent places. It invokes production PBKDF2-SHA512 **220,000 iterations** each time; one is an explicit cryptographic contract test, while **21 others** just provision the *same correctly hashed known credential* in isolated in-memory account/abuse/lockout scenarios. The production password **verifier** must remain real for every login (including decoy identities, abuse budgets and equality), the registration endpoint must keep genuinely hashing new passwords, and the dedicated hashing roundtrip must independently derive a fresh salt/hash.

This branch introduces a **zero-argument** `@lru_cache(maxsize=1)` helper in that test file which calls unchanged production `hash_password` once. Replace only the 21 repeated **fixture creation** assignments with this helper. Keep the standalone password hashing roundtrip test directly calling `hash_password`; full auth/login/abuse/counter/KDF public-header/oracle tests, all verify calls, all account identities and test names remain intact. The helper caches a real correctly derived 220k-iteration PBKDF2 hash, not a fake/weak hash. No changed credential secrets, policy constants, auth implementation, mock of verifier, or persisted prod fixture. Prior randomized-salt/per-call hashing and registration tests remain real; the shared static fixture's salt differs no more often than needed to test the identity state machine.

Also, six existing B62 UI test modules repeat the same **zero-arg real Node VM app.js** behavioral journey:
- B54 execute progress: 3 → 1
- B54 truthful result action: 2 → 1
- B54 run history copy: 2 → 1
- Calendar work log create: 2 → 1
- Claw automation create: 2 → 1
- Claw automation enable toggle: 2 → 1

Six modules reduce 13 identical starts to 6 (7 duplicate Node subprocess launches avoided). No independent scenario with script input or dynamic per-test arguments is cached. Every existing named test still asserts every original check against the same exact on-demand real JS result, and a failed harness is never cached. `lru_cache` is process-local, recreated each CI job. All original direct `__main__` invocation paths still execute their tests. The earlier [#4150](https://github.com/skerishKang/ai-revenue-lab/pull/4150) 4-module optimization remains untouched.

## Why this is bounded CI optimization, not security weakening

- B62 password hashing policy and the real verifier are **unchanged**. `test_password_hash_roundtrip_and_validation` and all real registration tests call production hashing.
- Login, identity/equality, public response timing/copy, lockout and abuse budget test paths execute as before. `verify_password` is **not stubbed or memoized**; only 21 identical fixture-hash constructions are deduplicated.
- The Worker code/scripts/config/lockfiles, all **four real Workerd/Pyodide probes**, Python Worker bundle, B14 and Core tests, GitHub Actions job graph, status names and required checks are unchanged.
- No new runner, extra workflow, production deployment, secret mutation or paid provider invocation.

## Exact-head acceptance

One ordinary GitHub PR trigger should verify **all prior 3708+ Chat pytest cases**, the eligible 2000+ Core pytest suite, B14 multimodal and classifier, four *real* Workerd/Pyodide probes and bundle dry-run, browser impact planner, Operations Policy, GitGuardian and final `b62-test`. Comparison baseline [latest complete main CI #38044545043](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38044545043): full host **120s**, Worker **142s**. Runtime variation across ephemeral Linux runners is high: compare exact tests counts and Chat pytest duration, do not attribute every wall delta to this patch or claim reduced Python Worker critical path.

Rollback: remove only the seven test-file `lru_cache` additions and revert fixture callsites to direct unchanged hashing. Keep #3989 OPEN for true Worker startup performance and overall fanout audit, and do not touch independently owned #4071 profiling PR.
