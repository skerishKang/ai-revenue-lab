# GitHub Report Handoff Policy

- Status: **CANONICAL PADIEM / CLAW REPORTING POLICY**
- Report repository: `skerishKang/workdiary` (private)
- Report root: `padiem-reports/`

## 1. Purpose

Local CLAW workers and CENTRAL coordinate through GitHub rather than by copying long reports through chat.

The related `ai-revenue-lab` Issue/PR is the coordination surface. The private `skerishKang/workdiary` repository is the long-form report/evidence surface.

## 2. Reporting modes

Reporting depth follows task risk and review need. **A long report is not the default for every tiny fix.**

### COMPACT mode — default for bounded fixes

Use `COMPACT` when all are true:

- root cause/scope is already bounded;
- changed files are small and reviewable directly in the PR;
- no migration, destructive action, billing, secret mutation, auth/authz redesign, or broad shared-authority change;
- focused tests/CI provide the needed evidence;
- CENTRAL did not explicitly request a long report.

The Issue/PR comment itself is the report:

```text
REPORT_MODE=COMPACT
BASE_SHA=
HEAD_SHA=
FILES_CHANGED=
IMPLEMENTATION_RESULT=
FOCUSED_TESTS=
RELEVANT_CI=
LIMITATIONS=
PRODUCTION_MUTATION=0|AUTHORIZED
```

No separate `workdiary` commit is required in COMPACT mode.

### LONG mode — only when materially useful

Use the private `skerishKang/workdiary` report when at least one applies:

- complex multi-surface or multi-authority change;
- large evidence set that would clutter the PR;
- independent local/browser/hardware validation with artifacts;
- migration/destructive/billing/high-risk auth or secret-boundary work;
- incident/root-cause investigation requiring durable detailed evidence;
- CENTRAL explicitly requests `REPORT_MODE=LONG`.

Then use:

```text
REPORT_REPO=skerishKang/workdiary
REPORT_PATH=padiem-reports/YYYY-MM-DD/<CLAW>/<task>.md
REPORT_COMMIT=<immutable workdiary commit SHA>
```

The Product Owner does not need to relay either report mode through chat. CENTRAL fresh-reads GitHub directly.

## 3. Compact Issue/PR comment

In `COMPACT` mode, the Issue/PR comment contains the complete bounded report and no private-report pointer is required.

In `LONG` mode, the Issue/PR comment contains only a short result summary, key exact-head/status fields, and the three private-report pointers. It must not contain the complete narrative report or large raw logs.

Example:

```text
CLAW2 #2827 correction complete.
HEAD=<exact head SHA>
DEV_FAST_GATE=PASS
DEV_ACTOR_RELEASED=YES
FULL_VALIDATION=PENDING
READY=NO
MERGE=NO

REPORT_REPO=skerishKang/workdiary
REPORT_PATH=padiem-reports/2026-09-25/CLAW2/2827-pdf-preview-correction.md
REPORT_COMMIT=<immutable workdiary commit SHA>
```

## 4. Long-report requirements

Only `REPORT_MODE=LONG` uses this section. The private long report should contain enough evidence for CENTRAL to independently review the claim, including when applicable:

```text
LOCAL=
ISSUE=
PR=
TASK=
BASE_SHA=
HEAD_SHA=
CURRENT_MAIN=
BRANCH=
FILES_CHANGED=
SCOPE=
IMPLEMENTATION_RESULT=
TESTS=
DEV_FAST_GATE=
DEV_ACTOR_RELEASED=
VALIDATOR_WINDOWS=
VALIDATOR_UBUNTU=
VALIDATOR_BROWSER=
FULL_VALIDATION=
CI=
LIMITATIONS=
SECURITY/SECRET_EXPOSURE=
PRODUCTION_MUTATION=
READY=
MERGE=
ISSUE_CLOSE=
```

A worker report does not need to wait for full Windows/Ubuntu/browser validation after `DEV_FAST_GATE=PASS`. Validator actors append or link their own exact-head records asynchronously, and `FULL_VALIDATION` is evaluated at merge review.

Report claims remain subordinate to current GitHub truth. CENTRAL still independently checks current main, Issue/PR state, exact head, changed files, CI, predecessors, overlap, and any required live evidence before consequential action.

## 5. Large evidence

Prefer GitHub Actions artifacts for:

- screenshots;
- Playwright traces;
- archives;
- large logs;
- browser/runtime evidence that is too large for a Markdown report.

The private report should reference the relevant workflow/run/artifact rather than embedding large payloads.

## 6. Google Drive / rclone

Google Drive and rclone are not part of the Padiem/CLAW reporting workflow.

```text
GOOGLE_DRIVE_REPORTING=DISABLED
RCLONE_REPORTING=DISABLED
DRIVE_QUOTA_RETRY=0
DRIVE_DELETE_OR_TRASH_CLEANUP=0
```

Do not retry `storageQuotaExceeded`, delete Drive files, empty trash, or perform quota cleanup as a reporting side task.

## 7. Secret and credential safety

Never write any secret value to:

- the private report;
- the public Issue/PR;
- GitHub Actions artifacts;
- CI logs;
- screenshots.

This includes passwords, API keys, access/refresh tokens, cookies, session values, private keys, database credentials/URLs, secret values, and raw credential bindings.

Secret binding names or presence-only readiness may be recorded only when the work order permits it and no value can be reconstructed from the evidence.

## 8. Failure to write the private report

This section applies only when `REPORT_MODE=LONG` was actually required. Failure to write a private long report must not manufacture a reporting blocker for a task that qualifies for `COMPACT` mode.

If a required LONG-mode worker cannot write to `skerishKang/workdiary`, it must not fall back to posting the entire report publicly and must not fall back to Google Drive/rclone.

Instead, preserve the report locally and post only:

```text
REPORT_WRITE=BLOCKED
REPORT_REPO=skerishKang/workdiary
REPORT_PATH=<intended path>
REPORT_COMMIT=UNAVAILABLE
LOCAL_REPORT_PRESERVED=YES
```

Then stop at the reporting gate and let CENTRAL resolve repository access.

## 9. Canonical report-repository instructions

The report repository contains its own worker-facing instructions at:

```text
skerishKang/workdiary
padiem-reports/README.md
```

Workers must follow both this policy and the report-repository instructions.