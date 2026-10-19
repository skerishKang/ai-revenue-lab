# #4070 — B62 host regression: independent Chat and Core pytest overlap, same runner

**2026-10-10 KST; PR linked to #4070 and umbrella #3989.** This is CI-only and does not modify password hashing, security assertions, test selection, production resources or paid providers.

## Current measurements and exclusions

[Successful merged main B62 CI #38037564786](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38037564786) executed **3,657 passing Chat tests in 104.73s**, then **1,984 passing Core tests in 40.36s**, in the existing `B62 full regression` job of **166s**; parallel Worker/Pyodide job **129s**, original mandatory `b62-test` PASS. Sequential pytest alone costs ~145s excluding environment setup.

The independent [#4071 duration profiling PR](https://github.com/skerishKang/ai-revenue-lab/pull/4071) (still open) recorded top slow cases on older Linux sources: three ~19s duplicated Claw retry Node harness calls and expensive password security cases. The Claw harness was **already** optimized in merged [#4083](https://github.com/skerishKang/ai-revenue-lab/pull/4083) to run once via a module fixture; this PR does not repeat its work, does not edit `pyproject.toml`, and does **not** reduce password hash work factors.

## Implementation, exact boundary

On **the existing B62 full regression GitHub Linux runner** only, replace two sequential pytest steps with one `.github/scripts/b62_host_pytest_overlap_4070.sh` call. It executes the **identical, full, existing commands**:

- `cd apps/padiem-chat && uv run --locked python -m pytest -q`
- `cd packages/padiem-ai-core && uv run --extra dev python -m pytest -q`

Each in its **own subprocess, own project working directory and own Python virtualenv**; neither pytest suite is split or filtered and all original warnings, test totals, assertion failures and exit codes are reported. Both processes start without waiting for the other's test suite to end, and **both must complete successfully**. If either fails, the host regression step and final `b62-test` fail. A temporary external-to-repo log directory is removed on completion or failure.

The existing fail-closed `registry-ci-plan` determines the exact original Core skip policy: `chat_only` or `static_only` omits Core; `full`, unknown, unset or any unrecognized scope runs **both**. Chat pytest is *always* executed, including `static_only`. The runtime Worker four-probe job, locked dependency checks, Python bytecode compilation, JS syntax, B14 multimodal checks and stable `b62-test` aggregation remain unchanged. This creates **no new runner and no new required check names**.

Extend both existing source-contract suites to trace pytest commands through the helper, and add an **offline fake uv** integration test proving two independently started subprocesses, correct scoped skips, fallback-to-full and fail-closed fan-in when either command fails. No external browser, npm, cloud, token, db or provider involved in this offline check.

## Acceptance and performance accounting

Require exact-head Linux B62 full regression with all Chat and Core case counts unchanged, real four Workerd/Pyodide probes and `b62-test` PASS, plus Operations Policy Guard and P01 when selected. On the same SHA rerun *only the expensive B62 full regression job* to test repeatability if the first passes. Compare the whole workflow wall time with the 184s [PR #? earlier] and 166s current full job, distinguishing job elapsed from runner billing.

**Cost risk:** running two Python suites simultaneously on a two-core GitHub-hosted runner may produce CPU, memory or cache contention (especially password KDF tests) and could fail timing-sensitive cases. If this trial is slower, unstable, or fails, revert it and retain the original sequential steps. Do not reduce test count, KDF parameters or gate checks to obtain a superficial PASS.

Original suite order: Chat then Core. Rollback: restore the two original steps in the existing B62 workflow and remove the new wrapper, without changing any product or Production configuration.
