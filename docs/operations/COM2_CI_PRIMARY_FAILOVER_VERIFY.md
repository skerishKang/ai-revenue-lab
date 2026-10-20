# COM2 and GitHub-hosted CI: current division of labour

Verified against this repository on 2026-10-21 (`gh api` on the live ruleset, the workflow
files in `main`, and the recorded runs cited below). This is the operating structure; the
superseded COM2-primary pilot is kept as a dated record at the bottom of this file.

## Required gate

- The only required status check on `main` is the ruleset `PADIEM COM2 policy gate`
  (id `25431914`, enforcement `active`), whose `required_status_checks` list contains exactly
  one context: `COM2 full policy`. `strict_required_status_checks_policy` is `false`.
  Legacy branch protection returns `Branch not protected` (404), so no second authority
  configures the same gate.
- The context name is historical. `COM2 full policy` is posted by
  `.github/workflows/com2-pr-auto-sandbox.yml`, and that job runs on the GitHub-hosted
  `ubuntu-24.04` runner: an offline container build (`--pull=never --network=none --read-only`)
  executes the full policy suite and the job publishes the pending/success/failure status on the
  exact open same-repository PR head SHA.
- Trigger chain on every PR: `com2-pr-policy-trigger.yml` (`pull_request`, hosted, no checkout,
  emits a trusted PR event) → `workflow_run` → `com2-pr-auto-sandbox.yml`. The sandbox `if:`
  requires the trigger run to have completed successfully, `event == 'pull_request'`, a
  same-repository `head_repository`, and a resolvable PR number. Fork PRs never reach it and
  keep hosted validation only.
- General browser QA is GitHub-hosted: `b62-browser-qa-unified.yml` and the per-surface
  `*-browser-qa` checks run per push/PR and are the default path.

## COM2 runners

- Two self-hosted runners carry the `padiem-com2-ci` label (`COM2-PADIEM-CI`,
  `COM2-PADIEM-CI-2`). They are retained for **selective** special QA only.
- All 17 `com2-b62-*` canaries are `workflow_dispatch`-only and take an exact 40-lowercase-hex
  `sha` (or `pr_number`) input. None has a `pull_request`, `push`, `schedule` or `workflow_run`
  trigger, so a push does not fan out COM2 work.
- A canary resolves its workflow file from the default branch but checks out the supplied PR
  head, so head-side **script** edits are tested while head-side **workflow** edits take effect
  only after merge. Each canary is non-required: it publishes its own `statuses` context and
  cannot block a merge.
- Each canary executes through a root-owned host command (for example
  `/usr/local/sbin/padiem-ci-b62-generic-browser-check`), never through PR-controlled shell on
  the host. Those commands, their ordered script lists and the runner installation are host
  configuration and are out of scope for repository changes.

## Failover

- `com2-policy-hosted-failover-watch.yml` and `com2-mobile-hosted-failover-watch.yml` run from
  the trusted default branch (`schedule` plus `workflow_dispatch`, no PR-controlled code) and
  trigger an exact-SHA hosted backup when a policy status is stale.
- `operations-policy-guard-hosted-backup.yml` is the on-demand hosted policy backup
  (`workflow_dispatch`). `operations-policy-guard.yml` still runs on `pull_request`.

## Dated record: the COM2-primary pilot (superseded, retained as history)

The text below is the design that was under verification before #5338 closed it. It is kept
verbatim as the record of that stage; it is not the current structure.

- GitHub remains the repository, PR review, Actions orchestration, and check record authority.
- The trusted default-branch COM2 workflow consumes a completed lightweight PR event and verifies
  the still-open exact same-repository PR HEAD before a bounded offline Docker policy test.
- The root-owned COM2 command is `/usr/local/sbin/padiem-ci-full-policy-check`, not PR-controlled
  scripts on the host.
- The existing hosted Operations Policy Guard remains active pending validated primary check
  attribution and failover. `operations-policy-guard-hosted-backup.yml` can run the complete
  hosted policy suite on demand.
- Fork PRs are not executed by the COM2 workflow; they retain hosted validation.
- Do not remove the hosted required check until COM2 status attribution and fallback recovery are
  demonstrated against the PR's exact SHA.

Transition evidence, measured at the time and recorded in issue #5338 (see its closing comment
`…issuecomment-6300737309`; those figures are the 2026-10-20 measurement, not a current one):

- The required policy run moved from COM2 to GitHub-hosted: of 130 `COM2 PR Auto Sandbox` runs
  after the switch, 122 ran hosted and 8 on COM2; last COM2 execution `39420735190` at
  2026-10-20T12:14:18Z, first hosted `39420970367` at 2026-10-20T12:16:08Z.
- Automatic COM2 browser-canary fan-out dropped to zero: 3 days before the switch, 226 PR policy
  triggers produced 1,165 canary runs (5.2 per PR); after it, 122 triggers produced 6 canary runs,
  all manual `workflow_dispatch`.
- Same-workflow durations: median 165s → 50s, p90 912s → 59s, max 2,456s → 104s, cancelled
  45 → 1.
- The residual that this file's reconciliation closes is tracked in #5210: the Generic Browser
  visual tail on COM2 and the two stale documents (`COM2_CI_PRIMARY_FAILOVER_VERIFY.md`,
  `COM2_CI_COMMIT_STATUS_E2E.md`).
