# #3989 — Real Worker/Pyodide four-probe phase profile (2026-10-10 KST)

## Decision boundary
The earlier [#4126](https://github.com/skerishKang/ai-revenue-lab/pull/4126) pinned npx cache was closed **unmerged** after real cache MISS/HIT measurements: the Worker job took 152s cold versus 148s warm, while the four real probe stage alone took approximately 94–97s. A 117MB npm cache did not offer reliable net wall/runner savings.

The four existing real Workerd/Pyodide scripts already run concurrently in one `B62 Worker/Pyodide contract` runner and isolate ports, inspector endpoints and SQLite persistence. Their output currently discloses only final success; we cannot safely infer if time is spent in pinned Wrangler startup, Python isolate boot/ready, local HTTP probe or assertion checking.

## Change
This PR adds **only epoch-millisecond phase markers** inside each of the four original, otherwise unchanged probe scripts:

- `B62_WORKER_PHASE_{TIMEOUT|WEB_TRANSPORT|P01_BINDING|R2_READ}_START_MS`
- `..._WORKER_LAUNCHED_MS`
- `..._READY_MS`
- `..._REQUEST_START_MS`
- `..._RESPONSE_MS`
- `..._ASSERT_PASS_MS`

The stamps use `date +%s%3N` on the actual GitHub Ubuntu Linux runner. For each probe, calculate `READY - WORKER_LAUNCHED` (Workerd readiness), `RESPONSE - REQUEST_START` (actual HTTP probe), `ASSERT_PASS - RESPONSE` (result verification). Stages **are not independent benchmark runs**; four probes contend for the same runner CPU. A failure still exits the original script at its original gate and intentionally lacks an `ASSERT_PASS` marker. No timeouts, assertion fields, test skips, version locks, dependency or required check settings change.

The original Python offline contract now verifies marker order, shell syntax and all four exact assertion gates. No new workflows or runners, no cache, no production mutation, no secrets/paid providers.

## Acceptance
1. Exact PR SHA Linux `B62 full regression`, four original real Worker/Pyodide probes, Worker bundle dry-run, classifier, B14 multimodal, `b62-test`, selected P01/Operations/Browser gates PASS.
2. Collect four *separate* `READY-WORKER_LAUNCHED`, `RESPONSE-REQUEST_START`, `ASSERT_PASS-RESPONSE` timings from raw Worker job. Do not claim performance improvement merely from instrumentation.
3. If startup dominates, investigate shared setup/CPU contention **without reducing the four independent Worker environments**. If HTTP runtime dominates, focus only on the slow probe's source and timeouts, not blanket timeout changes.
4. Preserve this tiny in-band telemetry for later comparisons; no extra CI run is required beyond the normal PR check. #3989 umbrella remains OPEN; #4071 Chat test duration profiling is a separate branch.

Rollback: revert only the `b62_probe_mark` definitions/calls and matching test/docs changes. The existing four probes and fail-closed fan-in remain untouched.
