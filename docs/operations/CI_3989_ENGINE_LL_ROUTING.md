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
