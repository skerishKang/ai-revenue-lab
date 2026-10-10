# CI #3989 — Engine / Living Learning path ownership (2026-10-10)

## Exact dependency boundary

The Engine package (`apps/padiem-ai-engine/pyproject.toml`) directly depends on `packages/padiem-ai-core`, **not** on `apps/living-learning`. Living Learning's opt-in `requirements-padiem-core.txt` depends on the same Core independently.

Two existing PR workflows, `padiem-ai-engine-ci.yml` and `living-learning-padiem-core-ci.yml`, both run **full Living Learning pytest** and **full shared Core pytest**. Prior to this change the Engine workflow also triggered for all `apps/living-learning/**` changes, including LL-only tests, even when neither Engine nor Core changed. In that case the separate Living Learning workflow already executed those product and Core tests.

## Source-to-PR-lane matrix

| Changed source | Engine CI | Living Learning Core CI | Proof |
| --- | --- | --- | --- |
| Living Learning only | **SKIP** | RUN | LL dedicated job retains full LL + Core tests |
| Engine only | RUN | SKIP | Engine job retains Engine + Core + LL regression |
| Shared `packages/padiem-ai-core/**` | RUN | RUN | Both product consumers must pass |
| Engine + Living Learning | RUN | RUN | Union of changed-file scopes |
| Core + Living Learning | RUN | RUN | Shared Core still fans out |
| Root-only documentation | SKIP | SKIP | Operations Policy Guard remains independently triggered |
| Engine workflow modification | RUN | SKIP | Self-validation |
| Living Learning workflow modification | SKIP | RUN | Self-validation |
| Scope contract test modification | RUN | RUN | Both workflows must prove selection guards |

Source of truth: `.github/tests/test_3989_engine_living_learning_ci_scope.py` (GitHub YAML parsed with PyYAML, test matrix, required steps and concurrency invariant).

## Safety / merge contract

- Do **not** delete existing Engine or Living Learning tests: the Engine CI still invokes the full Living Learning regression on changes that impact Engine or shared Core.
- Keep `workflow_dispatch`, PR-scoped cancellation, default mock provider and existing Production/identity/credential/rollback gates untouched.
- This is a workflow **trigger** reduction, not a tests-removed change.
- If a branch protection configuration requires `engine-core-reuse` on **every** PR regardless of path, that is an invalid gate setup for a path-filtered workflow and must be migrated to a stable always-reporting context before relying on path-skipped status. GitHub branch-protection read returned 403 to the integration at audit time; do not assert a ruleset that was not read.
- The baseline #3989 example of 22 workflow runs came from a B62 SSE PR, **not** an LL-only PR. Avoid projecting that baseline onto this change.
- Verify a real, isolated LL-only PR **after** merge; count triggered workflows and check that Engine did not start, Living Learning did start, and required statuses settle. Do not claim a measured before/after reduction without actual run evidence.
- Separate B62 unified browser QA optimisation is owned by LOCAL2 PR #4046; this change edits none of that team's files.
- Rollback: revert the Engine workflow trigger change to restore `apps/living-learning/**`; do not change test steps or product code.

## Environment and deployment

This change modifies only CI workflow trigger metadata, a CI test and this operations document. No live provider calls, Secrets Store edits, Production mutation or product service code changes are authorized.

## Actual isolated before/after — 2026-10-10 KST

Two separate **Draft PRs never merged** changed the exact same harmless one-file path, `apps/living-learning/CI_3989_TEMP_PROBE.md`, with identical file content. The only intended trigger difference was #4051's Engine workflow path restriction. Both PRs finished with all their triggered GitHub workflows **SUCCESS**.

| Measured metric | Before: [PR #4052](https://github.com/skerishKang/ai-revenue-lab/pull/4052) | After: [PR #4053](https://github.com/skerishKang/ai-revenue-lab/pull/4053) | Interpretation |
| --- | ---: | ---: | --- |
| Workflow runs triggered | 4 | 3 | **1 fewer** (25% reduction) |
| Non-skipped successful jobs | 5 | 4 | Engine full CI job removed |
| Sum of successful job elapsed seconds | 270 s | 136 s | **134 s less**, 49.6% reduction in measured job elapsed time |
| Longest completed workflow elapsed time | 151 s | 88 s | **63 s less**, 41.7% reduction in observed critical path |
| Engine full CI triggered | YES | **NO** | Targeted deduplication |
| Living Learning Core full CI | PASS, 76 s | PASS, 88 s | Regression retained |
| Operations Policy Guard | PASS | PASS | Governance retained |
| B62 Unified Browser QA plan | PASS | PASS | Existing orchestrator retained |

**Before actual workflows:** Engine [37999424303](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37999424303) 151s; LL [37999424294](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37999424294) 76s; Operations [37999424373](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37999424373) 34s; B62 QA [37999424330](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37999424330) 15s.

**After actual workflows:** LL [37999595342](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37999595342) 88s; Operations [37999595372](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37999595372) 37s; B62 QA [37999595476](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37999595476) 13s. **No Padiem AI Engine CI run** was created on that head.

Job times use GitHub REST `jobs[].completed_at - jobs[].started_at` for non-skipped jobs. Workflow times use `workflow_runs[].updated_at - created_at`. Neither metric is a claim about GitHub billing rounding or total developer time. Draft PRs were not product/deployment changes.

**Implementation gate:** [PR #4051](https://github.com/skerishKang/ai-revenue-lab/pull/4051) exact-head 5/5 workflows PASS and merge `fbe4549abc33991f3874cbc75757aa5b3387f666`. Engine full run 37999366120 PASS (116s) and Living Learning CI run 37999366071 PASS (87s); source-only matrix guard enforced in Operations Policy Guard.

**Further #3989 umbrella work:** cross-product-wide routing, LOCAL2's independent [B62 browser QA PR #4046](https://github.com/skerishKang/ai-revenue-lab/pull/4046), required branch-check inventory (GitHub branch protection GET returned 403 to this integration), representative B62 frontend 22-run baseline comparison, and consolidated repository-wide queue/cache measurements remain separate. Do not close #3989 based on this isolated LL/Engine slice.
