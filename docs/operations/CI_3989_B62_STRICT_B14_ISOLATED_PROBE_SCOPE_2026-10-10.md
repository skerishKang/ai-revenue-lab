# #3989 — B62 Worker live probes skipped only for source-isolated B14 application/test edits
**2026-10-10 KST — narrow fail-closed CI classification, no production change**

## Baseline and scope

B62 CI runs four separate **real** Python Worker/Pyodide Workerd processes (HTTP timeout, real HTTPX transport, P01 service binding composition, R2 ObjectBody). Their startup is roughly **92–96s apiece** even with four probes parallelized, while HTTP assertions typically finish in <1s. Full unmodified [main CI #38047796962](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38047796962): Worker job **165s**; most recent proven test-only [main CI #38048457013](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38048457013): Worker locked vendor/bundle **51s**, host Chat **104s**. Never report the latter as a true Workerd startup speedup. This feature targets a change category that cannot alter the four B62 Worker binaries/dependencies.

The existing B62 workflow triggers on changes under `apps/korean-ai-platform/**` for cross-service compatibility. However B62 Worker entrypoints/config `apps/padiem-chat/worker_runtime_{timeout,web_transport,p01_binding,r2_read}_probe.py`, source `apps/padiem-chat/app/**`, Core `packages/padiem-ai-core/**`, pinned Wrangler `4.130.0`, locks and Worker vendored runtime live in **different files** than the independent B14 application `apps/korean-ai-platform/app/**` and its direct `tests/test_*.py` tests. The four Worker probes exercise the **B62 Workerd runtime**, not an external live B14 service. Changes confined to source-isolated B14 code cannot change the deployed B62 Python Worker bytes, even when B14 public contract behavior changes.

## Exact changed-file source invariance

A new `b14_only` classification is selected **only** when exact GitHub PR or main-push compare succeeded, returned 1–100 unique changed files all with status **added** or **modified**, and **every** path matches one of:

- `apps/korean-ai-platform/app/**/<basename>.py` or `...json`, with simple basename/directory grammar and no parent traversal; or
- Direct `apps/korean-ai-platform/tests/test_<basename>.py` (no nested test folders, helpers or conftest).

Any B62 file, shared Core, CI workflow/script, P01 contract, B14 `pyproject.toml`/requirements/lock, B14 infrastructure script or other file mixed into the diff reverts to **`full`** (except preexisting B62-only special cases). Rename/removal, duplicate path, traversal, unsupported file extension, >100 files, invalid event, missing GitHub compare API results, no token, main/PR ambiguity and explicit workflow dispatch **all fall back to full**. This conservative source boundary is intentional.

## Coverage selection (unchanged status and security)

| Area | `b14_only` branch |
|---|---|
| B62 Chat pytest | **All test cases still run**: real B14 integration/contract cases remain |
| Shared Core pytest | Omitted only because `packages/padiem-ai-core/**` cannot have changed |
| B14 pilot pytest | **Run unchanged**, `tests/test_multimodal.py` and `tests/test_pilot.py` |
| Pinned Wrangler + pywrangler locked sync | **Run unchanged** |
| Host/vendor dependency/version and locks | **Run unchanged**, strict locked and no changed committed lockfiles |
| Four real local Workerd/Pyodide runtime probe processes | **Skipped only for exact `b14_only`**, because all four B62 probe sources/binaries and runtime deps are invariant |
| Actual Python Worker bundle dry-run | **Run unchanged** |
| GitGuardian / Operating Policy / Browser impact planner | **Run unchanged** as selected by existing workflows |
| Final required `b62-test` | **Requires success** from B62 Chat full regression, B62 Worker bundle job, B14 multimodal and fail-closed classifier; no job or status renamed |

The **existing** full runtime behavior for B62 source/Worker, mixed/unknown, vendored dependencies, Worker-entrypoint scripts and CI changes stays four true probes; they are not replaced by synthetic mocks or marked as PASS if skipped.

Prior `static_only` and `tests_only` scope behavior is unchanged, likewise B14 append-only registration-only mode. This PR alters `.github/scripts/**`, `.github/tests/**`, and `.github/workflows/**` paths; **it must be classified `full` on its own exact-head CI and main push** and MUST run all four genuine Workerd probes before merge. The expected benefit for future actual strict B14-only source/test PRs/pushes is approximately the difference between full Worker startup (~150–190s observed, variable) and Worker locked vendor/bundle (~40–55s observed). This is an **estimate**, not yet a measured B14-only run; total CI wall depends on Chat full regression and runner start variability.

## Local preflight and exact-head acceptance

Connected Windows environment pulled exact branch files from GitHub. Updated fail-closed classifier **14/14 Python unittest PASS**, including exact PR and push comparisons, B14 isolated source/test, mixed B62/Core/vendor/CI/deps/unknown, rename/delete/traversal/duplicate, and prior `tests_only`/`static_only` cases. All modified Python sources passed AST syntax checks. Existing Linux `test_3989_b62_parallel_runtime_jobs.py` must also pass its real bash/mock-uv propagation/selection canaries for new `b14_only` Core skip and unchanged required aggregator.

The PR-head Linux run must show `B62_CI_IMPACT_SCOPE=full`, **all** 4 genuine Workerd probes PASS, Worker bundle/vendor/locks PASS, all Chat and Core tests PASS, B14 PASS, Operations Policy/Browser QA impact planning/GitGuardian and stable final `b62-test` PASS. **Never merge on local tests alone.**

Rollback: remove `B14_ONLY` classifier branch, revert host scope arm and workflow probe-step exclusion, plus matching scope contract tests. Do not deploy production, mutate secrets or call paid models. Leave umbrella issue #3989 open to measure genuine B14-only savings on a future natural change, not by synthetic dispatch.
