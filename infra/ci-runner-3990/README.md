# CI #3990 — isolated ephemeral GitHub Actions pilot

STATE=SOURCE_READY_NOT_PROVISIONED (2026-10-10)

## Evidence and security boundary

The repo skerishKang/ai-revenue-lab is PUBLIC and belongs to an individual GitHub user. Existing self-hosted runners: 0. K_lipvoice has no OCI/GCP CLI credentials or dedicated Linux VM. No VM, registration token or production runner has been created. GitHub warns that public fork PR code can be dangerous on self-hosted runners; a personal repo also lacks an organizational workflow-restricted runner group. Therefore NEVER connect a reusable self-hosted runner or route pull_request jobs here.

An ephemeral runner is single-job only, auto-deregisters, and must be used on a fresh isolated virtual machine. This is a manual, main-only, read-only source-contract pilot. Even this pilot must NOT be activated until a new dedicated VM exists with no IAM role, secrets, service-account credential, Oracle Hermes agent or production storage.

## Files

- cloud-init-ubuntu2404-x64.yaml: dedicated no-sudo unprivileged padiem-runner user, Ubuntu packages, worker-UID metadata IP blocks; no token or SSH key embedded.
- run-once-ubuntu2404-x64.sh: validates VM identity/architecture, pinned official GitHub runner URL and SHA256, one-use unpredictable label, then --ephemeral registration; token is read from stdin and job has a 25-minute cap. VM destruction is still required after exit.
- .github/workflows/ci-3990-ephemeral-runner-benchmark.yml: workflow_dispatch only, main only, contents:read, GitHub-hosted default; optionally selects exactly one label on a disposable x64 runner; no PR triggers or deployment rights.
- .github/scripts/ci_runner_3990_benchmark.py: 3 bounded trials of 2 B62 read-only contract suites, Node JS syntax, pinned uv/B62 lock sync. It does not establish parity for heavy browser CI.

## Operator prerequisites

1. Choose a NEW Ubuntu 24.04 AMD64 VM (dedicated OCI x64 or GCP x64). OCI Ampere ARM64 cannot satisfy this x64 runner pilot. Do not co-locate with Hermes, Google credentials, active developer agents or Windows.
2. No attached cloud service account / instance role / production disks; isolated network, verified SSH access for cloud default administrator, no direct public ingress beyond strictly restricted SSH. Mount cloud-init file as user-data without adding secrets. Configure external logging if upgrading to production.
3. Verify cloud-init status --wait, OS patches, worker UID has no sudo privileges, cloud metadata IP blocked for worker, and no mounted cloud/Docker sockets. DO NOT register unless these pass.
4. From a trusted operator shell with gh, openssl, SSH and Python3, generate a fresh 128-bit label and separate runner name:
   LABEL="padiem-pilot-$(openssl rand -hex 16)"
   NAME="padiem-run-$(openssl rand -hex 16)"
   Both must be fresh for every VM.
5. Obtain the current official Linux x64 runner download URL AND sha256_checksum from:
   gh api repos/skerishKang/ai-revenue-lab/actions/runners/downloads
   Never guess the URL or checksum. This API returns a SHA256 digest; enforce it via runner script.
6. Copy the run-once script to /opt/padiem-ci/run-once.sh on the VM, root-owned mode 0755, using verified SSH host keys. Do not copy any GitHub PAT or SSH credential to the VM.
7. Dispatch exactly one benchmark on main, specifying target=ephemeral and runner_label set to LABEL:
   gh workflow run ci-3990-ephemeral-runner-benchmark.yml --repo skerishKang/ai-revenue-lab --ref main -f target=ephemeral -f runner_label="$LABEL"
8. On the TRUSTED OPERATOR MACHINE ONLY retrieve the short-lived registration token using:
   gh api -X POST repos/skerishKang/ai-revenue-lab/actions/runners/registration-token --jq .token
   Never print/store it, and never embed it in user-data or GitHub Actions secrets. Pipe token via trusted SSH stdin to a sudo -u padiem-runner invocation with environment variables:
   RUNNER_REPO_URL=https://github.com/skerishKang/ai-revenue-lab
   RUNNER_TARBALL_URL=(from downloads API)
   RUNNER_TARBALL_SHA256=(from downloads API)
   RUNNER_LABEL=(the one-time label)
   RUNNER_NAME=(the one-time name)
   bash /opt/padiem-ci/run-once.sh
   Token is read on stdin before config.sh. The registration utility may briefly hold it in process args; only root and runner must have process-inspection access.
9. Check the exact Actions job conclusion and artifact. Immediately destroy VM AND boot disk after one job, revoke stale/offline runner registrations, cancel orphaned runs, and preserve diagnostic runner logs outside the VM. Deleting a workspace alone is NOT secure cleanup. Do not retry on same VM.

Hosted comparator (available without a VM):
   gh workflow run ci-3990-ephemeral-runner-benchmark.yml --repo skerishKang/ai-revenue-lab --ref main -f target=github-hosted

Gather at least 3 hosted and 3 independently provisioned/destroyed ephemeral runs; compare queue wait, setup, three scoped test trials per run, errors and VM cost. This scoped non-secret smoke benchmark cannot substitute for complete B62 Chromium browser QA parity.

## Safety, release and rollback

Workflow is main-only manual dispatch. Permissions only contents:read; checkout persist-credentials:false. Runner label is an unpredictable 128-bit value. Original PR-required jobs, workflow names, B62/B14/Engine, #3523 Golden Path, migrations and production deployments remain unchanged. No blanket runs-on switch. The hosted option is the fallback. Public PR workloads must NOT be routed to this runner; risk of arbitrary PR code remains without organizational workflow restrictions. This is not approved as a production or general-purpose CI runner.

Blockers to actual activation: separate dedicated x64 cloud VM, verified isolation/budget/provider admin, off-instance logging, operator with repository registration permissions and explicit decision to accept public-repository one-job pilot risks. The current connected computer cannot supply these prerequisites.