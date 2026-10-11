# #3989 — B62 Browser QA visual-tail bounded concurrency

**2026-10-10 KST**, scope exclusively GitHub Actions test runtime. No B62 product source, B14, Engine/Core, Cloudflare, Production or Secrets modification.

## Actual Linux baseline

A successful representative full QA run [38009772215](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38009772215) selected 15 of 16 browser QA lanes: **918 summed non-skipped job elapsed seconds**, **271 workflow elapsed seconds**, **258 seconds for the `browser-qa` job**. These are observed GitHub job timestamps, not billed runner minutes or controlled A/B measurements.

The 258-second browser-qa job's logged step starts reveal:

- Core desktop/mobile visual QA starts at ~00:37:08 and next step begins ~00:38:38 (about 90s).
- Three independent visual tail scripts begin ~00:39:20 (`glass_zoom`), ~00:39:42 (`glass_shell`) and ~00:40:36 (`chat_gutter`): approximately **22s + 54s + 14s serialized**.
- Browser dependency bootstrap ~14s runs per selected lane with cached browser binary but OS dependencies **actually install nine packages**. **Do not remove `--with-deps`**; it would weaken Chromium runtime correctness on GitHub-hosted runners.

These figures are from one real run of another commit and thus only a baseline to compare observationally.

## Exact, fail-closed changes

- Keep original **16 job IDs/status checks**, output names, artifact paths, per-lane selection, own self-test, pinned Playwright Chromium and Linux dependency installation. All earlier individual browser-qa suites stay sequential.
- Only the three tail visual suites with distinct report families run with **two** Python subprocesses concurrently on the **same** runner/server: `b62_glass_shell_visual_qa.py`, `b62_glass_zoom_visual_qa.py`, `b62_chat_gutter_visual_qa.py`.
- Each subprocess launches an independent Playwright browser and page contexts, and writes its original unique report / screenshot family to the original artifact directory; no scripts or individual assertions modified. No live provider access; require `PADIEM_CHAT_RUNTIME_MODE=mock`.
- The wrapper uses the same active Python venv, captures all three outputs, applies a **240-second per-script bound**, waits for all three, reports PASS/FAIL per script, and exits nonzero if **any one** fails or times out.
- Changes to scheduler or its own test run all 16 lanes via `PLAN_FILES` fail-open ownership. Existing `plan` job runs a new stdlib-only contract test proving all scripts retained, no third concurrent subprocess, runtime confinement and fail-closed failures.
- No new runner/job, no workflow status renames, no ignored tests/xfail, no changes to browser artifacts/Production/Secrets.

## Release and measurement

Capture exact-head Linux `plan` + all applicable lanes, particularly `browser-qa`, and confirm every original report and screenshot in the artifact. Compare **job elapsed seconds, full workflow wall seconds, and sum of non-skipped job elapsed seconds** separately. A source-only green plan is insufficient to merge: real browser job and selected sibling lanes must succeed. Repeat against a fresh exact-head Linux PR run if runtime overlap or animation timing becomes flaky; revert if repeated regressions.

**Rollback:** single revert of this PR to restore the three original sequential YAML steps, remove wrapper/test and planner entries. Do not alter required check/status names.
