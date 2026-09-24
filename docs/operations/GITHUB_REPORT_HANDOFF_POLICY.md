# GitHub Report Handoff Policy

- Status: **CANONICAL PADIEM / CLAW REPORTING POLICY**
- Report repository: `skerishKang/workdiary` (private)
- Report root: `padiem-reports/`

## 1. Purpose

Local CLAW workers and CENTRAL coordinate through GitHub rather than by copying long reports through chat.

The related `ai-revenue-lab` Issue/PR is the coordination surface. The private `skerishKang/workdiary` repository is the long-form report/evidence surface.

## 2. Required reporting flow

At the end of a CLAW task:

1. Write the complete report to the private report repository:

```text
REPORT_REPO=skerishKang/workdiary
REPORT_PATH=padiem-reports/YYYY-MM-DD/<CLAW>/<task>.md
```

2. Commit the exact report revision and record the immutable commit SHA.

3. Post only a compact final result to the related `ai-revenue-lab` Issue or PR. Do not paste the long report into the public Issue/PR.

4. The compact comment must include:

```text
REPORT_REPO=skerishKang/workdiary
REPORT_PATH=padiem-reports/YYYY-MM-DD/<CLAW>/<task>.md
REPORT_COMMIT=<workdiary commit SHA containing the exact report>
```

5. CENTRAL fresh-reads the relevant `ai-revenue-lab` state and reads the full report directly from the private report repository.

The Product Owner does not need to copy/paste the full report into ChatGPT.

## 3. Compact Issue/PR comment

The Issue/PR comment may contain a short result summary, key exact-head/status fields, and the three report pointers. It must not contain the complete narrative report or large raw logs.

Example:

```text
CLAW2 #2827 correction complete.
HEAD=<exact head SHA>
Focused/full tests PASS; exact-head CI PASS.
READY=NO
MERGE=NO

REPORT_REPO=skerishKang/workdiary
REPORT_PATH=padiem-reports/2026-09-25/CLAW2/2827-pdf-preview-correction.md
REPORT_COMMIT=<immutable workdiary commit SHA>
```

## 4. Long-report requirements

The private long report should contain enough evidence for CENTRAL to independently review the claim, including when applicable:

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
CI=
LIMITATIONS=
SECURITY/SECRET_EXPOSURE=
PRODUCTION_MUTATION=
READY=
MERGE=
ISSUE_CLOSE=
```

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

If the worker cannot write to `skerishKang/workdiary`, it must not fall back to posting the entire report publicly and must not fall back to Google Drive/rclone.

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