# COM2 CI primary and hosted fallback verification

- GitHub remains the repository, PR review, Actions orchestration, and check record authority.
- The trusted default-branch COM2 workflow consumes a completed lightweight PR event and verifies the still-open exact same-repository PR HEAD before a bounded offline Docker policy test.
- The root-owned COM2 command is `/usr/local/sbin/padiem-ci-full-policy-check`, not PR-controlled scripts on the host.
- The existing hosted Operations Policy Guard remains active pending validated primary check attribution and failover. `operations-policy-guard-hosted-backup.yml` can run the complete hosted policy suite on demand.
- Fork PRs are not executed by the COM2 workflow; they retain hosted validation.
- Do not remove the hosted required check until COM2 status attribution and fallback recovery are demonstrated against the PR's exact SHA.
