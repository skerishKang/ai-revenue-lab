# #3989 B62 Browser QA Chromium OS dependency mirror: measured pilot and rollout

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


## Pilot result and full 16-lane rollout decision

PR #4098 pilot HEAD `73af47f55d6874c2f0b0cc570095ee9bce35e696`: [Actions run 38031786884](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38031786884) **SUCCESS**, all 16 browser lanes + plan success, P01 and Operations Policy Guard success.

The pilot actually switched both Azure hosts to canonical `archive.ubuntu.com` (marker `B62_APT_MIRROR=OFFICIAL_UBUNTU_ARCHIVE`). Full upstream `playwright install --with-deps chromium` ran unchanged and installed exactly **9 previously missing packages + 1 upgraded** in each. Real Linux apt 21.5 MB download timings:

- `error-retry-browser-qa`: **158s (Azure) → 2s (Ubuntu archive)**, job **195s → 58s**.
- `saved-outputs-browser-qa`: **171s (Azure) → 3s (Ubuntu archive)**, job **207s → 47s**.
- Full 16-lane job elapsed sum: **1,263s → 967s**; cannot attribute all to mirror alone because hosted runner conditions vary. Wall time and billed runner minutes are distinct metrics.

Based on both pilot checks PASS + real package-count parity, the **same single already tested mirror selector** is used by all 16 browser QA lanes. It changes only the ephemeral runner Ubuntu host when on Ubuntu 24.04; the **16 original mandatory Playwright `--with-deps` installations are retained**. Source contract tests prove 16/16 selectors and 16/16 upstream installers. Follow-up exact-head full 16-lane Linux CI is REQUIRED before merge; if it fails, rollback the broadening or PR. No test target or owner status has been removed.
