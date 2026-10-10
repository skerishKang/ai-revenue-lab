# #3989 B62 parallel host/Worker CI jobs (2026-10-10)

## Measured bottleneck (GitHub PR #4061, run 38006046376)

The successful B62 full regression ran Python tests, Core tests, Worker package preparation,
and four real Worker/Pyodide probes **sequentially in one GitHub Actions job**.

| Phase | Actual elapsed seconds |
|---|---:|
| Chat pytest (3,616 cases) | 157 |
| Shared Core pytest (1,955 cases) | 54 |
| Pywrangler sync from committed pylock | 25 |
| Four real Worker/Pyodide probes already parallel within their shell helper | 102 |
| Entire B62 full regression GitHub job (including setup and bundle dry-run) | ~360 |

Source: https://github.com/skerishKang/ai-revenue-lab/actions/runs/38006046376
The workflow run wall time was about 381 seconds including planner and the final aggregate.

## Change and safety guarantees

- Keep the existing, stable `b62-test` success/failure check (no change in its name).
- Split `b62-full-suite` (3,616 Chat tests, required Core tests, JS syntax, lock verification)
  from `b62-worker-suite` (same locked environment, pylock sync/vendor checks,
  four actual Worker probes, and Python Worker bundle dry-run). Both jobs depend
  **only on the existing fail-closed registry/impact planner**, so GitHub may run
  them in parallel.
- The final `b62-test` gate **requires both** jobs to be `success` in a full
  lane; any failure, cancellation, or unintended skip blocks it. The registry-only
  fast lane still requires its narrow contract and both heavy jobs to be `skipped`.
- Existing `static_only` skip applies **only** to the real Worker/Pyodide probes.
  Existing Core skip applies only to `chat_only`/`static_only`.
  No pytest case, lock/security validation, vendoring assertion, or bundle dry-run
  was dropped. Worker re-installs its dependencies on its own clean runner.
- Trigger path parity between PR and main push remains exact. New policy tests
  run as part of the planner and are explicitly included in both trigger paths.
- No changes to production deploy, secrets, providers, Cloudflare configuration,
  Python production code, or shared Core.

## Performance accounting

This reduces **critical-path wall time**, not necessarily total GitHub runner-minutes:
the Worker job provisions a second runner and performs an independent locked
environment setup. Based solely on the measured 2026-10-10 run, host/worker
parallel execution could put the long phases on concurrent paths, but **no
speedup is claimed until exact-head GitHub Actions actually runs**.

## Verify and rollback

1. Run the local policy contracts and `docs/operations/tests/test_ci_scope_policy.py`.
2. On PR exact head, inspect `B62 full regression`, `B62 Worker/Pyodide contract`,
   `B14 changeset classifier (fail-closed)`, `b14-multimodal-test`, and `b62-test`.
   Require success in all applicable jobs and check the four Worker probe logs.
3. For static-only, model registration-only, and shared Core changes, verify the
   existing scope semantics; a skipped or failed selected job must fail `b62-test`.
4. Compare wall time and runner-job duration with run 38006046376 while noting
   different source changes, runner queue and cache variation.
5. Roll back by reverting the single PR commit restoring the original sequential
   workflow. Do **not** change the required status name or GitHub settings.
