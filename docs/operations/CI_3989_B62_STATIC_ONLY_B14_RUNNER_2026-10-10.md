# #3989 — B62 static-only B14 runner scope (2026-10-10 KST)

## Measured starting point

Read-only audit of the most recent 300 GitHub Actions runs on 2026-10-10 (three pages of 100, not the whole repository history):

| Workflow | Runs | PR | main push | Sum of run elapsed seconds (NOT runner seconds) |
| --- | ---: | ---: | ---: | ---: |
| B62 Padiem Chat CI | 47 | 32 | 15 | 12,238 |
| B62 Unified Browser QA | 48 | 48 | 0 | 2,666 |
| Operations Policy Guard | 50 | 50 | 0 | 1,719 |
| B67 Drive Case Folder A6 source contract | 30 | 0 | 30 | 474 |
| B67 D1 Read-only source gate | 30 | 0 | 30 | 442 |

The sum of overlapping run durations is **not** GitHub-billed runner time or the end-to-end critical path. Separate per-job runner accounting and cache-hit accounting are not yet available from this sample. Both B67 gates currently explicitly contract-test execution on every main push, so their intentionally broad push gates are unchanged.

Example real B14 multimodal job from B62 main CI run [38010112006](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38010112006): job log spans approximately 00:41:31 to 00:41:49 UTC (~18s), including environment/bootstrap. This is a **sample log timespan**, not a billed duration, controlled speedup, or guarantee for future runs.

## Strict scope improvement

B62's existing fail-closed changeset/impact classifiers already distinguish:

- `model_registration_only`: dedicated quick registry lane, all large jobs skipped.
- `static_only`: **only** added/modified files within `apps/padiem-chat/static/**`, at most 100 unique paths, with exact authoritative PR or push diff. Malformed, deleted, mixed, missing-token, network/API or manual cases yield `full`.
- `chat_only` or `full`: existing backend and B14 pilot checks remain.

Previously, `b14-multimodal-test` ran even on strictly `static_only` B62 changes. Its inputs are under `apps/korean-ai-platform` and its pilot source does not depend on B62 static assets. The B62 host regression, lock checks, Worker bundle dry-run, and applicable browser/static security jobs continue unchanged.

On **only** `static_only`, skip the otherwise invariant B14 multimodal **job runner**. Keep the original job ID and the `b62-test` required gate: that aggregator must reject a non-skipped B14 result for this lane, and require B14 SUCCESS for every other full lane. B14 source changes and unknown scopes continue to run it.

## Proof / release restrictions

- No test files, assertions, security policy, deploy/Secrets or backend source removed.
- Exact CI implementation changes themselves classify as `full` and run B14 pilot.
- Added source contract in `.github/tests/test_3989_b62_parallel_runtime_jobs.py` to pin both the B14 condition and the fail-closed aggregate result.
- PR HEAD Linux CI, post-merge main, and a representative genuine static-only path probe are tracked independently. Do not claim measured resource savings until an actual static-only job is verified.
- Rollback: revert the workflow conditional, `SCOPE` aggregate branch, and contract test in one PR. Original B14 job always runs on all non-registration lanes.
