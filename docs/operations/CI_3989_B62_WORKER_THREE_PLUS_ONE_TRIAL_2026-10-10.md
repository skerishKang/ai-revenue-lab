# #3989 — 3+1 real Worker/Pyodide launch scheduling trial (2026-10-10)

## Observed bottleneck and previous negative controls

[PR #4130](https://github.com/skerishKang/ai-revenue-lab/pull/4130) merged **timestamps only**; [Linux CI #38040385829](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38040385829) proved four real concurrent Wrangler/Pyodide Workers each take 89–92s from launch to first `/ready`, while actual HTTP checks each need <1s. The **4-way original Worker job elapsed 141s**. This is observational evidence, not an isolated CPU benchmark.

[PR #4133](https://github.com/skerishKang/ai-revenue-lab/pull/4133) was **closed UNMERGED** after a two-at-a-time trial: original four real probes passed, but Worker jobs measured **119s then 171s** at the exact same head. Faster per-Worker readiness in small groups did not produce reproducible job completion improvements. [PR #4126](https://github.com/skerishKang/ai-revenue-lab/pull/4126) also stayed UNMERGED after 117MB npm executable cache failed to provide compelling net speedup.

## Trial hypothesis and isolation

**Limit simultaneous Python Worker boots to three instead of four**, then run fourth after all three conclude, on **the existing one Worker job runner**. The first group is Timeout, Web Transport, P01 binding, and last is R2 read. This is deliberately a separate strategy from the already-rejected two waves of two. There is no new runner, cache, package, install job, replay, modified Worker entrypoint, permission, fake probe or timeout change.

The original four real Python Worker scripts, pinned `wrangler@4.130.0`, **90 existing readiness iterations**, unique HTTP and inspector ports, separated `--persist-to` SQLite roots, all HTTP security/content assertions, host-lock and vendor checks, and Worker bundle dry-run remain untouched. On failure in the first group, the fourth still runs, all four original `B62_WORKER_PROBE_i=PASS|FAIL` records are printed and fail-closed `B62_WORKER_PROBES=FAIL` propagates to `b62-test`. Added network-free mock tests prove three parallel starts before fourth, all-four execution and failure propagation. All existing B14, browser-planner, Operations Policy and selected P01 checks must still succeed on the exact head.

## Acceptance and rollback

1. Compare exact-head Linux PR Worker job against the contemporaneous original 4-way **141s** and 2+2 **119s / 171s** (do not claim controlled causal savings on different ephemeral runners).
2. Extract four measured `B62_WORKER_PHASE_..._WORKER_LAUNCHED/READY/REQUEST_START/RESPONSE/ASSERT_PASS` stamps. All four real Workerd probes and bundle must pass, no readiness gate weakening.
3. If faster on first run, rerun **only the existing Worker job once at the identical SHA**. Merge only if both runs show a *meaningful, reproducible* elapsed and end-to-end critical-path benefit with no skipped guards. Do not rerun 16 unrelated browser lanes.
4. If slower/unstable, close PR unmerged and retain already-merged phase timestamps in main. `#3989` remains open.

No production deployment, Cloudflare Secrets changes, paid model calls, explicit workflow dispatch or extra runner.
