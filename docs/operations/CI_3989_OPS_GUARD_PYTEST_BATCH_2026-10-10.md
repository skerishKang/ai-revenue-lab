# #3989 — Operations Policy Guard pytest process economy

**Date:** 2026-10-10 KST. **Scope:** CI runner overhead only. No Production/Secrets/provider changes.

## Existing exact production behavior

`.github/workflows/operations-policy-guard.yml` has two independent PR jobs:

- `Operating policy consistency` — ~28–33 observed runner-job seconds across three representative recent runs; executes nine sequential `python -m pytest -q` processes (ten distinct target paths) and two direct fail-closed source scripts.
- `Pull request contract report` — ~7–8 observed runner-job seconds; separate advisory PR-body scan and original status context.

Three recent complete runs: [38009938216](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38009938216), [38010375240](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38010375240), [38010607217](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38010607217). Their non-skipped job elapsed-time sums are approximately 35s, 37s and 40s. These are **job elapsed seconds, not billed minutes**; separate run wall-clock seconds are 31s, 32s and 36s respectively. Changes to test source, runner load and cache can affect samples; no controlled A/B claim.

## Change and safety boundaries

- Retain **both original job IDs and human-readable check names**, required/advisory status behavior, `pull_request` without paths filters, `workflow_dispatch`, group cancellation and read-only token permissions.
- Retain **all ten existing pytest target paths** without `-k`, `-x`, skips, retries or hidden xfail changes. Execute them in one pytest collection/interpreter process instead of nine sequential pytest process startups.
- Keep both direct `cross_lane_test_dependency_guard.py` and `frozen_source_checkout_byte_guard.py` checks as separate blocking shell steps.
- Add `.github/tests/test_3989_operations_guard_pytest_batch.py` to the same collection, permanently pinning original check-name and test-target coverage.
- Preserve `PR_CONTRACT_GUARD_MODE=REPORT_BY_DEFAULT`, repository governance, B66 archive safety tests, R2 credential authority tests, trigger scope and Engine/LL guards.

## Measurement and acceptance

Before/after reports must separate **workflow wall time**, **sum of non-skipped job elapsed seconds**, **pytest test counts**, status context names and test failures. A change in isolated collection may expose fixtures/process-state coupling: if so, restore separate pytest processes rather than skipping cases. Target reproducible Linux PR + postmerge `main` results and avoid modifying any unrelated product/test implementation.

**Rollback:** revert this one workflow refactor and its companion contract test in a new PR; existing GitHub Actions check names do not change.
