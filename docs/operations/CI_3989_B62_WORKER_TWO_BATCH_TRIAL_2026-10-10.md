# #3989 — two concurrent real Worker probes per batch (performance trial, 2026-10-10)

## Measured baseline (not a prediction)
Merged [#4130](https://github.com/skerishKang/ai-revenue-lab/pull/4130) provides in-band Linux timestamps while retaining four real, isolated Workerd/Pyodide probes. [Exact-head CI #38040385829](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38040385829) PASS: 4-way parallel real Worker job **141s**; full Chat/Core job **100s**. Launch-to-ready durations: Timeout **89.261s**, Web transport **92.464s**, P01 binding **91.389s**, R2 read **89.842s**. HTTP requests, by contrast, took 0.421s / 0.829s / 0.032s / 0.024s. The 90 × 1s bounded readiness loop was close to exhaustion. CPU contention from simultaneously booting four Pyodide runtimes on the usual two-vCPU GitHub Linux runner is a **hypothesis**; do not claim causality or speedup without a new genuine Linux run.

## Change
Within the **same existing** `b62-worker-suite` job and `b62_worker_probe_parallel.sh`:
- Start the original **timeout + web transport** probes simultaneously, wait for both and emit both unchanged logs, then start the original **P01 binding + R2 read** probes simultaneously and wait for both.
- All four original scripts, original pinned `wrangler@4.130.0`, distinct ports/inspector/persistence roots, environment setups, substantive HTTP assertions, exact `PASS` markers, original 90-attempt readiness window, locked vendor deps, B14 checks and Python bundle dry-run remain untouched.
- Run batch 2 **even if batch 1 failed**, record all four results, and fail the entire Worker job and final `b62-test` if any fails. No false PASS, new runner, changed required status name, different environment or tests skipped.
- Offline integration contracts (mock probes, no network/Cloudflare) enforce max two concurrent workers, both batches run, and first-batch failure is not hidden. Existing negative first-use npm preflight test remains.

## Merge acceptance (actual measurement required)
1. One exact-HEAD Linux PR full run succeeds for original 3,657+ Chat / 2,000+ Core cases, all 4 real Workerd probes and assertion markers, Worker bundle dry-run, B14, policy, browser planner, P01 when selected and stable `b62-test`.
2. Capture all four `B62_WORKER_PHASE_...` milestones from Worker log. Compute launch-to-ready, request, assertion and full Worker job elapsed. Compare to original four-way [#38040385829](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38040385829) and representative newer main with revision/runner caveat.
3. If first exact-head PASS is faster, rerun **only original Worker job once** to check stability; never rerun all workflows needlessly. Adopt only if elapsed/runners improve without security/test weakening and without worsening readiness risk. If slower or unstable, **close trial unmerged** and retain merged profiling instrumentation as authoritative.
4. GitHub job wall time differs from summed runner-seconds and charged minutes, which have rounding/other factors. No billable savings assertion without accurate accounting.

Rollback: restore the original four-way launch/wait loops in `.github/scripts/b62_worker_probe_parallel.sh`, and remove the corresponding two offline contract tests and this document. No Production/Secrets/provider mutation.
