#!/usr/bin/env bash
# Run on a disposable Ubuntu 24.04 AMD64 VM as user padiem-runner only.
# Registration token is read from stdin, never embedded in image or user-data.
set -euo pipefail
set +x
umask 077
fail() { printf 'RUNNER_PILOT_ABORT=%s\n' "$*" >&2; exit 2; }
[[ "$(id -un)" == "padiem-runner" ]] || fail "dedicated_user_required"
[[ "$(uname -m)" == "x86_64" ]] || fail "x64_required"
[[ "$(source /etc/os-release; printf '%s' "$VERSION_ID")" == "24.04" ]] || fail "ubuntu_24_04_required"
[[ "$(source /etc/os-release; printf '%s' "$ID")" == "ubuntu" ]] || fail "ubuntu_required"
[[ "${RUNNER_REPO_URL:-}" == "https://github.com/skerishKang/ai-revenue-lab" ]] || fail "repo_not_allowlisted"
[[ "${RUNNER_LABEL:-}" =~ ^padiem-pilot-[0-9a-f]{32}$ ]] || fail "invalid_one_use_label"
[[ "${RUNNER_NAME:-}" =~ ^padiem-run-[0-9a-f]{32}$ ]] || fail "invalid_one_use_name"
[[ "${RUNNER_TARBALL_SHA256:-}" =~ ^[a-f0-9]{64}$ ]] || fail "invalid_sha256"
[[ "${RUNNER_TARBALL_URL:-}" =~ ^https://github.com/actions/runner/releases/download/v2[0-9.]+/actions-runner-linux-x64-2[0-9.]+\.tar\.gz$ ]] || fail "untrusted_download_origin"
command -v timeout >/dev/null || fail "timeout_missing"
command -v sha256sum >/dev/null || fail "sha256sum_missing"
base="/home/padiem-runner/padiem-gha"
[[ -d "$base" && ! -e "$base/.runner" ]] || fail "runner_state_detected"
[[ -z "$(find "$base" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "existing_runner_contents"
[[ ! -d "/home/padiem-runner/.ssh" ]] || fail "worker_ssh_credentials_detected"
[[ ! -d "/home/padiem-runner/.aws" && ! -d "/home/padiem-runner/.config/gcloud" && ! -d "/home/padiem-runner/.oci" ]] || fail "cloud_credentials_detected"
[[ ! -e /var/run/docker.sock ]] || fail "docker_socket_on_vm"
cd "$base"
archive="$base/runner.tar.gz"
cleanup() {
  rc=$?
  trap - EXIT
  # VM destruction is required after run.sh, even if the job failed.
  rm -rf -- "$base/_work" "$base/runner.tar.gz" "$base/.credentials" "$base/.credentials_rsaparams" 2>/dev/null || true
  printf 'RUNNER_PILOT_PROCESS_EXIT=%s\n' "$rc"
  exit "$rc"
}
trap cleanup EXIT
curl --fail --silent --show-error --location --retry 2 --max-time 180 \
  "$RUNNER_TARBALL_URL" --output "$archive"
printf '%s  %s\n' "$RUNNER_TARBALL_SHA256" "$archive" | sha256sum --check --status || fail "runner_package_hash_mismatch"
tar -xzf "$archive" -C "$base" --no-same-owner
rm -f "$archive"
[[ -x "$base/config.sh" && -x "$base/run.sh" ]] || fail "invalid_runner_package"
printf 'AWAITING_SINGLE_USE_REGISTRATION_TOKEN_STDIN\n'
IFS= read -r token || fail "missing_registration_token"
[[ "${#token}" -ge 20 && "${#token}" -le 256 && "$token" != *[[:space:]]* ]] || fail "malformed_token"
./config.sh --unattended --ephemeral --disableupdate \
  --url "$RUNNER_REPO_URL" --token "$token" --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABEL" --work "_work"
unset token
printf 'EPHEMERAL_REGISTERED_WAITING_FOR_ONE_JOB\n'
timeout --signal=TERM --kill-after=30s 1500s ./run.sh
printf 'ONE_JOB_RUNNER_EXITED_DESTROY_VM_NOW\n'