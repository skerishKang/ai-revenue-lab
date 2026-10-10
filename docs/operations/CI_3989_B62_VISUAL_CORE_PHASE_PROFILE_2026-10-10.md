# #3989 — B62 core visual QA: exact phase elapsed profiling

2026-10-10 KST. CI runtime only; no product, test thresholds, provider, Production or Secrets changes.

## Baseline

[Exact PR Linux run 38033996872](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38033996872), before this instrumentation:
- `browser-qa` 292s, complete 16/16 browser QA jobs green; combined non-skipped jobs 1071s, workflow wall 306s.
- Within `browser-qa`, first `b62_browser_visual_qa.py` began 07:19:35 and following step began 07:21:15: about **100 seconds**. All source assertions and screenshot evidence must remain.
- Glass Shell/Zoom/Gutter are already serialized on this runner by merged #4102 to address reproducible 6.6–7.8 FPS contention. Do not reintroduce simultaneous Chromium processes.

## Implementation

`b62_browser_visual_qa.py` wraps the *original awaits*, in the same order on one Playwright browser instance, with `time.monotonic()` phase observation. It prints `B62_VISUAL_PHASE=<name> seconds=<actual>` directly in the workflow's existing step log and appends `phase_elapsed_seconds` to original `report.json`. Product source, original tests, five-turn Glass interactions, transition timing assertions, all screenshots, artifact paths, retry conditions, security settings and original sixteen CI statuses are untouched. A failed await propagates unchanged; the measured duration is still recorded for diagnosis.

Phases: `desktop`, `mobile`, `claw_tablet_820`, `glass_female`, `glass_male`, `reduced_motion`, `touch_mobile`. Duration is observational and includes screenshot I/O and renderer waits for each original phase. Timing writes for the two static reduced-motion/touch checks occur after they complete; no I/O is added inside the Glass animation windows.

## Acceptance / follow-up

Run exact-head Linux browser QA, require all original checks and evidence PASS; inspect durations to choose the real dominant phase, not arbitrary test deletion. Target the dominant implementation cost with a separate scope-proven optimization in this PR when safe. If no safe acceleration exists, retain profiling rather than falsely claim runtime saved. Compare CI workflow wall, individual job elapsed, and summed runner-job seconds separately; uncontrolled runner comparisons are not billed minute proof.
