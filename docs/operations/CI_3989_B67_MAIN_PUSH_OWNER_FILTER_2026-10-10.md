# #3989 — B67 A6/D1 source-contract CI on owned main changes only

**Date:** 2026-10-10 KST. **Scope:** GitHub Actions trigger filters only; **no Production, Secrets, D1 query, live session or provider mutation**.

## Reproduced waste

The following two B67 source-only CI workflows were configured to run after **every main push**, including unrelated B62 browser-only PR merges and B14 model changes:

| Main commit and trigger | A6 job | D1 source job | Total |
| --- | ---: | ---: | ---: |
| `2c1e52f40074c038dcab56949aec3cb4bd9d638b` (`#4107`, B62 mock-stream visual QA only) | 10s [38035628674](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38035628674) | 11s [38035628673](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38035628673) | **21 runner-job seconds** |
| `8c18b8b9bbecb6e60d0c932b2b16bcd6bb58a00f` (B14/B66 changes) | 12s [38035508396](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38035508396) | 10s [38035508375](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38035508375) | **22 runner-job seconds** |

Both `source-contract` jobs install Python/pytest on a new Ubuntu runner before re-verifying source files unchanged by those merges. The D1 job `production-readonly` was correctly skipped because the event was a `push` rather than a specifically confirmed manual dispatch.

## Change and strict contract

For **both** existing workflows, keep the original `pull_request.paths` lists and copy the *identical* list to `push.paths`, with `push.branches: [main]` unchanged. A6: 3 exact canary script/test/workflow paths. D1: 6 exact workflow/test/Engine Drive-folder binding/document-reference/schema/wrangler paths. Keep all B67 PR checks, current job names, test suites and pytest dependency installs **unchanged** when relevant code changes.

`workflow_dispatch` is unchanged and always available. D1's live `production-readonly` remains executable **only** with the original exact-current-main approval phrase, production environment, read-only D1 queries and no provider calls. This change does not create any new workflow, job, or token permissions.

Add explicit source assertions in the existing independent A6 and D1 tests: **push-path owner list must equal PR-path owner list**, no duplicates, correct count, main branch remains and no B62/B14 blanket selection. Any future update to a B67 source dependency must update both filters together, otherwise the existing source CI will fail.

## Acceptance and limitations

Require both PR exact-head Linux `source-contract` checks, unmodified security invariants, and no material GitHub YAML behavior changes. After merge, B67-related pushes still trigger each relevant workflow; B62-only merges should trigger neither. GitHub `workflow_dispatch` D1 attestation path is **not** removed or changed.

Savings are conditional: observed **~21–22 runner-job elapsed seconds per otherwise unrelated main commit** if both would previously have fired. This is *not* a precise billed-minute claim; GH billing rounds runner usage and queue times vary. This optimization does **not** speed up actual B67 changes, the B62 pytest/Worker/Pyodide tests, or reduce protected PR test coverage.

Rollback: restore unconditional B67 main push triggers in both workflows while leaving PR and manual triggers intact.
