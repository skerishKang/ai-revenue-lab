# CI #3989 — Proven B62 Python test-only changes avoid unchanged 4x Worker boot
**Baseline: 2026-10-10 KST. Status: scoped proposal requiring exact-head Linux full acceptance.**

## Root cause and measured baseline

[main Linux B62 #38045341209](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38045341209) **SUCCESS**, Worker job **147s**, host Chat/Core **75s**, B14 multimodal **16s**. The four genuine independent Cloudflare Workerd/Pyodide probes took launch-to-ready: timeout **92.486s**, web transport **95.587s**, P01 service binding **94.129s**, R2 read **92.906s**, but probe HTTP response times were **0.447/0.834/0.031/0.021s**. Wrangler dependency prewarm/pywrangler sync was **25.4s**. Four live runtime process launches are the principal CI critical path on full changes; no new scheduling, fake Worker, producer mock or startup-time fix is asserted.

Recent CI optimization PRs that modified **only** Python tests (e.g. #4150, #4154) nevertheless ran four unchanged real runtimes, just to revalidate unchanged Worker source/dependencies. Full runtime checks have already been proved on multiple exact heads and main.

## Narrow, fail-closed change classification

Add `tests_only` to existing exact GitHub PR/push changed-file metadata classifier **only if**:
- **Every** changed file is directly inside `apps/padiem-chat/tests/` and its basename matches `test_*.py`.
- Every file has change status **added** or **modified** (not renamed/deleted).
- The exact PR/push commit comparison API succeeds and returns **1–100 unique nontraversing** paths.
- No Worker code, entrypoint, Wrangler config, runtime vendor dependency, shared Core, app source, static resource, product-tier declaration, B14 source, CI shell/workflow, helper/conftest, documentation or mixed path changes.

Anything uncertain/mixed (missing GITHUB_TOKEN, API failure, delete/rename, >100 changed files, compare status mismatch, invalid PR/push, duplicate, traversal, helper, nested path, runtime or CI changes) **continues full**. `chat_only` remains for app/Worker Python source (runs 4/4). `static_only` keeps existing proven safe behavior. The classifier code and workflow modified by **this PR** are themselves outside `tests/`, so exact-head and main-push acceptance naturally follow the full Worker path.

### Actual selected work by type

| Exact changed-file scope | Chat full pytest | Unchanged Core pytest | Pywrangler locked sync / vendor/lock attestation | 4 real Workerd/Pyodide probes | Worker bundle dry-run | B14 pilot + final fail-closed b62-test |
|---|---|---|---|---|---|---|
| `tests_only` (NEW) | **RUN all** | Proven source-invariant skip | **RUN all** | **SKIP unchanged runtime** | **RUN** | **RUN** |
| `static_only` (existing) | RUN all | Skip | RUN all | Existing skip | RUN | Existing B14 skip; aggregator RUN |
| `chat_only` (existing) | RUN all | Skip | RUN all | **RUN all four** | RUN | RUN |
| `full`, unknown or mixed (existing) | RUN all | RUN full | RUN all | **RUN all four** | RUN | RUN |
| B14 append-only model registration (existing) | Existing registry-only contract | Existing skip | Existing skip | Existing skip | Existing skip | **Existing stable status** |

The **Worker job itself is never skipped** in `tests_only`: exact `uv lock --check`, locked host sync and lock check, parallel locked Pyodide `pywrangler sync --force`, pinned Wrangler **4.130.0** version validation, `git diff --exit-code -- uv.lock pylock.toml`, offline Worker probe concurrency/failure-propagation contract, real vendored Core checks, and Python Worker deploy `--dry-run` remain required. B14 multimodal still runs. The stable `b62-test` aggregator still requires **B62 full regression=success + Worker/Pyodide job=success + B14 multimodal=success** (unless the preexisting unrelated `static_only` or registry-only plans apply).

**No removal or weakening of the four genuine Workerd/Pyodide runtime probe scripts**: they remain mandatory for all source/Worker/unknown/mixed/CI changes; only a formally proven source-invariant `tests_only` branch, analogous to the existing `static_only` branch, stops redundant launching.

## Acceptance evidence and limits

Local preflight on separate authorized Windows device: 11/11 exact classifier/unit workflow-source tests **PASS** for test-only, mixed/Worker/CI/product files, invalid/duplicate/deleted/renamed, 101 files, exact PR and push comparisons and original static scopes. The complete Linux CI HEAD must show the **full four true Worker probes** and final security/lock/coverage gates PASS before merge. `test_3989_b62_parallel_runtime_jobs.py` additionally exercises the host/Core selection, Worker job presence and final aggregator contract, including `tests_only` and unknown fallbacks.

Expected improvement: the unaffected `tests_only` Worker job avoids roughly **90–100s** of parallel live Workerd boot but still runs locked vendoring (~25s), bundle (~6s) and other guards. That is a **prediction only** until a future genuine `tests_only` PR/push exercises it; overall wall saving will depend on host regression and runner variability. **Do not claim an actual faster Worker boot or skip real probes on source changes.** No new runner, workflow dispatch, Secrets, production deployment or provider calls.

Roll back by deleting `TESTS_ONLY` classification plus the `tests_only` exclusion from the real probe step, restoring the original host Core scope and offline contract expectations. Keep umbrella #3989 OPEN; independent #4071 owner untouched.
