# GitHub Actions: CI queue and cache improvement

Date: 2026-10-10. Repository: skerishKang/ai-revenue-lab.

## Verified cause

A single B62 Chat PR generated 22 independent workflow runs at the same timestamp. It was NOT 22 pull requests. Several jobs obtained GitHub-hosted runners in seconds. Many browser QA workflows repeat Python/uv/Playwright/Chromium setup.

The latest main already contains PR-scoped concurrency and improved path filters in B62 browser QA. This patch preserves all such changes.

## Stage 1: Warm dependencies, preserve gates

Sixteen B62 browser QA workflows using pinned Playwright 1.55.0 now:
- enable setup-uv cache based on apps/padiem-chat/uv.lock;
- share downloaded Chromium browsers via actions/cache keyed by operating system, architecture and pinned Playwright version;
- continue to run Playwright install --with-deps Chromium after the cache restore (handles misses and OS packages);
- retain all workflow names, job names, runners, paths, tests, and concurrency semantics.

No secrets, auth files, deployments or runtime user data are cached. Caching improves setup time when warmed, NOT the number of independent runs. Measure cache hits, queue wait and step runtimes on actual GitHub Actions before claiming speedup.

## Stage 2: Workflow fanout (separate guarded change)

Before consolidating workflow runs: capture all required contexts, rulesets, production merge automation, protected gates, and path-dependency owners. A permanent pending required check is unacceptable. An always-reporting aggregator may replace related jobs only with explicit verified equivalence of all tests. Keep shared Core/identity fanout where required.

DO NOT auto-cancel or parallelize production deploys, database migrations, identity authority gates, remote probes or manually dispatched deployment sequences. Retain #3523 production golden path.

## Stage 3: Self-hosted Linux runner rollout

Benchmark an isolated disposable Linux runner for trusted, non-secret test lanes. Do NOT use a personal Windows PC containing developer credentials and active agents as the runner for arbitrary pull-request code. Keep untrusted/fork PR jobs GitHub-hosted until an ephemeral VM isolation policy is proven. Runner group/labels must restrict eligible repos/jobs; use least privilege, dedicated workspace, ephemeral runners and rollback to GitHub-hosted Ubuntu.

Self-hosted is not automatically faster: compare full PR elapsed time, cache hit rate, queued time and per-test duration, not just runner availability.

## Validation

Run python -m unittest discover -s .github/tests -p test_b62_browser_ci_cache_contract.py -v, parse all changed YAML, and compare parent-versus-head normalized workflow documents to ensure only cache settings and cache steps changed.
## Stage 1b: publish a cross-PR browser cache on default branch

GitHub caches first written by pull_request runs are scoped to that PR merge ref and should not be assumed reusable by unrelated PRs. After this PR merges into default main, invoke the dispatch-only b62-browser-cache-seed.yml workflow exactly once with ref main. It publishes the same pinned Chromium key as 16 PR browser consumers. Future PRs can restore a cache from the default branch. This publisher has no secrets, no production API, no push/pull_request triggers, and must run only on main. A cold cache is still supported by install --with-deps in each browser QA.

Verify the seed run succeeds and follow-up PR job logs show a cache hit before claiming cross-PR cache reuse. If the cache key changes, rerun the seed after its updated workflow is merged to main. Avoid re-running the seed on every PR.
## Stage 2 (#3989): consolidate independent B62 browser QA runs

Previously 16 browser QA workflow files each triggered independently on matching pull_request paths. A B62 UI change could create all 16 workflow runs, cluttering PR checks.

- The new b62-browser-qa-unified.yml is the single B62 browser QA PR workflow. It always reports a plan job and 16 stable browser QA job identifiers (original check names). Relevant jobs run; unrelated jobs skip successfully.
- The 16 original browser QA workflows retain workflow_dispatch only, permitting independent manual diagnostics. No job commands, environment, QA scripts, evidence uploads, Chromium caches, or timeouts were changed.
- b62_browser_qa_paths.json retains the exact original per-job positive/negative PR path patterns.
- A lightweight read-only plan job retrieves changed file paths from GitHub pull-request files API with pull-requests: read. Renames include old/new names. Pattern matching is conservative (overselection permitted, silent omission avoided).
- Missing API token, error, unexpected event, oversized PR (3000 files), or policy-file changes fail open to all 16 jobs, avoiding an accidental false-success skip.
- The unified pull_request trigger is unconditional, so the plan always reports and 16 job contexts materialize even for non-B62 PRs. Unrelated PRs execute one lightweight classifier and skip browser tests. This avoids permanently pending required checks.
- Concurrency is per PR with cancellation of superseded ordinary CI. Existing individual manual workflows keep their own concurrency. Protected deploy, identity, production, #3523 and migration gates are untouched.

### Validation and rollback

The improvement reduces independent workflow runs but does not reduce the number of browser test jobs for a typical UI change. The PR integration must establish:
1. One unified B62 browser QA run and zero old browser PR runs on the same SHA.
2. All 16 check contexts appear with PASSED or SKIPPED results. Executed QA jobs still upload evidence.
3. UI, touch-only CSS, Core-only, docs-only, worker-only and QA-script-only changes classify correctly; API failures run all jobs.
4. No indefinite Pending or missing required contexts.
5. Rollback is to revert this single PR in full: restore 16 old PR triggers and remove unified YAML, ownership manifest and classifier in one step.

The separate self-hosted GitHub Actions runner issue #3990 is not activated.