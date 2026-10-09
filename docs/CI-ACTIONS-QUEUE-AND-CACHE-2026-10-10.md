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