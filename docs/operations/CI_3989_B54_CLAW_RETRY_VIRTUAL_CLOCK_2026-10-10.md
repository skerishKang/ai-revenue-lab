# #3989 — deterministic virtual-time B54 Claw execute-retry harness (2026-10-10)

## Evidence and bottleneck
The existing [PR #4071](https://github.com/skerishKang/ai-revenue-lab/pull/4071) (owned by another team; unchanged) captured slowest tests on real GitHub Linux [CI #38005362137](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38005362137): three B54 execute retry UI assertions each reported ~19.16 seconds, password-auth abuse safety ~16.73 seconds. The B54 file in current main ALREADY has a **module-scoped fixture**, so the three assertions consume **a single** real Node harness execution in current code. Do NOT claim to save 3 x 19s: the remaining per-file ~19s is real `setTimeout` wall-clock waiting for Retry-After 3/2-second cooldown and other safety checks.

## Narrow, provider-free change
Only `apps/padiem-chat/tests/test_b54_claw_execute_retry_ui.py` changes (no actual app.js, auth routes, production code, public UI, dependency version, workflow, test selectors, or security gates). The embedded Node VM harness still executes the **unmodified real app.js**, recording the exact existing HTTP requests and DOM behavior. Replace only the Node VM's `Date`, `setTimeout`, `setInterval`, `clearTimeout` and `clearInterval` with a deterministic virtual clock and execute the *scheduled timer callbacks in order at their original due times* whenever the test harness `tick(ms)` advances simulated time. Node microtasks flush after every callback and at the end of each tick. A 10,000-callback guard fails closed rather than hang. No callback or assertion is dropped; 3-second and 2-second countdown transitions and the 900-second clamped cooldown still occur in simulated time, including the "no automatic POST" and uncertain-dispatch protections.

## Offline results, measured on separate authorized Windows terminal (no production)
- Original HEAD-extracted `_HARNESS` against current `static/app.js`: **19.595 seconds**, `ok=true`, **31/31 behavioral result checks** PASS.
- Identical harness with only virtual-time injection: **0.059 seconds**, `ok=true`, **31/31 same behavioral checks** PASS; assertions unchanged.
- Isolated Windows `pytest -q tests/test_b54_claw_execute_retry_ui_candidate.py` after setting `PYTHONUTF8=1`: **14 passed in 6.40s**. An initial Windows subprocess attempt without UTF-8 failed while decoding Korean test copy; this is a **Windows cp949 output-decoder setting**, not an app code or simulation failure. Linux GitHub uses UTF-8 and the production test's subprocess code is unchanged.

## Actual Linux merge acceptance
1. Exact-head GitHub `B62 Padiem Chat CI` full host suite and real 4/4 Workerd/Pyodide probes, package locks, worker bundle dry-run, B14 classifier/multimodal, final `b62-test`, Operations Policy/Browser selector/GitGuardian PASS.
2. Confirm `B54` three existing test names all remain selected and PASS, and the real Chat test count never drops versus current main (any extras reflect unrelated concurrent commits).
3. In the Linux host log, verify the actual Chat pytest duration and compare to corresponding main runs; avoid attributing host variance, password KDF slow tests or Worker critical path to this change. Do not rerun full workflow needlessly.
4. If tests fail, rollback only the deterministic Node VM timer shim and restore the real-time `tick()`; don't alter any runtime production security gate.

Umbrella #3989 stays OPEN. #4071 remains independently owned, untouched. No workflow dispatch, Production deployment, Secrets changes, paid provider calls, KDF weakening, or removal/skipping of tests.
