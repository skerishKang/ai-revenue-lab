# #3989 B62 Browser QA Chromium OS dependency mirror pilot

**2026-10-10, scope: ephemeral GitHub Actions runners only.**

## Reproduced Linux bottleneck

All sixteen B62 browser QA jobs run the pinned `uv run playwright install --with-deps chromium` to install Playwright 1.55.0 and **required OS libraries/fonts**. This step **must remain in place**. Browser binary is already cached. Full run [38030917850](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38030917850) (16/16 lanes PASS) had 1,263 summed runner-job seconds, compared with [38009772215](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38009772215) (15/16 PASS) 918s; the two differently scoped runs are **not an A/B experiment**.

Exact logs isolated the outlier to Debian package download, **not** pytest/Playwright test execution:

| Lane | install command elapsed | apt update/index | apt packages downloaded |
| --- | ---: | --- | --- |
| `error-retry-browser-qa` | ~169s | ~6s | 21.5MB downloaded in **158s (136kB/s)** |
| `saved-outputs-browser-qa` | ~182s | ~6s | 21.5MB downloaded in **171s (126kB/s)** |

The two hosts use `http://azure.archive.ubuntu.com/ubuntu`, and each still needs **9 missing font packages + an updated `libfreetype6`**, despite a Playwright Chromium cache hit. Hard-skipping `--with-deps` is not safe.

## Minimal pilot and guard

Use `.github/scripts/b62_playwright_apt_mirror_3989.sh` in **only these two outlier lanes**, before the **unchanged** `uv run playwright install --with-deps chromium` step. On Ubuntu 24.04 with the Azure host in `/etc/apt/apt-mirrors.txt`, replace **only** the Ubuntu archive host with `archive.ubuntu.com`. GitHub-hosted ephemeral machine only; no Production mutation. Other distro/image or missing Azure mirror => leave runner unchanged.

Ubuntu's package signature checks, all requested OS dependency packages and original pinned browser runtime remain unchanged; all sixteen job names, paths, suites, and existing artifact uploads remain. The browser path planner still selects all lanes when this workflow changes. A permanent source assertion in `.github/tests/test_b62_browser_qa_unified.py` checks **16 mandatory OS dependency installers** and **exactly 2 pilot steps**.

## Acceptance and rollback

The PR must show exact-head Linux `plan`, both pilot lanes, remaining 14 QA lanes, P01 boundary and Operations Policy Guard success. Confirm `B62_APT_MIRROR=OFFICIAL_UBUNTU_ARCHIVE` **in both pilot logs**, and capture actual apt package fetching time from both. If the canonical archive mirror does not improve the outlier or breaks package resolution, revert pilot or leave PR unmerged. Do **not** extrapolate an uncontrolled two-lane sample to 16-lane runner cost savings.

Rollback: revert two YAML pilot steps and script/test changes, leaving required Playwright dependency installation intact.

## Exact-head pilot Linux acceptance and rejected full rollout

**Accepted source shape: only two outlier lanes**, `error-retry-browser-qa` and `saved-outputs-browser-qa`. All 16 original upstream Playwright OS dependency installers remain mandatory. This document deliberately retains the failed broadening evidence so that a future CI owner will not repeat the mistake.

- Validated pilot HEAD `73af47f55d6874c2f0b0cc570095ee9bce35e696`: [Linux run 38031786884](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38031786884) **SUCCESS**, all 16 QA lanes + planner passed; companion P01 Deployment Boundary and Operations Policy Guard also SUCCESS.
- Same signed-package installation: **9 missing packages + 1 upgrade** in both pilot lanes, complete `playwright install --with-deps chromium`, 21.5 MB downloaded. From Azure prior run 38030917850 → official Ubuntu mirror pilot: `error-retry` downloaded in **158s → 2s**, total lane 195s → 58s; `saved-outputs` downloaded in **171s → 3s**, total lane 207s → 47s. Sum of all runner-job elapsed durations **1,263s → 967s**; observational comparison, not controlled A/B and not billed GitHub minutes.
- Attempted **full 16-lane mirror rollout** in HEAD `3fb9d202a6dd56f966d4cac7b9150a8c1e4430c1` and [run 38032101992](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38032101992). **REJECTED**. Fifteen browser QA lanes passed and package downloads were 0–3 seconds in multiple sampled runners, but the core `browser-qa` failed its unchanged Glass evidence `progress >= 0.68` assertion (observed 0.671). A **single failed-job-only rerun** on the same source HEAD then passed the earlier assertion but failed the unchanged Glass Shell and Glass Zoom visual QA suites. Overall workflow remained FAIL. Cause may be timing/resource contention; do not declare it a proven mirror defect or relax product test thresholds.
- Accordingly **restored the exact source/test/helper of the validated two-lane pilot**. A fresh final HEAD Linux proof is required. The failed full rollout is **not** being merged.

Rollback is removal of only two pre-install selector steps + helper and contract-test assertion. **Next work:** investigate Glass dynamic-visual timing reliability separately before considering any broad mirror rollout; retain fail-closed CI.
