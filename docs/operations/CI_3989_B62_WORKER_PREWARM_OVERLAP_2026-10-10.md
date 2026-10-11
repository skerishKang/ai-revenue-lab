# #3989 — B62 Worker Pywrangler vendor and pinned Wrangler prewarm overlap

**2026-10-10 KST.** CI-only startup optimization; preserving all four real Worker/Pyodide probes, full Pywrangler lock sync, checks and dry-run.

## Baseline from real GitHub Linux worker logs

[Run 38036615200](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38036615200) full B62 CI SUCCESS: Worker job **175s**, B62 full regression **199s**, B14 multimodal **14s**, required `b62-test` aggregation PASS. Within Worker job:

- `uv run --locked pywrangler sync --force`: from **08:04:57.787** to **08:05:22.855** (about **25s**, including Pyodide 3.13.2 and Python 3.13.15 runtime downloads; 16 locked worker dependencies installed and Core vendored).
- `npx --yes wrangler@4.130.0 --version`: from **08:05:23.253** to `B62_WORKER_NPX_PREWARM=PASS` **08:05:33.965** (about **11s**, first-use pinned npm package preparation).
- Four real Workerd/Pyodide probes then ran **concurrently**, with a unique Wrangler port/inspector/config/persistence state each, in about **129s**, all PASS. This is expensive but real runtime coverage and **must not be replaced by mocks or omitted**. Final `uv run --locked pywrangler deploy --dry-run` completed and verified bundling.

Previously these **independent preparations were sequential**: ~25s + ~11s before running any real probes.

## Minimal optimization

Introduce `.github/scripts/b62_worker_prewarm_overlap.sh` in the original, unchanged-named `Pywrangler dependency sync from committed pylock` job step. It launches the **exact same** `uv run --locked pywrangler sync --force` and **same pinned** `npx --yes wrangler@4.130.0 --version` side by side, waits for **both**, checks the exact `4.130.0` stdout marker, retains the original logs, and fails the entire job if either fails. The vendor command writes `python_modules`/`.venv-workers`; the pinned npm command writes npm's `_npx` cache, not vendor files.

Only after **both** have succeeded does it emit `B62_WORKER_NPX_PREWARMED=1` through `GITHUB_ENV`. The existing real-probes wrapper consumes this same-job marker to **avoid repeating** the Wrangler prewarm, while retaining its original pinned fail-closed prewarm for standalone invocations. An offline mock-only contract confirms both independent commands start before either completes, and a failure or wrong Wrangler version prevents the marker and any real probe run.

All four real Worker tests, their preserved output markers, 90s readiness windows, locked Worker dependencies, lock immutability checks, Core vendoring, Worker bundle dry-run, all B62 full regression and B14 checks, and final required `b62-test` result are unchanged. No new runners, no Production, paid models, or Secrets mutation.

## Acceptance and accounting

Require exact-head Linux B62 Worker/Pyodide contract **SUCCESS** with all four real probe markers, one Wrangler prewarm verified, host/vendor lock checks PASS, and original dry-run. Source contract and policy checks must PASS. Compare job elapsed, actual vendor/first-use prewarm and the total CI wall time separately. The intended maximum overlap is about **11s in the worker job**; the workflow critical path may remain dominated by ~199s full regression, so do **not** claim it saves workflow wall time or billable minutes without measurement.

If concurrent preflights conflict, slow down unexpectedly, or violate security checks, revert this PR; never suppress an individual probe failure or replace a real Worker invocation with a mock. Production and Secret changes: zero.
