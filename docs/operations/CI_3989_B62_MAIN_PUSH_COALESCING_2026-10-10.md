# #3989 — Coalesce superseded B62 main-push CI (2026-10-10)

## Problem confirmed in GitHub Actions

The current B62 workflow's concurrency group previously used `github.event.pull_request.number || github.run_id`. A PR received a stable number and cancelled older commits, but **each main push was grouped by its distinct run ID**. Real overlapping B62 full-suite main runs:

| B62 main workflow run | Commit | Started (UTC) |
|---|---|---|
| [38009178502](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38009178502) | `51bea82e679` | 2026-10-10 00:28:11 |
| [38009215242](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38009215242) | `da4ab531b94` | 2026-10-10 00:28:45 |

Both were still **in_progress** simultaneously when checked, although the later B62-relevant main revision contains the earlier merged source. Each full B62 run can consume roughly 2–4 Ubuntu runner jobs for 2–4 minutes, including ~3,639 Chat pytest cases, shared Core conditionally, and four real Worker/Pyodide probes.

## Minimal change

Only the test-only `.github/workflows/b62-padiem-chat-ci.yml` concurrency group is changed to distinguish events:

- `pull_request`: `b62-padiem-chat-ci-pr-<PR number>` — PRs are independent; an updated commit to the same PR cancels the superseded run.
- `push`: `b62-padiem-chat-ci-push-refs/heads/main` — only the most recent B62-relevant main push finishes full validation; an older main run is intentionally cancelled.
- `workflow_dispatch`: `b62-padiem-chat-ci-manual-<unique run ID>` — independently initiated diagnostics never cancel a main or PR run, or another manual run.

`cancel-in-progress: true` remains. GitHub's documented workflow-level concurrency implements these guarantees. This does **not** change `on.push.paths`, `pull_request.paths`, the fail-closed B14/B62 changeset planner, full tests, Worker probes, vendor locks, `b62-test` aggregator, or required check names.

## Safety boundaries and tradeoffs

- **A cancelled superseded main run is intentionally not PASS.** The later qualifying main run is the one that must complete and verify the cumulative main source; investigate any latest run failure rather than reporting cancelled old runs as green.
- A push with *no* B62-matching path does not start a B62 job or cancel the previous B62 run; a newer *matching* main push checks cumulative state.
- PR required statuses are unaffected because PRs have their own keyed groups; `b62-test` still runs and must resolve on the current PR head.
- No Production, deploy, schema migration, credentials, B14 provider runtime, B66 product code, or non-cancellable Cloudflare mock deploy concurrency is modified.
- Run cancellation can reduce redundant **runner-job seconds** for burst merges; it may not reduce latency for the *final* main revision, and cancelled historical SHAs will show cancelled rather than success. Never treat a cancelled historical SHA as independently verified.
- Neither the exact runner-minute savings nor an end-to-end cancellation event is claimed prior to observing future overlapping **main push** runs. Prior evidence proves only redundant overlapping runs, not the post-change saving.

## Verification / rollback

1. Existing `docs/operations/tests/test_ci_scope_policy.py` pins the precise expression and checks event-group isolation and stable `b62-test` contract.
2. Require exact-head PR B62 full suite, 4 real Worker probes, B14, and Operations Policy Guard **SUCCESS** before merge; no intentionally induced duplicate main pushes or live provider requests.
3. After merge, verify the latest B62-relevant main push reaches `b62-test=success`. Inspect natural later burst merges for cancellation of superseded runs and actual runner-job times.
4. Rollback by reverting the single workflow/policy PR, restoring unique run IDs for main pushes. Deployment workflows are not involved.

Reference: [GitHub Actions official concurrency reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency).
