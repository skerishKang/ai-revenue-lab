# #4101 — B62 Glass visual evidence: host rendering starvation

**2026-10-10 KST.** CI-only corrective patch. A regression in the prior #3989 visual-tail scheduler's **on-runner Chromium concurrency**, not a justification to weaken visual or timing assertions.

## First-party Linux evidence before editing

- Full [38030917850](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38030917850) (original #4097 bounded-2 tail) was green once, proving source was runnable but not proving repeated timing stability.
- [38032101992](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38032101992) first attempt (apt mirror widened on ephemeral runners): `b62_browser_visual_qa.py` early screenshot timing caught `progress=0.671`, original strict minimum `0.68`, fail.
- **One** failed-job rerun on the same immutable source SHA: first standalone browser visual suite PASS, but bounded-2 tail ran independent Chromium shell, zoom and gutter suites on the **same Linux runner**. Glass shell failed `TimingOvershoot` after three exact-threshold attempts: peel `4390ms > 3600ms`, measured **6.6 FPS**, and Glass Zoom failed an unmodified reading-state assertion. The gutter suite PASS. Source job #114155480753.
- Restored the exact *two-lane-only* apt mirror pilot in PR #4098; [38032571645](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38032571645) still fails the original Glass Shell reassembly timing after three attempts: **4235ms > 3600ms**, **7.8 FPS**, while Zoom and Gutter PASS, and 15 other independent QA jobs/P01/Policy PASS. Job #114156453135.
- The evidence supports **renderer starvation under two local concurrent Chromium processes** as a plausible proximate cause for shell failures; it does **not prove** the 0.671 early-frame failure or a mirror causal relationship. Global mirrored apt downloads all completed successfully and all OS packages remained installed.

## Exact minimal mitigation

- Keep `.github/scripts/b62_browser_qa_tail_parallel.py` and the existing `browser-qa` job/status/artifact path, unchanged full `b62_glass_shell_visual_qa.py`, `b62_glass_zoom_visual_qa.py`, `b62_chat_gutter_visual_qa.py` source/test assertions and 240s individual timeouts.
- Set scheduler **MAX_PARALLEL=1**, execute **all three** unmodified suites in original fixed order, capture each complete evidence stream and return failure if any one fails or times out. Mock-only guard remains mandatory.
- Update the existing stdlib-only CI contract test to pin single active process at a time and the exact source suite order; all other checks remain.
- This trades off up to ~35 seconds of historical per-browser-job wall-time savings from #4097 for test reliability. Do not claim cost savings from this **stability** fix. It can unblock separately measured apt archive improvements without modifying/weakening any product gate.

## Acceptance

Use exact-head Linux source-contract unit results, actual `browser-qa` all three PASS with logs `B62_VISUAL_TAIL_EXECUTED=3` and `B62_VISUAL_TAIL_FAIL_COUNT=0`, all other PR selected browser checks/P01/Operations guard PASS. Avoid repeated blind whole-repository suites. Inspect any later failure with actual page-clock state and FPS; retaining any reproducible failure is preferable to a relaxed assertion.

**Rollback:** revert this PR to the earlier max two parallel processes if evidence proves stability and cost advantage safely, while preserving all three source suites. Production/Secrets/provider mutations: **none**.
