# #3989 — B62 UI Node harness per-module singleflight (2026-10-10 KST)

## Profiling evidence and bounded scope

The existing [#4071 Linux pytest duration profile](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38005362137), available as already-run evidence (no new profiler dispatch), flagged **repeatedly executed real Node VM behavioral harnesses**, with per-call approximate old times:

| B62 pytest module | Behavioral consumers, before -> after | Old per-call profile | Approx. avoidable calls |
| --- | ---: | ---: | ---: |
| `test_b54_claw_run_history_ui.py` | 3 -> 1 | 0.59s | 2 |
| `test_claw_session_reopen_ui.py` | 5 -> 1 | 0.38s | 4 |
| `test_b62_2342_project_file_binary_ui.py` | 2 -> 1 | 0.72s | 1 |
| `test_b62_2340_approved_memory_ui.py` | 3 -> 1 | 0.38s | 2 |

These are *historical* observations on a prior commit and runner; the aggregate ~4.2s is an **upper-bound estimate**, not a measured saving on today's main. The earlier B54 retry test was already optimized and is **not touched**. `test_3382_claw_general_answer_dom.py` is **not cached**, since it intentionally runs distinct server-derived SSE payloads through separate Node scenarios; those cannot be merged safely.

## Change

In **only four existing B62 Python test files**, decorate the zero-argument `_run_harness()` with `functools.lru_cache(maxsize=1)`. Each now executes the exact same real `static/app.js` and related JavaScript harness **once per Python module process**, then all original named pytest tests continue to assert the same full immutable read-only `checks` and `requests` result. The test functions do not mutate these shared values. Direct `python test_*.py` `__main__` entrypoints retain all checks, but avoid rerunning the same fixture repeatedly. Cache does not cross pytest processes or commits; every new CI runner executes its own current app.js. Node failures/nonzero exits propagate to every consumer (failed calls are never cached).

No product UI, production app source, worker runtime, HTTP security/authorization, Python password-KDF, provider, lockfile, workflow, CI job runner count, required status names, original test function, original subprocess assertions, or published coverage boundary changes.

## Acceptance

- Offline `python -m compileall` or equivalent syntax checks on the four modified tests; preserve original source-level subtest/behavioral assertions.
- Exact PR head Linux **all original B62 Chat tests**, Core whenever scope requires, all 4 **real** Workerd/Pyodide probes and bundle dry-run, B14 selected suite, Operations Policy/Browser QA/GitGuardian/final `b62-test` SUCCESS. No `skip`, `xfail`, monkeypatched app, missing checks, or cached result across distinct files.
- Record `B62 full regression` and exact Chat test count/runtime against nearby unmodified main (runner jitter matters); expected benefits accrue to Chat pytest **runner time**, not necessarily end-to-end critical path while Worker boot remains the longest job. If no code/test safety, revert all four decorators and imports without relaxing tests.
- Do **not** reopen or mutate independently owned [#4071](https://github.com/skerishKang/ai-revenue-lab/pull/4071). Umbrella #3989 remains OPEN.

No Production deployment, Secrets change, new billable runner, premium model calls or manual workflow dispatch.
