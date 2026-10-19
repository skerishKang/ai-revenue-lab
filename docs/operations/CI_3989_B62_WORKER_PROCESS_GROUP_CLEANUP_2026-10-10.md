# #3989 — Real Worker/Pyodide orphan-process lifecycle cleanup (2026-10-10 KST)

## Evidence from the current main (not a conjectured speedup)

In [latest successful main B62 CI #38043025150](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38043025150), the real `B62 Worker/Pyodide contract` job took **149 seconds** (host Chat/Core **77 seconds**, B14 multimodal **14 seconds**). Its four real Workerd probes all passed; original `npx --yes wrangler@4.130.0 dev` sessions then returned. GitHub's runner post-job cleanup nevertheless logged **eight** `Terminate orphan process: pid (...) (workerd)` records. Original bash probe `cleanup()` killed only `WORKER_PID=$!` (the **npx launcher**), not its descendant `wrangler`/Workerd process group.

This leaves resource-consuming process descendants until GitHub terminates them at job shutdown. Do **not** attribute 149 seconds to this alone; Workerd launch-to-ready dominates (~93–97 seconds in that run), and CPU contention is variable. This change's primary claim is process lifecycle correctness, reducing orphan leakage and possible cleanup overhead. The critical path benefit must be measured separately, not inferred.

## Scoped solution

All four unchanged real `.github/scripts/b62_worker_probe_{timeout,web_transport,p01_binding,r2_read}.sh` scripts launch **their existing exact pinned Wrangler command** through `setsid` (util-linux present in GitHub ubuntu-latest) to create a unique Linux process/session group **per probe**. The recorded `WORKER_PID` is then the new group ID. Their existing `trap cleanup EXIT` now sends bounded TERM to only `-$WORKER_PID`, a short 0.2s grace, KILL to that **same isolated group**, and `wait` on the direct launcher. The two local test HTTP-origin servers are still killed and waited, and each independent Workerd SQLite state and generated TOML are removed. The wrapper runner continues launching all four real probes *in parallel*, preserving separate listener and inspector ports/state and the original fail-closed wait markers.

The offline contract checks syntax, pinned Wrangler command, every existing real probe, precise TERM-then-KILL order, and verifies on an isolated real Linux process-group canary that a group's descendant receives TERM while the Python test runner retains a distinct process group. No dummy/fake Worker replaces a real runtime check in CI.

## Acceptance (one normal PR CI, avoid expensive reruns)

1. Exact-head B62 Linux CI full Chat/Core regression, four real Worker probes with all original HTTP and 90-attempt readiness gates, Python Worker bundle dry-run and lock guards, B14/Operations/GitGuardian, the appropriate Browser QA planner and `b62-test` PASS.
2. In post-job Linux Worker logs, inspect whether `Terminate orphan process (workerd)` count declines from the **8-process main baseline**. Distinguish surviving zombies from runnable descendants; a GitHub cleanup log alone cannot show whether they were still actively working. Do not claim all are fixed if evidence conflicts.
3. Record Worker elapsed, start-to-ready stamps and final wall critical path relative to the current ~149s Worker / 77s Host example, noting ephemeral runner variability. This one clean lifecycle fix need not show a major speedup to be worthwhile, but **must not add meaningful runtime, new failures or remove any tests**. If groups are not isolated or regression occurs, close PR unmerged and restore bare `npx` + original cleanup.
4. No new runner/Workflow, cache, dependency upgrade, Python import/edit, Production/Cloudflare deploy, Secrets, provider call or change to required check names. Keep #3989 OPEN.

## Rollback
Remove only the four `setsid` prefixes and added group cleanup signals/waits, and the matching test/docs. All original runtime configs, ports, package pins and assertions remain intact.
