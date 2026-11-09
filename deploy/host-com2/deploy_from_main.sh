#!/usr/bin/env bash
# Standard COM2 deployment after the 2026-10-31 cutover: merging to main no
# longer reaches the host by itself.
#
#   bash deploy_from_main.sh <main-sha>             plan only (the default)
#   bash deploy_from_main.sh <main-sha> --apply     move, reinstall, restart, health
#   bash deploy_from_main.sh <main-sha> --stage-only  mirror + permission checks only
#
# The services read their code as their own user, and over the 9p (D:) mount a
# file can stay unreadable there no matter what chmod says — the Windows ACL
# decides. So nothing is installed from the checkout: the target tree is first
# mirrored onto Linux storage, made world-readable, and only then does a single
# service get touched. Each mirror, release and rollback snapshot must report
# zero files the service user cannot read, or the run stops before that point.
#
# The production checkout is an operator setting, never a shared folder. The
# script refuses a SHA that is not origin/main, a checkout that is the staging
# checkout, a dirty tracked tree, a Chat database it cannot read, and a new
  # but an --apply run backs the Chat database up and applies it first.
#
# It never edits .env or any secret, never touches Cloudflare, the tunnel or the
# Windows 18731 release, and never enables a unit.
#
# Configuration (environment; every path is the operator's, none is guessed):
#   PADIEM_COM2_OPS_CHECKOUT     production checkout (required)
#   PADIEM_COM2_STAGING_CHECKOUT staging checkout to stay apart (default below)
#   PADIEM_COM2_STATE_DIR        private execution state (default below)
#   PADIEM_COM2_DEPLOY_LOCK      one-run lock (default <state dir>/deploy.lock)
#   PADIEM_COM2_PREVIOUS_DIR     root-owned, service-readable rollback worktrees
#   PADIEM_COM2_SOURCE_DIR       Linux-side staging mirror the services install from
#   PADIEM_COM2_READ_CHECK_USER  user the readability checks run as (default padiem-chat)
#   PADIEM_COM2_CHAT_HEALTH_ATTEMPTS / PADIEM_COM2_CHAT_HEALTH_INTERVAL
#   PADIEM_COM2_CHAT_HEALTH_TIMEOUT
#   PADIEM_COM2_CHAT_DB          Chat SQLite file holding the migration ledger
#   PADIEM_COM2_CHAT_DB_USER     owner the Chat migration backup and apply run as (default padiem-chat)
#   PADIEM_COM2_P01_APP          P01 install root (#6442 releases/rollback)
#   PADIEM_COM2_B14_APP          B14 app tree (a link into the mirror)
#   PADIEM_COM2_CHAT_APP         Chat app tree (a link into the mirror)
#   PADIEM_COM2_MESH_QUEUE_APP   the PC queue install root (its code also from the mirror)
#   PADIEM_COM2_MESH_QUEUE_USER  the account that owns that root
#   PADIEM_COM2_QUEUE_UNIT_DIR   where the queue units are installed (/etc/systemd/system)
#   PADIEM_COM2_EXECUTOR_UNIT_DIR  where the executor's unit is installed (/etc/systemd/system)
#   PADIEM_COM2_EXECUTOR_UNIT_SYNC 1 copies a differing executor unit; default 0
#                                reports EXECUTOR_UNIT_DRIFT and changes nothing
#   PADIEM_COM2_INSTALLED_ROOT  prefix for the sidecar drift report's installed paths
#                                (empty on the host; the offline test points it at a temp dir)
#   PADIEM_COM2_HEALTH_TIMEOUT / PADIEM_COM2_HEALTH_INTERVAL
#                                how long a start or a rollback may take to become
#                                healthy (240s, 2s)
#   PADIEM_COM2_UNIT_WAIT_TIMEOUT / PADIEM_COM2_PORT_WAIT_TIMEOUT
#                                how long systemctl is-active and the port bind may
#                                take before the health contract is even probed (30s, 240s)
#   PADIEM_COM2_STOP_WAIT_TIMEOUT  how long the previous process may take to release
#                                MainPID 0 and its port (30s)
#   PADIEM_COM2_WAIT_POLL_INTERVAL  poll gap inside every wait stage (1s)
#   PADIEM_COM2_SS               ss wrapper
#   PADIEM_COM2_CHAT_PORT / PADIEM_COM2_P01_PORT / PADIEM_COM2_B14_PORT
#                                the loopback ports the ladders watch (8798/8811/8789)
#   PADIEM_COM2_SYSTEMCTL        systemctl wrapper
#   PADIEM_COM2_PYTHON           python3
#   PADIEM_COM2_GIT              git
#   B66_CGI_ALPHA_USERNAME / B66_CGI_ALPHA_PASSWORD  existing QA account
#                                (also auto-loaded from the root-only
#                                /etc/padiem/qa-smoke.env below)
#   PADIEM_COM2_CHAT_VENV_PYTHON  the chat service's own venv interpreter
#                                (default /opt/padiem/chat-com2/venv/bin/python)
#   PADIEM_COM2_AI_CHECK_BASE_URL  target Chat origin (default https://chat.padiem.net)
#   COM2_CHAT_HEALTH_URL / COM2_P01_HEALTH_URL / COM2_B14_HEALTH_URL
set -euo pipefail
umask 077
# Root-run import checks must not leave __pycache__ in the staged tree; the
# service user cannot read a root-owned bytecode directory.
export PYTHONDONTWRITEBYTECODE=1

# The QA smoke account (provision_qa_smoke_account.ps1 writes it root-only
# 0600) reaches this systemd-run script only through the environment, so one
# source line connects the file to the AI answer gate's B66_CGI_ALPHA_* pair.
qa_smoke_env=${PADIEM_COM2_QA_SMOKE_ENV:-/etc/padiem/qa-smoke.env}
if [[ -r $qa_smoke_env ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$qa_smoke_env"
  set +a
fi

ops_checkout=${PADIEM_COM2_OPS_CHECKOUT:-}
staging_checkout=${PADIEM_COM2_STAGING_CHECKOUT:-/mnt/d/work/ai-revenue-lab-staging-chat}
state_dir=${PADIEM_COM2_STATE_DIR:-/var/lib/padiem-com2-deploy}
previous_dir=${PADIEM_COM2_PREVIOUS_DIR:-/opt/padiem/com2-deploy/previous}
# Beside the rollback worktrees by default: the same Linux-side storage, so a
# test run never writes into /opt and a host needs no second knob.
source_stage_dir=${PADIEM_COM2_SOURCE_DIR:-"${previous_dir%/*}/src"}
read_check_user=${PADIEM_COM2_READ_CHECK_USER:-padiem-chat}
staged=''
stage_only=0
# A service that has not finished binding its loopback port is not an unhealthy
# service. One probe used to be enough to call a rollback, so every service except
# Chat (which already had its own patience) retries until this deadline. 11-02:
# the deadline is the whole readiness budget now, and Chat walks the same ladder
# instead of carrying separate attempt caps.
# 11-06: the same shape of the 11-02 B14 case, measured on Chat. Under the
# staging copy and a neighbouring restart, a cold import took 56 s while the
# port was still unbound; a 30 s wait rolled a good release back, and the
# rollback release then bound in 5 s. A start that has not bound is not an
# unhealthy release, so both remaining readiness deadlines default to 240 s.
# An explicit value always wins.
health_timeout=${PADIEM_COM2_HEALTH_TIMEOUT:-240}
health_interval=${PADIEM_COM2_HEALTH_INTERVAL:-2}
# 11-02 B14: the release was fine, but the probe ran while the unit was still
# activating and the port did not exist yet, so a good tree rolled itself back.
# Each readiness stage therefore has its own bound, and the previous process
# must be provably gone before the new one starts.
unit_wait_timeout=${PADIEM_COM2_UNIT_WAIT_TIMEOUT:-30}
port_wait_timeout=${PADIEM_COM2_PORT_WAIT_TIMEOUT:-240}
stop_wait_timeout=${PADIEM_COM2_STOP_WAIT_TIMEOUT:-30}
wait_poll_interval=${PADIEM_COM2_WAIT_POLL_INTERVAL:-1}
ss_bin=${PADIEM_COM2_SS:-ss}
chat_port=${PADIEM_COM2_CHAT_PORT:-8798}
p01_port=${PADIEM_COM2_P01_PORT:-8811}
b14_port=${PADIEM_COM2_B14_PORT:-8789}
chat_db=${PADIEM_COM2_CHAT_DB:-/mnt/d/padiem/chat-com2/chat.sqlite3}
chat_db_user=${PADIEM_COM2_CHAT_DB_USER:-padiem-chat}
p01_root=${PADIEM_COM2_P01_APP:-/opt/padiem/p01}
b14_app=${PADIEM_COM2_B14_APP:-/opt/padiem/b14/app}
chat_app=${PADIEM_COM2_CHAT_APP:-/opt/padiem/chat-com2/app}
queue_root=${PADIEM_COM2_MESH_QUEUE_APP:-/opt/padiem/mesh-queue}
queue_account=${PADIEM_COM2_MESH_QUEUE_USER:-padiem-mesh}
queue_unit_dir=${PADIEM_COM2_QUEUE_UNIT_DIR:-/etc/systemd/system}
# The Oracle mesh executor ran from a hand copy of this repository that no
# deploy updated. Its tree is a commit directory now, with the PYTHONPATH
# path the unit already names pointing at it.
executor_root=${PADIEM_COM2_ORACLE_MESH_ROOT:-/opt/padiem/oracle-mesh}
executor_src=$executor_root/kagent-src
executor_releases=$executor_root/src
executor_unit_dir=${PADIEM_COM2_EXECUTOR_UNIT_DIR:-/etc/systemd/system}
executor_unit_sync=${PADIEM_COM2_EXECUTOR_UNIT_SYNC:-0}
# Every installed path the sidecar drift report reads is absolute on the host.
aux_root=${PADIEM_COM2_INSTALLED_ROOT:-}
systemctl_bin=${PADIEM_COM2_SYSTEMCTL:-systemctl}
journalctl_bin=${PADIEM_COM2_JOURNALCTL:-journalctl}
python_bin=${PADIEM_COM2_PYTHON:-python3}
git_bin=${PADIEM_COM2_GIT:-git}
chat_health_url=${PADIEM_COM2_CHAT_HEALTH_URL:-http://127.0.0.1:8798/health}
p01_health_url=${PADIEM_COM2_P01_HEALTH_URL:-http://127.0.0.1:8811/internal/v1/health}
b14_health_url=${PADIEM_COM2_B14_HEALTH_URL:-http://127.0.0.1:8789/health}
apply=0
ai_check=warn
extended_smoke=0
ai_base_url=${PADIEM_COM2_AI_CHECK_BASE_URL:-https://chat.padiem.net}
chat_venv_python=${PADIEM_COM2_CHAT_VENV_PYTHON:-/opt/padiem/chat-com2/venv/bin/python}
chat_root=${PADIEM_COM2_CHAT_ROOT:-/opt/padiem/chat-com2}
chat_env_file=${PADIEM_COM2_CHAT_ENV_FILE:-$chat_root/.env}
requested=''
resolved=''
old=''

CHAT_UNIT=padiem-chat-com2.service
P01_UNIT=padiem-p01.service
B14_UNIT=padiem-b14.service
QUEUE_UNIT=padiem-mesh-queue.service
EXECUTOR_UNIT=padiem-oracle-mesh-executor.service

# The files the queue's own installer installs from deploy/ (#6892 follow-up).
# The code mirror excludes them, so they follow the deployed commit through
# sync_queue_installer_files instead of a hand run of install.sh.
QUEUE_INSTALLER_FILES=(
  padiem-mesh-queue.service
  padiem-mesh-queue-health.service
  padiem-mesh-queue-health.timer
  provision_service_secret.sh
)

fail() { printf 'COM2_DEPLOY=STOP\nCOM2_DEPLOY_REASON=%s\n' "$1" >&2; exit "${2:-2}"; }
say() { printf 'COM2_DEPLOY_%s\n' "$*"; }

usage() {
  cat >&2 <<'USAGE'
usage: deploy_from_main.sh <main-sha> [--apply] [--dry-run] [--stage-only]
       [--ops-checkout PATH] [--state-dir PATH] [--chat-db PATH] [--ai-check=required|warn] [--smoke]
USAGE
}

parse_args() {
  while (($#)); do
    case "$1" in
      --apply) apply=1; shift ;;
      --dry-run) apply=0; shift ;;
      --smoke) extended_smoke=1; shift ;;
      --stage-only) stage_only=1; shift ;;
      --ai-check=warn) ai_check=warn; shift ;;
      --ai-check=required) ai_check=required; shift ;;
      --ops-checkout) ops_checkout=${2:?path required}; shift 2 ;;
      --state-dir) state_dir=${2:?path required}; shift 2 ;;
      --chat-db) chat_db=${2:?path required}; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      -*) fail INVALID_ARGUMENT ;;
      *)
        [[ -z $requested ]] || fail INVALID_ARGUMENT
        requested=$1; shift
        ;;
    esac
  done
  [[ -n $requested ]] || { usage; exit 2; }
}

# Only one run may read or move the operating checkout at a time. A plan that
# runs while an apply is moving HEAD reads the new commit as PREVIOUS and turns
# the missing diff into a false SKIP (2026-11-07 05:34: another lane's apply had
# already moved the checkout to 80be22ee, so the plan reported chat:SKIP).
# Every mode takes the same exclusive lock. flock releases it even when the
# holder is killed; the directory fallback covers shells without util-linux and
# records the holder PID there.
deploy_lock_dir=''
release_deploy_lock() {
  if [[ -n $deploy_lock_dir ]]; then rm -rf -- "$deploy_lock_dir"; fi
  return 0
}

acquire_deploy_lock() {
  local lock_path=${PADIEM_COM2_DEPLOY_LOCK:-"$state_dir/deploy.lock"} holder
  if command -v flock >/dev/null 2>&1; then
    exec 9>>"$lock_path" || fail DEPLOY_LOCK_UNWRITABLE
    if ! flock -n 9; then
      say "LOCK=BUSY PATH=$lock_path"
      fail DEPLOY_IN_PROGRESS
    fi
    say "LOCK=ACQUIRED PATH=$lock_path"
    return 0
  fi
  deploy_lock_dir="$lock_path.d"
  if ! mkdir -- "$deploy_lock_dir" 2>/dev/null; then
    holder=$(cat -- "$deploy_lock_dir/pid" 2>/dev/null || true)
    if [[ -z $holder ]]; then
      # The holder may be between mkdir and writing its PID; never steal it.
      sleep 0.2
      holder=$(cat -- "$deploy_lock_dir/pid" 2>/dev/null || true)
    fi
    if [[ $holder =~ ^[0-9]+$ ]] && kill -0 -- "$holder" 2>/dev/null; then
      say "LOCK=BUSY PATH=$lock_path HOLDER=$holder"
      fail DEPLOY_IN_PROGRESS
    fi
    if [[ -z $holder ]]; then
      say "LOCK=BUSY PATH=$lock_path"
      fail DEPLOY_IN_PROGRESS
    fi
    # A killed holder cannot keep the lock forever.
    rm -rf -- "$deploy_lock_dir"
    mkdir -- "$deploy_lock_dir" 2>/dev/null || {
      say "LOCK=BUSY PATH=$lock_path"
      fail DEPLOY_IN_PROGRESS
    }
  fi
  if ! printf '%s\n' "$$" > "$deploy_lock_dir/pid"; then
    release_deploy_lock
    fail DEPLOY_LOCK_UNWRITABLE
  fi
  say "LOCK=ACQUIRED PATH=$lock_path"
}

# The script moves the checkout it lives in, and bash keeps reading this file as
# it runs. Execute an immutable copy from the state directory instead.
main() {
  parse_args "$@"
  if [[ -n ${PADIEM_COM2_DEPLOY_REEXEC_COPY:-} ]]; then
    # This process is the immutable copy; remove it when the run ends.
    trap 'release_deploy_lock; rm -f -- "$PADIEM_COM2_DEPLOY_REEXEC_COPY"' EXIT
  fi
  if [[ -z ${PADIEM_COM2_DEPLOY_REEXEC:-} ]]; then
    export PADIEM_COM2_DEPLOY_REEXEC=1
    mkdir -p -- "$state_dir" || fail STATE_DIR_UNWRITABLE
    copy="$state_dir/deploy_from_main.$$.sh"
    cp -- "${BASH_SOURCE[0]}" "$copy" || fail STATE_DIR_UNWRITABLE
    export PADIEM_COM2_DEPLOY_REEXEC_COPY="$copy"
    exec bash "$copy" "$@"
  fi
  [[ -n $ops_checkout ]] || fail OPS_CHECKOUT_REQUIRED
  ops_checkout=$(readlink -f -- "$ops_checkout") || fail OPS_CHECKOUT_INVALID
  [[ -d $ops_checkout ]] || fail OPS_CHECKOUT_MISSING
  [[ -e $ops_checkout/.git ]] || fail OPS_CHECKOUT_NOT_A_REPO
  if [[ -e $staging_checkout ]] \
    && [[ $(readlink -f -- "$staging_checkout") == "$ops_checkout" ]]; then
    fail OPS_CHECKOUT_IS_STAGING
  fi
  # Before any mode reads HEAD or stages the mirror: a second run must stop
  # here, not after it has already planned against a moving checkout.
  acquire_deploy_lock
  if (( apply )); then
    [[ $(uname -s) == Linux ]] || fail LINUX_REQUIRED
    [[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
    command -v -- "$systemctl_bin" >/dev/null 2>&1 || fail SYSTEMD_MISSING
  fi
  run_deploy "$requested"
}

# Test, documentation and sample-environment changes do not justify a
# service restart. Return a stable reason so the deploy plan can account for
# every excluded path without weakening runtime/configuration changes.
deploy_path_exclusion() {
  local path=$1 base
  base=${path##*/}
  case "/$path/" in
    */tests/*|*/test/*) printf 'TEST_DIRECTORY'; return 0 ;;
  esac
  case "$base" in
    test_*.py|*_test.py|conftest.py|pytest.ini|*.test.mjs)
      printf 'TEST_FILE'; return 0 ;;
    .env.example)
      printf 'EXAMPLE_CONFIG'; return 0 ;;
    .gitignore|progress.md)
      printf 'REPO_META'; return 0 ;;
  esac
  case "/$path/" in
    */docs/*) printf 'DOCUMENTATION'; return 0 ;;
  esac
  case "$path" in
    *.md) printf 'DOCUMENTATION'; return 0 ;;
  esac
  return 1
}

# Service path rules. Shared packages are Chat inputs; packages installed into
# the P01 release also select P01. p01_matches_target remains an independent
# fail-safe for live code that is missing or cannot be verified.
service_for_path() {
  case "$1" in
    apps/padiem-chat/*|apps/padiem-council-apps/static/*|packages/*|deploy/host-com2/chat/*)
      printf '%s\n' chat ;;
    *) : ;;
  esac
  case "$1" in
    apps/padiem-ai-engine/*|deploy/host-com2/p01/*|packages/padiem-ai-core/*|packages/padiem-control-plane/*|apps/korean-ai-code-agent/src/kagent/*)
      printf '%s\n' p01 ;;
    deploy/host-com2/restart-policy/*)
      printf '%s\n' chat
      printf '%s\n' p01
      printf '%s\n' b14
      printf '%s\n' queue ;;
    # The executor's unit source: only its sync step reads it, so a change here
    # has to select the executor or the new file never reaches the check.
    deploy/host-com2/oracle-mesh/*)
      printf '%s\n' executor ;;
    *) : ;;
  esac
  case "$1" in
    apps/korean-ai-platform/*|deploy/host-com2/b14/*)
      printf '%s\n' b14 ;;
    *) : ;;
  esac
  case "$1" in
    apps/padiem-mesh-queue/*)
      printf '%s\n' queue ;;
    *) : ;;
  esac
  # The executor stages this app tree plus the Core modules it imports, so the
  # app path selects it directly; the Core modules come from the import list.
  case "$1" in
    apps/korean-ai-code-agent/*)
      printf '%s
' executor ;;
    *) : ;;
  esac
}

# Migrations that exist in the target tree but are not in this host's ledger.
# The Chat host applies pending migrations on start, so this check runs before
# any code moves; an unreadable database is not a reason to assume none.
pending_migrations() {
  "$python_bin" - "$ops_checkout" "$resolved" "$chat_db" "$git_bin" <<'PY'
import os
import sqlite3
import subprocess
import sys

checkout, sha, db, git = sys.argv[1:5]
tree = subprocess.run(
    [git, "-C", checkout, "ls-tree", "--name-only", sha, "apps/padiem-chat/migrations/"],
    capture_output=True, text=True, check=True,
).stdout.split()
names = sorted(os.path.basename(path) for path in tree if path.endswith(".sql"))
try:
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
except sqlite3.Error:
    sys.exit(4)
try:
    applied = {row[0] for row in con.execute("SELECT name FROM padiem_local_migration_ledger")}
except sqlite3.Error:
    # No ledger yet: nothing is proven applied, so every migration is pending.
    applied = set()
finally:
    con.close()
for name in names:
    if name not in applied:
        print(name)
PY
}

unit_active() { "$systemctl_bin" is-active --quiet "$1"; }

# A unit that crashed and waits out RestartSec reports `activating`, where
# is-active is false while systemd still holds the next attempt. It is running
# work: the stop has to cancel that attempt, and the unit has to come back.
unit_running_or_restarting() {
  local state
  state=$("$systemctl_bin" show -p ActiveState --value "$1" 2>/dev/null || true)
  [[ $state == active || $state == activating ]]
}

unit_loaded() {
  local state
  state=$("$systemctl_bin" show -p LoadState --value "$1" 2>/dev/null || true)
  [[ $state == loaded ]]
}

# Display only: the ActiveState systemd reports, so a plan shows a unit waiting
# out RestartSec as `activating` instead of the `inactive` that is-active implies.
unit_state() {
  local state
  state=$("$systemctl_bin" show -p ActiveState --value "$1" 2>/dev/null || true)
  printf '%s' "${state:-unknown}"
}

# $1 unit, optional $2 label and $3 port. Stop whenever the unit is loaded.
# Stopping only an active unit left a pending auto-restart alive while the
# caller replaced code underneath it (11-07 05:38: the restart fired during
# Chat's one-link-at-a-time swap and imported a mixed tree). A label proves the
# old process — and its port, when one is named — is gone before the install.
with_service_stopped() {
  local unit=$1 label=${2:-} port=${3:-}
  unit_loaded "$unit" || return 0
  "$systemctl_bin" stop "$unit" || return 1
  if [[ -n $label ]]; then
    if [[ -n $port ]]; then
      wait_service_down "$label" "$unit" "$port" || return 1
    else
      wait_main_pid_gone "$label" "$unit" || return 1
    fi
  fi
}

# A listening check against the real `ss -ltn` output shape:
#   LISTEN 0 2048 127.0.0.1:8798 0.0.0.0:*
# The local address is followed by the peer column, so the port must be matched
# as a whole token followed by whitespace — never anchored at end of line
# (11-02: a `$` anchor never matched, so every LISTEN wait timed out and every
# RELEASED wait passed at once, rolling back healthy deploys). The grep consumes
# the whole stream on purpose: with pipefail, an early -q exit would turn a
# clean match into a SIGPIPE failure.
port_listening() {
  "$ss_bin" -ltn 2>/dev/null | grep -E "[:.]${1}[[:space:]]" > /dev/null
}

# Stage a — the unit must reach active before anything else is probed.
wait_unit_active() {
  local label=$1 unit=$2 deadline=$((SECONDS + unit_wait_timeout))
  while :; do
    if unit_active "$unit"; then
      say "UNIT_${label}_ACTIVE"
      return 0
    fi
    (( SECONDS < deadline )) || { say "UNIT_${label}_ACTIVE_TIMEOUT"; return 1; }
    sleep "$wait_poll_interval"
  done
}

# Stage b — the app binds its loopback port after the unit goes active. Probing
# the health contract before the bind exists is how a good B14 release rolled
# itself back on 11-02.
wait_port_listening() {
  local label=$1 port=$2 deadline=$((SECONDS + port_wait_timeout))
  while :; do
    if port_listening "$port"; then
      say "PORT_${label}_LISTENING"
      return 0
    fi
    (( SECONDS < deadline )) || { say "PORT_${label}_LISTENING_TIMEOUT"; return 1; }
    sleep "$wait_poll_interval"
  done
}

# The previous process is down when systemd reports MainPID 0. A re-execing or
# wedged MainPID would leave the port held for the new process to trip over.
wait_main_pid_gone() {
  local label=$1 unit=$2 deadline=$((SECONDS + stop_wait_timeout)) pid
  while :; do
    pid=$("$systemctl_bin" show -p MainPID --value "$unit" 2>/dev/null || printf '0')
    if [[ ! $pid =~ ^[0-9]+$ ]] || [[ $pid == 0 ]]; then
      say "MAINPID_${label}_GONE"
      return 0
    fi
    (( SECONDS < deadline )) || { say "MAINPID_${label}_GONE_TIMEOUT"; return 1; }
    sleep "$wait_poll_interval"
  done
}

# A port the old process still holds makes the new process fail to bind, which
# reads as a broken release instead of a busy one.
wait_port_released() {
  local label=$1 port=$2 deadline=$((SECONDS + stop_wait_timeout))
  while :; do
    if ! port_listening "$port"; then
      say "PORT_${label}_RELEASED"
      return 0
    fi
    (( SECONDS < deadline )) || { say "PORT_${label}_RELEASED_TIMEOUT"; return 1; }
    sleep "$wait_poll_interval"
  done
}

# Run after with_service_stopped: the old process is provably gone (MainPID 0)
# and the port is free before anything is installed or started.
wait_service_down() {
  local label=$1 unit=$2 port=$3
  wait_main_pid_gone "$label" "$unit" || return 1
  wait_port_released "$label" "$port" || return 1
}

# One readiness ladder for every restarted service:
#   a. unit active       (<= PADIEM_COM2_UNIT_WAIT_TIMEOUT, 30s)
#   b. port listening    (<= PADIEM_COM2_PORT_WAIT_TIMEOUT, 240s)
#   c. health contract   (<= PADIEM_COM2_HEALTH_TIMEOUT, 240s — stage d verdict)
# A stage timeout or a failed contract returns 1 and the caller rolls back.
wait_service_ready() {
  local label=$1 unit=$2 port=$3
  shift 3
  wait_unit_active "$label" "$unit" || return 1
  wait_port_listening "$label" "$port" || return 1
  wait_for_health "$label" "$@"
}

# stage_code.sh copies these exact paths into the release selected by app.
# $1 label, $2... the probe command. The first attempt runs immediately, later ones
# after a pause, and the deadline bounds the whole wait; the attempt count is
# reported so a slow start reads as a slow start instead of a broken release.
wait_for_health() {
  local label=$1 attempt=0 deadline remaining pause
  shift
  [[ $health_timeout =~ ^[1-9][0-9]*$ && $health_interval =~ ^[0-9]+$ ]] \
    || { say "HEALTH_${label}=INVALID_CONFIGURATION"; return 1; }
  deadline=$((SECONDS + health_timeout))
  while :; do
    attempt=$((attempt + 1))
    if "$@"; then
      say "HEALTH_${label}_ATTEMPTS=$attempt"
      return 0
    fi
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || { say "HEALTH_${label}_ATTEMPTS=$attempt"; return 1; }
    pause=$health_interval
    (( pause > remaining )) && pause=$remaining
    sleep "$pause"
  done
}

# The queue health script can exit zero for an unreachable or invalid response.
# Keep the generic retry loop, but require its explicit healthy marker as well.
queue_health_ok() {
  local output
  output=$("$@" 2>&1) || return 1
  printf '%s\n' "$output" | grep -Eq '^MESH_QUEUE_HEALTH=OK([[:space:]]|$)'
}

# Compare that actual link target with the requested Git tree. Missing, broken,
# or unprovable state is not evidence that a deployment can be skipped.
p01_matches_target() {
  local actual temp item result=0
  [[ -L $p01_root/app ]] || return 1
  actual=$(readlink -f -- "$p01_root/app") || return 1
  [[ -d $actual ]] || return 1
  temp=$(mktemp -d) || return 1
  if ! "$git_bin" -C "$ops_checkout" archive "$resolved" apps/padiem-ai-engine packages/padiem-ai-core/padiem_ai_core packages/padiem-control-plane/padiem_control_plane apps/korean-ai-code-agent/src/kagent | tar -x -C "$temp"; then
    rm -rf -- "$temp"
    return 1
  fi
  for item in app clients ingress migrations asgi.py worker.py worker_identity.py; do
    if ! diff -qr --exclude=__pycache__ --exclude='*.pyc' \
        "$temp/apps/padiem-ai-engine/$item" "$actual/$item" >/dev/null 2>&1; then
      result=1
      break
    fi
  done
  if (( result == 0 )); then
    for item in packages/padiem-ai-core/padiem_ai_core packages/padiem-control-plane/padiem_control_plane apps/korean-ai-code-agent/src/kagent; do
      if ! diff -qr --exclude=__pycache__ --exclude='*.pyc' \
          "$temp/$item" "$actual/$(basename "$item")" >/dev/null 2>&1; then
        result=1
        break
      fi
    done
  fi
  rm -rf -- "$temp"
  return "$result"
}

# Paths the installers, health probes and the post-deploy check read. A mirror
# of these is enough for every service and contains no operator state.
SOURCE_PATHS=(
  deploy/host-com2
  apps/padiem-chat
  apps/padiem-council-apps
  apps/padiem-ai-engine
  apps/korean-ai-platform
  apps/padiem-mesh-queue
  apps/korean-ai-code-agent/src/kagent
  packages/padiem-ai-core/padiem_ai_core
  packages/padiem-control-plane
  packages/padiem-auth-verify/verify.py
  .github/scripts
)

# $1 path, $2 user. access() as that user is the only question that matters on a
# 9p mount, where Windows ACLs can refuse a read that the mode bits promise.
# Where the caller cannot even reach the directory as that user (a private parent
# in a test run) the probe would report the ancestor, so fall back to mode bits.
probe_as_user() {
  # $1 is the account, the rest is the command. The probe runs from / because the
  # launcher's own directory is usually one the service account cannot enter —
  # root's home is 0700, and state_dir is 0700 too. Dropped into that account, find
  # cannot restore its initial working directory and exits non-zero; under
  # `set -euo pipefail` the caller then reads the "|| files=1" fallback as unreadable
  # source. Three runs on 11-03 stopped on SOURCE_PERMISSIONS_PREVIOUS that way
  # while both trees were in fact readable by the service account.
  local user=$1
  shift
  ( cd / && runuser -u "$user" -- "$@" )
}

read_check_method() {
  local path=$1 user=$2
  [[ ${EUID} -eq 0 ]] || { printf 'mode'; return; }
  getent passwd -- "$user" >/dev/null 2>&1 || { printf 'mode'; return; }
  if probe_as_user "$user" test -x "$path" 2>/dev/null; then printf 'access'; else printf 'mode'; fi
}

unreadable_files() {
  local path=$1 user=$2
  if [[ $(read_check_method "$path" "$user") == access ]]; then
    probe_as_user "$user" find "$path" -type f ! -readable -print 2>/dev/null | wc -l
    return
  fi
  find "$path" -type f ! -perm -0444 -print 2>/dev/null | wc -l
}

unreachable_dirs() {
  local path=$1 user=$2
  if [[ $(read_check_method "$path" "$user") == access ]]; then
    probe_as_user "$user" find "$path" -type d ! -readable -print 2>/dev/null | wc -l
    return
  fi
  find "$path" -type d ! -perm -0555 -print 2>/dev/null | wc -l
}

assert_service_readable() {
  # $1 label, $2 path, $3 user. Zero unreadable files and zero untraversable
  # directories, or the caller must not touch the service that reads this tree.
  local label=$1 path=$2 user=$3 files dirs
  if [[ ! -d $path ]]; then
    say "READABLE_${label}=MISSING PATH=$path"
    return 1
  fi
  files=$(unreadable_files "$path" "$user") || files=1
  dirs=$(unreachable_dirs "$path" "$user") || dirs=1
  say "READABLE_${label}_USER=$user METHOD=$(read_check_method "$path" "$user") FILES=$files DIRS=$dirs"
  (( files == 0 && dirs == 0 ))
}

stage_source() {
  # Mirror the target tree onto Linux storage. git archive reads objects, not
  # the working tree, so a 0600 checkout cannot poison the result.
  local target="$source_stage_dir/$resolved" temp marker
  marker=.padiem-stage-complete
  if [[ -f "$target/$marker" && $(cat -- "$target/$marker") == "$resolved" ]]; then
    staged=$target
    say "SOURCE_STAGED=CACHED PATH=$target"
    return 0
  fi
  [[ ! -L $source_stage_dir ]] || fail STAGE_DIR_INVALID
  install -d -m 0755 -- "$source_stage_dir" || fail STAGE_DIR_UNWRITABLE
  temp=$(mktemp -d "$source_stage_dir/.stage-XXXXXX") || fail STAGE_DIR_UNWRITABLE
  # Only paths the target tree actually carries; an operator checkout of a
  # smaller repository still stages everything it owns.
  local present=()
  while IFS= read -r name; do
    [[ -n $name ]] && present+=("$name")
  done < <("$git_bin" -C "$ops_checkout" ls-tree --name-only "$resolved" -- "${SOURCE_PATHS[@]}" 2>/dev/null)
  (( ${#present[@]} > 0 )) || fail STAGE_SOURCE_EMPTY
  if ! "$git_bin" -C "$ops_checkout" archive --format=tar "$resolved" "${present[@]}" \
      | tar -x -C "$temp"; then
    rm -rf -- "$temp"
    fail STAGE_ARCHIVE_FAILED
  fi
  # The mirror is code only: readable by every service, writable by nobody else.
  chmod -R a+rX,u+w,go-w "$temp" || { rm -rf -- "$temp"; fail STAGE_CHMOD_FAILED; }
  if [[ ${EUID} -eq 0 ]]; then chown -R root:root "$temp" || true; fi
  printf '%s\n' "$resolved" > "$temp/$marker" || { rm -rf -- "$temp"; fail STAGE_MARK_FAILED; }
  chmod a+rX,u+w,go-w "$temp/$marker" || { rm -rf -- "$temp"; fail STAGE_MARK_FAILED; }
  if [[ -e $target ]]; then
    mv -T "$target" "$target.stale.$$" || { rm -rf -- "$temp"; fail STAGE_SWAP_FAILED; }
  fi
  if ! mv -T "$temp" "$target"; then
    [[ -e $target.stale.$$ ]] && mv -T "$target.stale.$$" "$target"
    rm -rf -- "$temp"
    fail STAGE_SWAP_FAILED
  fi
  rm -rf -- "$target.stale.$$" 2>/dev/null || true
  staged=$target
  say "SOURCE_STAGED=PATH=$target"
}

# Every install and every post-deploy probe reads the mirror, never the checkout.
verify_staged_source() {
  stage_source
  assert_service_readable STAGED "$staged" "$read_check_user" \
    || fail SOURCE_PERMISSIONS_STAGED
  assert_service_readable STAGED_P01 "$staged/apps/padiem-ai-engine" padiem-p01 \
    || fail SOURCE_PERMISSIONS_STAGED_P01
}

# Move the production checkout to $resolved and keep $previous_dir/$old as the
# rollback source. The script-only path uses this too: the next plan reads this
# checkout, so a change to the script itself has to land here before it can act.
move_checkout_to_target() {
  if [[ -n $("$git_bin" -C "$ops_checkout" status --porcelain --untracked-files=no) ]]; then
    fail CHECKOUT_DIRTY
  fi

  # Rollback sources must be traversable by the service but not writable by it.
  [[ ! -L $previous_dir && ! -L $previous_dir/$old ]] || fail PREVIOUS_CHECKOUT_INVALID
  install -d -m 0755 -- "$previous_dir" || fail PREVIOUS_DIR_UNWRITABLE
  if [[ ! -d $previous_dir/$old ]]; then
    (umask 022; "$git_bin" -C "$ops_checkout" worktree add --detach --quiet \
      "$previous_dir/$old" "$old") || fail PREVIOUS_CHECKOUT_FAILED
  fi
  if [[ ${EUID} -eq 0 ]]; then
    chown root:root "$previous_dir" || fail PREVIOUS_CHECKOUT_FAILED
    chown -R root:root "$previous_dir/$old" || fail PREVIOUS_CHECKOUT_FAILED
  fi
  find "$previous_dir/$old" -type d -exec chmod a+rx,go-w {} + || fail PREVIOUS_CHECKOUT_FAILED
  find "$previous_dir/$old" -type f -exec chmod a+r,go-w {} + || fail PREVIOUS_CHECKOUT_FAILED
  assert_service_readable PREVIOUS "$previous_dir/$old" "$read_check_user" \
    || fail SOURCE_PERMISSIONS_PREVIOUS
  say "PREVIOUS_CHECKOUT=$previous_dir/$old"

  (umask 022; "$git_bin" -C "$ops_checkout" checkout --detach --quiet "$resolved") \
    || fail CHECKOUT_MOVE_FAILED
  # Older deploys may already have left tracked files at 0600. Restrict the
  # repair to tracked files and their directories; never expose untracked envs.
  "$python_bin" - "$ops_checkout" "$git_bin" <<'PY' || fail CHECKOUT_PERMISSIONS_FAILED
import os, stat, subprocess, sys
root = os.path.abspath(sys.argv[1])
files = subprocess.check_output([sys.argv[2], "-C", root, "ls-files", "-z"]).split(b"\0")
dirs = {root}
for name in files:
    if not name:
        continue
    path = os.path.join(root, os.fsdecode(name))
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        continue
    if stat.S_ISREG(mode):
        os.chmod(path, stat.S_IMODE(mode) | 0o444)
    parent = os.path.dirname(path)
    while parent.startswith(root + os.sep) and parent not in dirs:
        if os.path.islink(parent):
            raise RuntimeError("tracked directory is a symlink")
        dirs.add(parent)
        parent = os.path.dirname(parent)
for path in dirs:
    mode = os.stat(path).st_mode
    os.chmod(path, stat.S_IMODE(mode) | 0o555)
PY
  say "CHECKOUT=$ops_checkout"
}

deploy_chat() {
  local before_active=0
  if unit_running_or_restarting "$CHAT_UNIT"; then before_active=1; fi
  with_service_stopped "$CHAT_UNIT" CHAT "$chat_port" || return 1
  bash "$staged/deploy/host-com2/chat/install.sh" \
    --apply --source-root "$staged" || return 1
  assert_service_readable CHAT_LIVE "$staged/apps/padiem-chat/app" "$read_check_user" || return 1
  if (( before_active )); then
    "$systemctl_bin" start "$CHAT_UNIT" || return 1
    wait_service_ready CHAT "$CHAT_UNIT" "$chat_port" \
      "$python_bin" "$staged/deploy/host-com2/chat/health.py" --url "$chat_health_url"
  else
    say 'CHAT_START=SKIPPED_NOT_ACTIVE_BEFORE'
  fi
}

deploy_p01() {
  local before_active=0
  if unit_running_or_restarting "$P01_UNIT"; then before_active=1; fi
  with_service_stopped "$P01_UNIT" P01 "$p01_port" || return 1
  bash "$staged/deploy/host-com2/p01/install.sh" \
    --apply --source-root "$staged" || return 1
  local live
  live=$(readlink -f -- "$p01_root/app") || return 1
  assert_service_readable P01_LIVE "$live" padiem-p01 || return 1
  if (( before_active )); then
    "$systemctl_bin" start "$P01_UNIT" || return 1
    wait_service_ready P01 "$P01_UNIT" "$p01_port" \
      "$python_bin" "$staged/deploy/host-com2/p01/health.py" --url "$p01_health_url"
  else
    say 'P01_START=SKIPPED_NOT_ACTIVE_BEFORE'
  fi
}

# B14's app tree used to be an operator copy this script could neither update nor
# put back, so platform code on main could not reach 8789 and a failed install left
# the unit stopped. The link is now the deployment: the previous mirror, the previous
# rollback worktree or the displaced copy is the rollback, and the unit comes up
# either way.
link_b14_app() {
  # $1 the tree B14 must run. A copy the operator placed by hand is displaced, not
  # deleted: it is the only rollback left when no previous mirror exists.
  local target=$1 displaced
  [[ -d $target ]] || { say "B14_SOURCE_MISSING PATH=$target"; return 1; }
  stage_b14_shared_module "$target" || return 1
  if [[ ! -L $b14_app && -d $b14_app ]]; then
    displaced="${b14_app}.displaced-$(date +%Y%m%dT%H%M%S)"
    mv -- "$b14_app" "$displaced" || { say 'B14_DISPLACE_FAILED'; return 1; }
    say "B14_OPERATOR_COPY=$displaced"
  fi
  ln -sfn -- "$target" "$b14_app" || return 1
  say "B14_LINK=$target"
}

# The installer puts one shared Core module inside B14's app tree. A rollback never
# runs the installer, and a tree without that module exits on import — so the link,
# forward or back, has to guarantee it.
stage_b14_shared_module() {
  local target=$1 package source root module module_source cp_package cp_source
  package="$target/padiem_ai_core"
  if [[ ! -f $package/pc_work_metrics.py ]]; then
    source=''
    for root in "$source_stage_dir/$resolved" "$source_stage_dir/$old" "$staged"; do
      [[ -n $root && -f "$root/packages/padiem-ai-core/padiem_ai_core/pc_work_metrics.py" ]]         && { source="$root/packages/padiem-ai-core/padiem_ai_core/pc_work_metrics.py"; break; }
    done
    [[ -n $source ]] || { say 'B14_SHARED_MODULE_MISSING'; return 1; }
    install -d -m 0755 -- "$package" || return 1
    [[ -e $package/__init__.py ]]       || printf '%s
' '"\"\"\"Deployment-staged canonical Core modules.\"\"\""' > "$package/__init__.py"
    install -m 0644 -- "$source" "$package/pc_work_metrics.py" || return 1
    say "B14_SHARED_MODULE=$source"
  fi
  # #6848: the platform imports more than one Core module now. Stage every
  # canonical module this tree lacks from the same staged release, so a forward
  # link and a rollback link both import cleanly.
  for module in conversation_bounds.py evidence_blocks.py; do
    [[ -f $package/$module ]] && continue
    module_source=''
    for root in "$source_stage_dir/$resolved" "$source_stage_dir/$old" "$staged"; do
      [[ -n $root && -f "$root/packages/padiem-ai-core/padiem_ai_core/$module" ]]         && { module_source="$root/packages/padiem-ai-core/padiem_ai_core/$module"; break; }
    done
    [[ -n $module_source ]] || continue
    install -m 0644 -- "$module_source" "$package/$module" || return 1
    say "B14_SHARED_MODULE=$module SOURCE=$module_source"
  done
  chmod -R a+rX,go-w -- "$package" || return 1
  # #6828: the private-registry switch imports padiem_control_plane.models_registry
  # at boot, and the package is not otherwise in this tree. Stage the whole package
  # so a forward link and a rollback link both import it without a host PYTHONPATH.
  cp_package="$target/padiem_control_plane"
  if [[ ! -f $cp_package/models_registry.py ]]; then
    cp_source=''
    for root in "$source_stage_dir/$resolved" "$source_stage_dir/$old" "$staged"; do
      [[ -n $root && -f "$root/packages/padiem-control-plane/padiem_control_plane/models_registry.py" ]]         && { cp_source="$root/packages/padiem-control-plane/padiem_control_plane"; break; }
    done
    [[ -n $cp_source ]] || { say 'B14_CONTROL_PLANE_MISSING'; return 1; }
    rm -rf -- "$cp_package" || return 1
    cp -a -- "$cp_source" "$cp_package" || return 1
    find "$cp_package" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    say "B14_CONTROL_PLANE=$cp_source"
  fi
  chmod -R a+rX,go-w -- "$cp_package" || return 1
}

b14_rollback_source() {  # The newest thing that is provably the previous code, or nothing.
  local candidate displaced
  displaced=$(ls -1dt "$b14_app".displaced-* 2>/dev/null | head -1 || true)
  for candidate in "$source_stage_dir/$old/apps/korean-ai-platform" \
                   "$previous_dir/$old/apps/korean-ai-platform" \
                   "$displaced"; do
    [[ -n $candidate && -d $candidate ]] && { printf '%s' "$candidate"; return 0; }
  done
  return 1
}

deploy_b14() {
  local before_active=0
  if unit_running_or_restarting "$B14_UNIT"; then before_active=1; fi
  with_service_stopped "$B14_UNIT" B14 "$b14_port" || return 1
  link_b14_app "$staged/apps/korean-ai-platform" || return 1
  bash "$staged/deploy/host-com2/b14/install.sh" --reload || return 1
  assert_service_readable B14_LIVE "$staged/apps/korean-ai-platform" padiem-b14 || return 1
  if (( before_active )); then
    "$systemctl_bin" start "$B14_UNIT" || return 1
    wait_service_ready B14 "$B14_UNIT" "$b14_port" \
      "$python_bin" "$staged/deploy/host-com2/b14/health.py" --url "$b14_health_url"
  else
    say 'B14_START=SKIPPED_NOT_ACTIVE_BEFORE'
  fi
}

# Chat's live links point into a checkout, so its rollback is the previous
# checkout itself.
rollback_chat() {
  local previous="$previous_dir/$old"
  [[ -d $previous/deploy/host-com2/chat ]] || { say 'CHAT_ROLLBACK=NO_PREVIOUS_CHECKOUT'; return 1; }
  # The failing unit waits in `activating` for its next Restart=always attempt,
  # where is-active is false. The helper stops it unconditionally and proves it
  # is gone, so no restart can fire while the installer swaps links one at a time.
  with_service_stopped "$CHAT_UNIT" CHAT_ROLLBACK "$chat_port" || return 1
  bash "$previous/deploy/host-com2/chat/install.sh" \
    --apply --source-root "$previous" || return 1
  "$systemctl_bin" start "$CHAT_UNIT" || return 1
  wait_service_ready CHAT_ROLLBACK "$CHAT_UNIT" "$chat_port" \
    "$python_bin" "$previous/deploy/host-com2/chat/health.py" --url "$chat_health_url"
}

# P01's own installer snapshots the replaced app (#6442); rollback re-points the
# release link at that snapshot, exactly as deploy/host-com2/p01/README.md says.
rollback_p01() {
  local snapshot
  snapshot=$(ls -1dt "$p01_root"/rollback/p01.* 2>/dev/null | head -1 || true)
  [[ -n $snapshot ]] || { say 'P01_ROLLBACK=NO_SNAPSHOT'; return 1; }
  with_service_stopped "$P01_UNIT" P01_ROLLBACK "$p01_port" || return 1
  # A snapshot taken before this existed may still be 0600; a rollback that
  # cannot be read is no rollback at all, so fix it and then prove it.
  chmod -R a+rX,u+w,go-w "$snapshot" || return 1
  assert_service_readable P01_ROLLBACK "$snapshot" padiem-p01 || return 1
  local next="$p01_root/.app-rollback-$$" displaced=""
  ln -s "$snapshot" "$next" || return 1
  if [[ -d $p01_root/app && ! -L $p01_root/app ]]; then
    install -d -m 0755 "$p01_root/releases" || { rm -f "$next"; return 1; }
    displaced=$(mktemp -d "$p01_root/releases/p01.displaced.XXXXXXXX") || { rm -f "$next"; return 1; }
    rmdir "$displaced" || { rm -f "$next"; return 1; }
    mv -T "$p01_root/app" "$displaced" || { rm -f "$next"; return 1; }
  fi
  if ! mv -Tf "$next" "$p01_root/app"; then
    [[ -z $displaced ]] || mv -T "$displaced" "$p01_root/app"
    rm -f "$next"
    return 1
  fi
  "$systemctl_bin" start "$P01_UNIT" || return 1
  wait_service_ready P01_ROLLBACK "$P01_UNIT" "$p01_port" "$python_bin" "$staged/deploy/host-com2/p01/health.py" --url "$p01_health_url"
}

rollback_b14() {
  local previous="$previous_dir/$old/apps/korean-ai-platform" source
  if source=$(b14_rollback_source); then
    with_service_stopped "$B14_UNIT" B14_ROLLBACK "$b14_port" || return 1
    link_b14_app "$source" || return 1
    "$systemctl_bin" start "$B14_UNIT" || return 1
    wait_service_ready B14_ROLLBACK "$B14_UNIT" "$b14_port" \
      "$python_bin" "$staged/deploy/host-com2/b14/health.py" --url "$b14_health_url"
    return
  fi
  # Nothing this script owns can put the code back, so say so instead of guessing.
  # A stopped unit is not a rollback either: bring it up on whatever the link holds.
  printf 'COM2_DEPLOY_B14_ROLLBACK=MANUAL PREVIOUS=%s\n' "$previous" >&2
  wait_service_down B14_ROLLBACK "$B14_UNIT" "$b14_port" || return 1
  "$systemctl_bin" start "$B14_UNIT" || return 1
  wait_service_ready B14_ROLLBACK "$B14_UNIT" "$b14_port" \
    "$python_bin" "$staged/deploy/host-com2/b14/health.py" --url "$b14_health_url"
}

# What a service actually runs, computed from the code itself.
#
# The queue links the Chat app tree, the Core package and the control plane into
# its root, so those modules are queue code even though they live under another
# app's path. #6794 made the pairing claim idempotent in apps/padiem-chat/app, and
# every deploy after it still reported queue:SKIP because service_for_path names
# only chat there. The Oracle mesh executor has the same shape: it stages kagent
# and the Core modules kagent imports, so a change to any of them has to move the
# process that does the reads (#6889 never reached it).
#
# The list comes from the imports themselves: every module reachable from the
# service's own tree at the deployed commit. A hand-written allowlist is the same
# bug one import later, so no path is spelled out by name here.
module_import_closure() {
  # $1 the commit, $2 the tree the service runs, $3... every "module=directory"
  # pair those modules may import from.
  "$python_bin" - "$ops_checkout" "$1" "${@:2}" <<'CLOSURE_PY'
import ast
import subprocess
import sys

sys.stdout.reconfigure(newline="\n")
repo, sha, entry = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
pairs = dict(argument.split("=", 1) for argument in sys.argv[4:])

GIT = ["git", "-C", repo]


def git(*args):
    done = subprocess.run(
        GIT + list(args), capture_output=True, text=True, encoding="utf-8", check=True
    )
    return done.stdout


tree = {
    line.strip()
    for line in git("ls-tree", "-r", "--name-only", sha).splitlines()
    if line.strip()
}

# The trees a module may belong to: the service's own, then each package it links.
roots = [entry] + [directory.rstrip("/") for directory in pairs.values()]


def candidates(base, parts):
    if not parts:
        return [base + "/__init__.py"] if base + "/__init__.py" in tree else []
    tail = "/".join(parts)
    found = [base + "/" + tail + ".py", base + "/" + tail + "/__init__.py"]
    for index in range(1, len(parts) + 1):
        found.append(base + "/" + "/".join(parts[:index]) + "/__init__.py")
    return [path for path in found if path in tree]


def resolve(path, module, level):
    """The files one import statement in `path` refers to."""
    parts = [part for part in (module or "").split(".") if part]
    holding = [root for root in roots if path.startswith(root + "/")]
    if not holding:
        return []
    root = max(holding, key=len)
    package = path[len(root) + 1:].split("/")[:-1]
    if level:
        keep = len(package) - (level - 1)
        if keep < 0:
            return []
        base = root + ("/" + "/".join(package[:keep]) if keep else "")
        return candidates(base, parts)
    if parts and parts[0] in pairs:
        return candidates(pairs[parts[0]].rstrip("/"), parts[1:])
    if root == entry and len(parts) == 1:
        return candidates(entry, parts)
    return []


def imports_of(path):
    try:
        node = ast.parse(git("show", "%s:%s" % (sha, path)))
    except (SyntaxError, ValueError):
        return []
    found = []
    for statement in ast.walk(node):
        if isinstance(statement, ast.Import):
            found.extend((alias.name, 0) for alias in statement.names)
        elif isinstance(statement, ast.ImportFrom):
            found.append((statement.module or "", statement.level))
            for alias in statement.names:
                name = (
                    "%s.%s" % (statement.module, alias.name)
                    if statement.module
                    else alias.name
                )
                found.append((name, statement.level))
    return found


# Every module the service runs: its own tree, never tests.
pending = sorted(
    path
    for path in tree
    if path.startswith(entry + "/")
    and path.endswith(".py")
    and "/tests/" not in path
    and not path.rsplit("/", 1)[-1].startswith("test_")
    and path.rsplit("/", 1)[-1] != "conftest.py"
)
seen = set()
while pending:
    path = pending.pop()
    if path in seen:
        continue
    seen.add(path)
    for module, level in imports_of(path):
        for target in resolve(path, module, level):
            if target not in seen:
                pending.append(target)

for path in sorted(seen):
    print(path)
CLOSURE_PY
}

# The queue's own root is its app tree; what it links in comes from the imports.
queue_import_closure() {
  module_import_closure "$1" apps/padiem-mesh-queue \
    app=apps/padiem-chat/app \
    padiem_ai_core=packages/padiem-ai-core/padiem_ai_core \
    padiem_control_plane=packages/padiem-control-plane/padiem_control_plane
}

# The executor runs kagent, which imports the Core package.
executor_import_closure() {
  module_import_closure "$1" apps/korean-ai-code-agent/src/kagent \
    kagent=apps/korean-ai-code-agent/src/kagent \
    padiem_ai_core=packages/padiem-ai-core/padiem_ai_core \
    padiem_agent=packages/padiem-ai-core/padiem_agent
}

# The Oracle mesh executor (`padiem-oracle-mesh-executor`) used to run from
# /opt/padiem/oracle-mesh/kagent-src, a copy of this repository taken by hand on
# 11-01 that no deploy ever touched: #6889's kagent fix never reached the process
# that performs the reads, and the lane kept refusing `$` node ids. The tree is a
# commit directory now, with the PYTHONPATH path the unit already names pointing
# at it, the same shape P01 and B14 use.
#
# $1 the tree to copy from, $2 the release directory to build, $3 the tree to
# carry padiem_agent forward from.
stage_executor_code() {
  local source=$1 target=$2 preserve=$3
  [[ -d $source/apps/korean-ai-code-agent/src/kagent ]] \
    || { say "EXECUTOR_SOURCE_MISSING PATH=$source"; return 1; }
  command -v -- rsync >/dev/null 2>&1 || { say 'EXECUTOR_RSYNC_MISSING'; return 1; }
  install -d -m 0755 -- "$target" || return 1
  rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
    "$source/apps/korean-ai-code-agent/src/kagent/" "$target/kagent/" || return 1
  rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
    "$source/packages/padiem-ai-core/padiem_ai_core/" "$target/padiem_ai_core/" || return 1
  # padiem_agent is not tracked here. It is carried forward from the tree the
  # unit runs today; inventing one would be worse than keeping the last copy.
  if [[ -d $preserve/padiem_agent ]]; then
    rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
      "$preserve/padiem_agent/" "$target/padiem_agent/" || return 1
    say "EXECUTOR_PRESERVED=padiem_agent FROM=$preserve"
  else
    say 'EXECUTOR_PRESERVED=padiem_agent MISSING'
  fi
  chmod -R a+rX,go-w -- "$target" || return 1
  say "EXECUTOR_STAGED=$target"
}

# The link is the deployment. A directory the operator copied by hand is
# displaced, never deleted: it is the rollback copy.
link_executor_source() {
  local target=$1 displaced
  [[ -d $target ]] || { say "EXECUTOR_SOURCE_MISSING PATH=$target"; return 1; }
  if [[ ! -L $executor_src && -d $executor_src ]]; then
    displaced="${executor_src}.displaced-$(date +%Y%m%dT%H%M%S)"
    mv -- "$executor_src" "$displaced" || { say 'EXECUTOR_DISPLACE_FAILED'; return 1; }
    say "EXECUTOR_OPERATOR_COPY=$displaced"
  fi
  ln -sfn -- "$target" "$executor_src" || return 1
  say "EXECUTOR_LINK=$target"
}

# The executor is poll-only and has no listening port. Check the process systemd
# actually started rather than importing with the deploy script's Python, which
# need not have the service's venv or environment.
executor_process_alive() {
  local pid
  unit_active "$EXECUTOR_UNIT" || return 1
  pid=$("$systemctl_bin" show -p MainPID --value "$EXECUTOR_UNIT" 2>/dev/null) || return 1
  [[ $pid =~ ^[1-9][0-9]*$ ]]
}

# A module that imports cleanly can still die after the import. One traceback in
# the journal since this start is a verdict, never retried.
executor_no_traceback() {
  local since=$1 count
  count=$("$journalctl_bin" -u "$EXECUTOR_UNIT" --since "@$since" --no-pager 2>/dev/null \
    | grep -c 'Traceback (most recent call last)' || true)
  say "EXECUTOR_TRACEBACKS=${count:-0}"
  [[ ${count:-0} == 0 ]]
}

executor_rollback_source() {
  local candidate displaced
  displaced=$(ls -1dt "$executor_src".displaced-* 2>/dev/null | head -1 || true)
  for candidate in "$executor_releases/$old" "$displaced"; do
    [[ -n $candidate && -d $candidate ]] && { printf '%s' "$candidate"; return 0; }
  done
  return 1
}

# The link is the deployment, so the link is also the deployment evidence. 11-06
# 22:28 the executor rolled back to a displaced copy, the ops checkout still
# moved to that commit, and the empty old..new diff then skipped the executor:
# the process kept running code no deploy had installed (#7028). Compare what
# the unit actually runs, the way P01 does, instead of trusting the checkout.
#
# 0 the unit runs the commit this checkout recorded as deployed; 1 it runs
# something else, or that cannot be proven (missing, broken, unreadable); 2 no
# executor tree on this host, so there is nothing to compare.
executor_matches_previous_release() {
  local actual
  if [[ ! -L $executor_src && ! -e $executor_src ]]; then
    return 2
  fi
  [[ -L $executor_src ]] || return 1
  actual=$(readlink -f -- "$executor_src") || return 1
  [[ -d $actual ]] || return 1
  [[ $actual == "$executor_releases/$old" ]]
}

# Chat and B14 have the executor's shape: the link is the deployment. 11-07
# 05:38 the Chat unit rolled back to previous/7b638c11 while the checkout still
# moved to 80be22ee; only Chat's three changed files happened to select it. The
# running code is what a deploy must compare, never the checkout alone.
#
# 0 the link points at this checkout's recorded release; 1 another commit, a
# broken link, or a tree this script cannot prove; 2 no tree on this host.
chat_matches_previous_release() {
  local actual expected
  if [[ ! -L $chat_app && ! -e $chat_app ]]; then
    return 2
  fi
  [[ -L $chat_app ]] || return 1
  actual=$(readlink -f -- "$chat_app") || return 1
  [[ -d $actual ]] || return 1
  # Compare real paths on both sides, so the same mirror reached through
  # another symlinked root is that release, not an unprovable tree.
  expected=$(readlink -f -- "$source_stage_dir/$old/apps/padiem-chat/app" 2>/dev/null)
  [[ -n $expected ]] && [[ $actual == "$expected" ]] && return 0
  expected=$(readlink -f -- "$previous_dir/$old/apps/padiem-chat/app" 2>/dev/null)
  [[ -n $expected ]] && [[ $actual == "$expected" ]]
}

# The queue is a mirror, not a link: stage_queue_code rsyncs the tree into
# $queue_root, so "is the running copy this commit" can only be answered by
# comparing the files. Only the code the repository ships is compared — the
# root also holds runtime state (the database, queue.env, secrets, backups)
# that the deploy deliberately never touches. A file that is missing in the
# running copy, or differs, means the host is behind this commit.
queue_matches_target() {
  local actual temp item rel result=0 present=0
  actual=$(readlink -f -- "$queue_root") || return 1
  # A host with no mirror at all is "not installed", exactly like the other
  # services: the plan must not turn an absent tree into a redeploy of every
  # commit. Only a tree that holds some of the shipped files can be behind.
  [[ -d $actual ]] || return 2
  temp=$(mktemp -d) || return 1
  if ! "$git_bin" -C "$ops_checkout" archive "$resolved" apps/padiem-mesh-queue       | tar -x -C "$temp"; then
    rm -rf -- "$temp"
    return 1
  fi
  while IFS= read -r rel; do
    [[ -n $rel ]] || continue
    case "$rel" in
      # Tests, docs and the installer-managed root copies are not the running
      # service code; the deploy handles them separately.
      tests/*|*/tests/*|*.md|deploy/host-com2/*) continue ;;
    esac
    if [[ ! -f $actual/$rel ]]; then
      continue
    fi
    present=$((present + 1))
    if ! cmp -s -- "$temp/apps/padiem-mesh-queue/$rel" "$actual/$rel"; then
      say "QUEUE_RUNNING_CODE_DIFF=$rel"
      result=1
      break
    fi
  done < <(cd "$temp/apps/padiem-mesh-queue" && find . -type f -printf '%P
' 2>/dev/null)
  rm -rf -- "$temp"
  if (( result == 0 )) && (( present == 0 )); then
    return 2
  fi
  return "$result"
}

b14_matches_previous_release() {
  local actual expected
  if [[ ! -L $b14_app && ! -e $b14_app ]]; then
    return 2
  fi
  [[ -L $b14_app ]] || return 1
  actual=$(readlink -f -- "$b14_app") || return 1
  [[ -d $actual ]] || return 1
  expected=$(readlink -f -- "$source_stage_dir/$old/apps/korean-ai-platform" 2>/dev/null)
  [[ -n $expected ]] && [[ $actual == "$expected" ]] && return 0
  expected=$(readlink -f -- "$previous_dir/$old/apps/korean-ai-platform" 2>/dev/null)
  [[ -n $expected ]] && [[ $actual == "$expected" ]]
}

# The executor's unit was the one deployment input with no source in this
# repository: a change meant editing /etc/systemd/system by hand and nothing
# recorded what the host ran (#6892 follow-up). deploy/host-com2/oracle-mesh
# holds the example, and this step compares it with the installed unit. The
# installed unit may carry host settings this repository does not know, so the
# default is to report the drifting directives and change nothing; copying needs
# PADIEM_COM2_EXECUTOR_UNIT_SYNC=1. executor.env is never read or written.
EXECUTOR_UNIT_EXAMPLE=deploy/host-com2/oracle-mesh/padiem-oracle-mesh-executor.service.example

executor_unit_directives() {
  # $1 a unit file: one directive per line, sections and comments dropped, so a
  # moved block or a reworded comment is not drift.
  sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    -e '/^[#;]/d' -e '/^\[/d' -e '/^$/d' -- "$1"
}

executor_unit_drift_keys() {
  # $1 the example, $2 the installed unit: the directive names whose value
  # differs, or that only one side carries.
  local differing
  differing=$( { diff <(executor_unit_directives "$1" | sort) \
                     <(executor_unit_directives "$2" | sort) || true; } \
             | sed -n 's/^[<>][[:space:]]//p' ) || true
  printf '%s' "$differing" | cut -d= -f1 | sort -u | paste -sd, -
}

sync_executor_unit_file() {
  # $1 the staged tree, $2 the commit a backup is named after.
  local source=$1 sha=$2 example target drift
  example="$source/$EXECUTOR_UNIT_EXAMPLE"
  target="$executor_unit_dir/$EXECUTOR_UNIT"
  [[ -f $example ]] || { say 'EXECUTOR_UNIT_EXAMPLE=MISSING'; return 0; }
  if [[ ! -f $target ]]; then
    say 'EXECUTOR_UNIT_DRIFT=YES:NOT_INSTALLED'
  else
    if cmp -s -- "$example" "$target"; then
      say 'EXECUTOR_UNITS=SAME'
      return 0
    fi
    drift=$(executor_unit_drift_keys "$example" "$target")
    # An identical directive set with different bytes is layout or comments.
    say "EXECUTOR_UNIT_DRIFT=YES:${drift:-COMMENT_OR_LAYOUT}"
  fi
  if [[ $executor_unit_sync != 1 ]]; then
    say 'EXECUTOR_UNITS=CONFIRM_ONLY'
    return 0
  fi
  if [[ -e $target ]]; then
    # The copy this deploy replaces is the only way back; a re-run of the same
    # commit keeps the first backup.
    if [[ ! -e $target.bak-$sha ]]; then
      cp -p -- "$target" "$target.bak-$sha" \
        || { say 'EXECUTOR_UNIT_BACKUP_FAILED'; return 1; }
    fi
    # cp into an existing file keeps that file's mode and owner.
    cp -- "$example" "$target" || { say 'EXECUTOR_UNIT_COPY_FAILED'; return 1; }
  else
    install -m 0644 -- "$example" "$target" \
      || { say 'EXECUTOR_UNIT_COPY_FAILED'; return 1; }
  fi
  "$systemctl_bin" daemon-reload || { say 'EXECUTOR_UNIT_RELOAD_FAILED'; return 1; }
  say "EXECUTOR_UNITS=UPDATED:$EXECUTOR_UNIT"
}

restore_executor_unit_file() {
  # $1 the commit whose install is being rolled back. Only a deploy that copied
  # the unit has a backup to put back.
  local sha=$1 target="$executor_unit_dir/$EXECUTOR_UNIT"
  if [[ ! -f $target.bak-$sha ]]; then
    say 'EXECUTOR_UNITS_ROLLBACK=NONE'
    return 0
  fi
  if [[ -e $target ]]; then
    cp -- "$target.bak-$sha" "$target" \
      || { say 'EXECUTOR_UNIT_RESTORE_FAILED'; return 1; }
  else
    cp -p -- "$target.bak-$sha" "$target" \
      || { say 'EXECUTOR_UNIT_RESTORE_FAILED'; return 1; }
  fi
  "$systemctl_bin" daemon-reload || { say 'EXECUTOR_UNIT_ROLLBACK_RELOAD_FAILED'; return 1; }
  say "EXECUTOR_UNITS_ROLLBACK=RESTORED:$EXECUTOR_UNIT"
}

deploy_executor() {
  local target="$executor_releases/$resolved" preserve before_active=0 started
  if unit_running_or_restarting "$EXECUTOR_UNIT"; then before_active=1; fi
  with_service_stopped "$EXECUTOR_UNIT" EXECUTOR || return 1
  preserve=$(readlink -f -- "$executor_src" 2>/dev/null || true)
  stage_executor_code "$staged" "$target" "$preserve" || return 1
  link_executor_source "$target" || return 1
  assert_service_readable EXECUTOR_LIVE "$target" "$read_check_user" || return 1
  # Reported by default; only PADIEM_COM2_EXECUTOR_UNIT_SYNC=1 replaces the unit.
  sync_executor_unit_file "$staged" "$resolved" || return 1
  if (( before_active )); then
    started=$(date +%s)
    "$systemctl_bin" start "$EXECUTOR_UNIT" || return 1
    wait_unit_active EXECUTOR "$EXECUTOR_UNIT" || return 1
    wait_for_health EXECUTOR executor_process_alive || return 1
    executor_no_traceback "$started" || return 1
  else
    say 'EXECUTOR_START=SKIPPED_NOT_ACTIVE_BEFORE'
  fi
}

rollback_executor() {
  local target started
  with_service_stopped "$EXECUTOR_UNIT" EXECUTOR_ROLLBACK || return 1
  if target=$(executor_rollback_source); then
    link_executor_source "$target" || return 1
  else
    say 'EXECUTOR_ROLLBACK=NO_PREVIOUS_COPY'
    restore_executor_unit_file "$resolved" || return 1
    "$systemctl_bin" start "$EXECUTOR_UNIT" || return 1
    return 1
  fi
  # A deploy that copied the unit left the copy it replaced.
  restore_executor_unit_file "$resolved" || return 1
  started=$(date +%s)
  "$systemctl_bin" start "$EXECUTOR_UNIT" || return 1
  wait_unit_active EXECUTOR_ROLLBACK "$EXECUTOR_UNIT" || return 1
  wait_for_health EXECUTOR_ROLLBACK executor_process_alive || return 1
  executor_no_traceback "$started"
}


# The queue keeps its database, environment, venv and secrets on the host; only its
# code comes from the mirror, with the excludes its own installer uses.
stage_queue_code() {
  local source=$1
  [[ -d $source ]] || { say "QUEUE_SOURCE_MISSING PATH=$source"; return 1; }
  [[ -d $queue_root ]] || { say "QUEUE_ROOT_MISSING PATH=$queue_root"; return 1; }
  command -v -- rsync >/dev/null 2>&1 || { say 'QUEUE_RSYNC_MISSING'; return 1; }
    # The installer owns backup.sh, health_check.sh and provision_service_secret.sh
    # at the queue root (deploy/ in the tree). Excluding them keeps a code mirror
    # from deleting the files the backup and health units execute.
  rsync -a --delete \
    --exclude /src --exclude /pc-outputs --exclude venv --exclude '__pycache__' \
    --exclude '*.sqlite3*' --exclude 'queue.env' --exclude 'service-secret.txt' \
    --exclude 'ownership-map.json' --exclude 'watch-read-secret.txt' \
    --exclude /backup.sh --exclude /health_check.sh --exclude /provision_service_secret.sh \
    --exclude '*.bak-*' \
    "$source/" "$queue_root/" || return 1
  # The systemd health timer runs the installer-managed root-level copy.
  install -m 0755 "$queue_root/deploy/health_check.sh" "$queue_root/health_check.sh" || return 1
  # The rules the queue shares with Chat have one implementation: the modules are
  # linked into the mirror, never copied, exactly as the queue's installer does.
  ln -sfn "$staged/apps/padiem-chat/app" "$queue_root/app" || return 1
  ln -sfn "$staged/packages/padiem-ai-core/padiem_ai_core" "$queue_root/padiem_ai_core" || return 1
  ln -sfn "$staged/packages/padiem-control-plane/padiem_control_plane" \
    "$queue_root/padiem_control_plane" || return 1
  if [[ ${EUID} -eq 0 ]]; then
    chown -R -- "$queue_account" "$queue_root" 2>/dev/null || true
  fi
  say "QUEUE_STAGED=$source"
}

# install.sh owns four files the code mirror never writes: the queue's main unit,
# its health unit and timer, and provision_service_secret.sh. stage_queue_code
# excludes the installer's copies on purpose, so a change to any of them on main
# used to leave the installed file at whatever the last hand run wrote (#7012
# fixed health_check.sh the same way). State and environment files — queue.env,
# service-secret.txt, the database — are never read or written here.
queue_installer_target() {
  # $1 one name from QUEUE_INSTALLER_FILES; the installed path it belongs at.
  case "$1" in
    provision_service_secret.sh) printf '%s\n' "$queue_root/$1" ;;
    *) printf '%s\n' "$queue_unit_dir/$1" ;;
  esac
}

queue_unit_changed() {
  # $1 a queued installer file name. Only a unit needs a daemon-reload.
  case "$1" in
    *.service|*.timer) return 0 ;;
  esac
  return 1
}

sync_queue_installer_files() {
  # $1 the staged queue tree, $2 the commit a backup is named after.
  local source=$1 sha=$2 name path target mode
  local -a updated=()
  local reload=0
  for name in "${QUEUE_INSTALLER_FILES[@]}"; do
    path="$source/deploy/$name"
    target=$(queue_installer_target "$name")
    # A smaller operator tree simply does not carry the file.
    [[ -f $path ]] || continue
    if [[ -f $target ]] && cmp -s -- "$path" "$target"; then continue; fi
    if [[ -e $target ]]; then
      # The copy this deploy replaces is the only way back. The first backup of a
      # commit is the state before it was ever installed, so a re-run keeps it.
      if [[ ! -e $target.bak-$sha ]]; then
        cp -p -- "$target" "$target.bak-$sha" \
          || { say "QUEUE_UNITS_BACKUP_FAILED=$name"; return 1; }
      fi
      # cp into an existing file keeps that file's mode and owner.
      cp -- "$path" "$target" || { say "QUEUE_UNITS_COPY_FAILED=$name"; return 1; }
    else
      case $name in
        *.sh) mode=0755 ;;
        *) mode=0644 ;;
      esac
      install -m "$mode" -- "$path" "$target" \
        || { say "QUEUE_UNITS_COPY_FAILED=$name"; return 1; }
    fi
    updated+=("$name")
    if queue_unit_changed "$name"; then reload=1; fi
  done
  if (( reload )); then
    "$systemctl_bin" daemon-reload || { say 'QUEUE_UNITS_RELOAD_FAILED'; return 1; }
  fi
  if (( ${#updated[@]} )); then
    say "QUEUE_UNITS=UPDATED:$(IFS=,; printf '%s' "${updated[*]}")"
  else
    say 'QUEUE_UNITS=SAME'
  fi
}

restore_queue_installer_files() {
  # $1 the commit whose install is being rolled back. Only the files that deploy
  # replaced come back; one it created stays, because the host had none before.
  local sha=$1 name target restored=0 reload=0
  for name in "${QUEUE_INSTALLER_FILES[@]}"; do
    target=$(queue_installer_target "$name")
    [[ -f $target.bak-$sha ]] || continue
    if [[ -e $target ]]; then
      # Same rule as the copy: the installed mode and owner stay as they are.
      cp -- "$target.bak-$sha" "$target" \
        || { say "QUEUE_UNITS_RESTORE_FAILED=$name"; return 1; }
    else
      cp -p -- "$target.bak-$sha" "$target" \
        || { say "QUEUE_UNITS_RESTORE_FAILED=$name"; return 1; }
    fi
    restored=$((restored + 1))
    if queue_unit_changed "$name"; then reload=1; fi
  done
  if (( reload )); then
    "$systemctl_bin" daemon-reload || { say 'QUEUE_UNITS_ROLLBACK_RELOAD_FAILED'; return 1; }
  fi
  if (( restored )); then
    say "QUEUE_UNITS_ROLLBACK=RESTORED:$restored"
  else
    say 'QUEUE_UNITS_ROLLBACK=NONE'
  fi
}

queue_rollback_source() {
  local candidate
  for candidate in "$source_stage_dir/$old/apps/padiem-mesh-queue" \
                   "$previous_dir/$old/apps/padiem-mesh-queue"; do
    [[ -d $candidate ]] && { printf '%s' "$candidate"; return 0; }
  done
  return 1
}

deploy_queue() {
  local before_active=0
  if unit_running_or_restarting "$QUEUE_UNIT"; then before_active=1; fi
  with_service_stopped "$QUEUE_UNIT" QUEUE || return 1
  assert_service_readable QUEUE_SOURCE "$staged/apps/padiem-mesh-queue" "$queue_account" \
    || return 1
  stage_queue_code "$staged/apps/padiem-mesh-queue" || return 1
  # The units and the secret provisioner install.sh installs follow the same
  # commit as the code; only what differs is copied, and only a changed unit
  # reloads systemd.
  sync_queue_installer_files "$staged/apps/padiem-mesh-queue" "$resolved" || return 1
  # #6898's kit installs the backup script and its timer units from the mirror.
  # It never starts, enables or restarts anything and never opens the queue
  # database; running it here keeps the host's backup copy on the code that
  # just landed, right after the queue's own tree is staged.
  bash "$staged/deploy/host-com2/mesh-queue-backup/install.sh" --apply || return 1
  if (( before_active )); then
    "$systemctl_bin" start "$QUEUE_UNIT" || return 1
    wait_for_health QUEUE queue_health_ok bash "$queue_root/deploy/health_check.sh"
  else
    say 'QUEUE_START=SKIPPED_NOT_ACTIVE_BEFORE'
  fi
}

rollback_queue() {
  local source
  if source=$(queue_rollback_source); then
    with_service_stopped "$QUEUE_UNIT" QUEUE_ROLLBACK || return 1
    stage_queue_code "$source" || return 1
  else
    printf 'COM2_DEPLOY_QUEUE_ROLLBACK=MANUAL PREVIOUS=%s\n' "$previous_dir/$old" >&2
  fi
  # The forward run replaced the installer-owned files; put them back before the
  # unit starts on the previous code.
  restore_queue_installer_files "$resolved" || return 1
  if [[ -n $source ]]; then
    "$systemctl_bin" start "$QUEUE_UNIT" || return 1
    wait_for_health QUEUE_ROLLBACK queue_health_ok bash "$queue_root/deploy/health_check.sh"
    return
  fi
  "$systemctl_bin" start "$QUEUE_UNIT" || return 1
  wait_for_health QUEUE_ROLLBACK queue_health_ok bash "$queue_root/deploy/health_check.sh"
}

# Chat migrations used to stop the run and wait for an operator to apply them. The
# application applies them on start anyway, so the script now does what the operator
# did: one consistent backup beside the database, then exactly the files that were
# pending, as the database owner, with the same ledger the app writes.
#
# The two halves are deliberately split by who may read what. The object store of
# the operator checkout belongs to the account that fetched it, and this script runs
# under `umask 077`: on 2026-11-03 a pack index written that way left the database
# owner unable to read a single git object, and git reported the migration file as
# missing (`safe.directory` cannot help an unreadable object). So the SQL is read
# here, by the account that fetched it, and only the bytes of one migration are
# handed to the process that writes the database — which still runs as the database
# owner, so the ledger and the file ownership stay exactly as the app leaves them.
apply_pending_chat_migrations() {
  local pending=$1 backup stamp name sql
  local -a as_user=() applied=()
  stamp=$(date +%Y%m%dT%H%M%S)
  backup="$chat_db.pre-deploy-$stamp"
  if [[ -e $backup ]]; then
    say "CHAT_MIGRATION_BACKUP=EXISTS PATH=$backup"
    return 1
  fi
  if [[ -n $chat_db_user && ${EUID} -eq 0 ]] && getent passwd -- "$chat_db_user" >/dev/null 2>&1; then
    as_user=(runuser -u "$chat_db_user" --)
  fi
  if ! "${as_user[@]}" "$python_bin" - "$chat_db" "$backup" <<'PY'
import sqlite3
import sys

db, backup = sys.argv[1:3]
con = sqlite3.connect(db, isolation_level=None)
dst = sqlite3.connect(backup)
con.backup(dst)
dst.close()
integrity = con.execute("PRAGMA integrity_check").fetchone()
con.close()
if not integrity or integrity[0] != "ok":
    print("COM2_DEPLOY_CHAT_MIGRATION_BACKUP=INTEGRITY_FAIL")
    sys.exit(1)
print("COM2_DEPLOY_CHAT_MIGRATION_BACKUP=%s" % backup)
PY
  then
    return 1
  fi
  # shellcheck disable=SC2086  # the pending names arrive newline-separated
  for name in $pending; do
    if ! sql=$("$git_bin" -C "$ops_checkout" show \
        "$resolved:apps/padiem-chat/migrations/$name"); then
      say "CHAT_MIGRATION_READ_FAILED NAME=$name"
      return 1
    fi
    if ! printf '%s\n' "$sql" | "${as_user[@]}" "$python_bin" -c '
import sqlite3
import sys
from datetime import datetime, timezone

db, name = sys.argv[1], sys.argv[2]
sql = sys.stdin.read()
if not sql.strip():
    print("COM2_DEPLOY_CHAT_MIGRATION=EMPTY NAME=%s" % name)
    raise SystemExit(1)
con = sqlite3.connect(db, isolation_level=None)
con.executescript(sql)
con.execute(
    "INSERT OR REPLACE INTO padiem_local_migration_ledger (name, applied_at) VALUES (?, ?)",
    (name, datetime.now(timezone.utc).isoformat()),
)
con.close()
print("COM2_DEPLOY_CHAT_MIGRATION_APPLIED_ONE=%s" % name)
' "$chat_db" "$name"; then
      say "CHAT_MIGRATION_APPLY_FAILED NAME=$name"
      return 1
    fi
    applied+=("$name")
  done
  if (( ${#applied[@]} == 0 )); then
    printf 'COM2_DEPLOY_CHAT_MIGRATION=NONE\n'
    return 1
  fi
  printf 'COM2_DEPLOY_CHAT_MIGRATION_APPLIED=%s\n' "$(IFS=,; printf '%s' "${applied[*]}")"
  return 0
}

# The installers restart a unit only when it was active before the install. A unit
# the operator left enabled but stopped therefore received the new code and never
# came up, and the health gate rolled it back (B14, 2026-11-01). Nothing moves until
# every selected unit is enabled, and an enabled-but-stopped one is started and
# health-checked here. A unit waiting out RestartSec is already coming up: the
# deploy stops it and starts it again, so starting it a second time here only
# adds a window for that pending restart to interleave.
ensure_unit_ready() {
  local label=$1 unit=$2
  shift 2
  if ! "$systemctl_bin" is-enabled --quiet "$unit"; then
    say "UNIT_ENABLED_${label}=NO UNIT=$unit"
    return 1
  fi
  if unit_running_or_restarting "$unit"; then
    say "UNIT_READY_${label}=ACTIVE"
    return 0
  fi
  say "UNIT_READY_${label}=STARTING UNIT=$unit"
  "$systemctl_bin" start "$unit" || return 1
  wait_for_health "PRE_${label}" "$@" || return 1
  say "UNIT_READY_${label}=STARTED"
}

# $1 the comma-separated list the diff selected.
ensure_target_units_ready() {
  local service probe_root
  probe_root=$ops_checkout
  [[ -d $source_stage_dir/$resolved ]] && probe_root=$source_stage_dir/$resolved
  for service in ${1//,/ }; do
    case $service in
      chat) ensure_unit_ready CHAT "$CHAT_UNIT" \
        "$python_bin" "$probe_root/deploy/host-com2/chat/health.py" --url "$chat_health_url" ;;
      p01) ensure_unit_ready P01 "$P01_UNIT" \
        "$python_bin" "$probe_root/deploy/host-com2/p01/health.py" --url "$p01_health_url" ;;
      b14) ensure_unit_ready B14 "$B14_UNIT" \
        "$python_bin" "$probe_root/deploy/host-com2/b14/health.py" --url "$b14_health_url" ;;
      queue) ensure_unit_ready QUEUE "$QUEUE_UNIT" \
        queue_health_ok bash "$queue_root/deploy/health_check.sh" ;;
      # Probed by its own active state: the import check for a tree that is
      # about to be replaced says nothing about this run.
      executor) ensure_unit_ready EXECUTOR "$EXECUTOR_UNIT" ;;
    esac || fail "UNIT_NOT_READY_${service}"
  done
}

# Installers this deploy never runs. Each one copies files onto the host, so a
# change to the repository leaves the installed copy behind until someone runs
# that installer by hand — the silence #6892 was about. This reads and reports
# only: nothing is copied, reloaded or restarted, and a difference never changes
# the deploy result.
#
# The cron lane renders its unit files from templates with the profile's values,
# so those are not comparable byte for byte; the scripts it copies are. Its app
# root is the production profile's app root, not the installer's staging default.
report_sidecar_drift() {
  local service relative installed entry name listing='' count=0
  local -a pairs=(
    "file-lane|deploy/host-com2/file-lane/check_config.py|/opt/padiem/file-lane/check_config.py"
    "file-lane|deploy/host-com2/file-lane/health.py|/opt/padiem/file-lane/health.py"
    "file-lane|deploy/host-com2/file-lane/padiem-file-lane.service|/etc/systemd/system/padiem-file-lane.service"
    "boot-recovery|deploy/host-com2/boot-recovery/wsl/boot_recovery.py|/opt/padiem/boot-recovery/boot_recovery.py"
    "boot-recovery|deploy/host-com2/boot-recovery/wsl/boot-recovery.sh|/opt/padiem/boot-recovery/boot-recovery.sh"
    "boot-recovery|deploy/host-com2/boot-recovery/wsl/padiem-boot-recovery.service|/etc/systemd/system/padiem-boot-recovery.service"
    "connector-watch|deploy/host-com2/connector-watch/connector_watch_host.py|/opt/padiem/connector-watch/connector_watch_host.py"
    "connector-watch|.github/scripts/connector_lane_watch.py|/opt/padiem/connector-watch/connector_lane_watch.py"
    "connector-watch|deploy/host-com2/connector-watch/padiem-connector-watch.service|/etc/systemd/system/padiem-connector-watch.service"
    "connector-watch|deploy/host-com2/connector-watch/padiem-connector-watch.timer|/etc/systemd/system/padiem-connector-watch.timer"
    "offsite-backup|deploy/host-com2/offsite-backup/offsite.py|/opt/padiem/offsite-backup/offsite.py"
    "offsite-backup|deploy/host-com2/offsite-backup/padiem-offsite-backup.service|/etc/systemd/system/padiem-offsite-backup.service"
    "offsite-backup|deploy/host-com2/offsite-backup/padiem-offsite-backup.timer|/etc/systemd/system/padiem-offsite-backup.timer"
    "cron|deploy/host-com2/cron/run-cron.sh|/opt/padiem/chat-com2/run-cron.sh"
    "cron|deploy/host-com2/cron/run-expired-purge.sh|/opt/padiem/chat-com2/run-expired-purge.sh"
    "cron|deploy/host-com2/cron/status-cron.sh|/opt/padiem/chat-com2/status-cron.sh"
    "cron|deploy/host-com2/cron/check_config_cron.py|/opt/padiem/chat-com2/check_config_cron.py"
    "cron|deploy/host-com2/cron/README.md|/opt/padiem/chat-com2/README-cron.md"
  )
  [[ -n $staged ]] || { say 'AUX_DRIFT=UNKNOWN'; return 0; }
  # The restart drop-in is one file the installer writes for every listed unit.
  if [[ -f $staged/deploy/host-com2/restart-policy/units.txt ]]; then
    while IFS= read -r name; do
      pairs+=("restart-policy|deploy/host-com2/restart-policy/10-padiem-restart.conf|/etc/systemd/system/$name.d/padiem-restart.conf")
    done < <(grep -vE '^[[:space:]]*(#|$)' \
      "$staged/deploy/host-com2/restart-policy/units.txt" 2>/dev/null || true)
  fi
  for entry in "${pairs[@]}"; do
    service=${entry%%|*}
    relative=${entry#*|}
    installed=$aux_root${relative#*|}
    relative=${relative%%|*}
    # A smaller operator tree simply does not carry the file.
    [[ -f $staged/$relative ]] || continue
    # The installed path relative to its root: one drop-in per unit, so the
    # basename alone would name ten identical entries.
    name=${installed#"$aux_root"}
    name=${name#/}
    if [[ ! -e $installed ]]; then
      listing+="${listing:+,}${service}:${name}=NOT_INSTALLED"
    elif cmp -s -- "$staged/$relative" "$installed"; then
      continue
    else
      listing+="${listing:+,}${service}:${name}"
    fi
    count=$((count + 1))
  done
  if (( count )); then
    say "AUX_DRIFT=$listing"
  else
    say 'AUX_DRIFT=NONE'
  fi
  return 0
}

run_deploy() {

  local sha=$1 origin changed='' services='' pending='' line status=0
  local mapped='' service='' reason='' state='' unit='' queue_dependent='' executor_dependent=''
  local mismatch=0 p01_mismatch=0 excluded_test=0 excluded_docs=0 excluded_example=0 excluded_meta=0 excluded_unmapped=0
  local executor_mismatch=0 executor_code=0
  local chat_mismatch=0 chat_code=0 b14_mismatch=0 b14_code=0
  local queue_mismatch=0 queue_code=0
  local deploy_script_changed=0
  declare -A wanted=([chat]=0 [p01]=0 [b14]=0 [queue]=0 [executor]=0)
  declare -A reason_files=([chat]=0 [p01]=0 [b14]=0 [queue]=0 [executor]=0)
  declare -A result=([chat]=SKIP [p01]=SKIP [b14]=SKIP [queue]=SKIP [executor]=SKIP)

  "$git_bin" -C "$ops_checkout" fetch --quiet origin main || fail GIT_FETCH_FAILED
  origin=$("$git_bin" -C "$ops_checkout" rev-parse origin/main) || fail GIT_FETCH_FAILED
  resolved=$("$git_bin" -C "$ops_checkout" rev-parse --verify --quiet "$sha^{commit}") \
    || fail SHA_UNKNOWN
  [[ $resolved == "$origin" ]] || fail SHA_NOT_ORIGIN_MAIN
  old=$("$git_bin" -C "$ops_checkout" rev-parse HEAD) || fail GIT_FAILED

  say "MODE=$(if ((stage_only)); then echo STAGE_ONLY; elif ((apply)); then echo APPLY; else echo DRY_RUN; fi)"
  say "SHA=$resolved"
  say "PREVIOUS=$old"
  # Reported, never fatal: the checkout itself is no longer an install source.
  if assert_service_readable CHECKOUT "$ops_checkout/apps/padiem-chat/app" "$read_check_user"; then
    say 'CHECKOUT_SOURCE=READABLE'
  else
    say 'CHECKOUT_SOURCE=NOT_SERVICE_READABLE_USES_MIRROR'
  fi
  if (( stage_only )); then
    verify_staged_source
    say "SUMMARY=stage:PASS"
    return 0
  fi

  # Reported, never fatal: an import list this script cannot read must not
  # stop a deploy, but a silent SKIP is the bug the list exists to end.
  if queue_dependent=$(queue_import_closure "$resolved" 2>/dev/null); then
    say "QUEUE_IMPORT_CLOSURE_FILES=$(printf '%s\n' "$queue_dependent" | awk 'NF{n++} END{print n+0}')"
  else
    queue_dependent=''
    say 'QUEUE_IMPORT_CLOSURE=UNKNOWN'
  fi
  if executor_dependent=$(executor_import_closure "$resolved" 2>/dev/null); then
    say "EXECUTOR_IMPORT_CLOSURE_FILES=$(printf '%s\n' "$executor_dependent" | awk 'NF{n++} END{print n+0}')"
  else
    executor_dependent=''
    say 'EXECUTOR_IMPORT_CLOSURE=UNKNOWN'
  fi

  if p01_matches_target; then
    say 'P01_RUNNING_CODE=MATCH'
  else
    say 'P01_RUNNING_CODE=DIFF_OR_UNVERIFIABLE'
    wanted[p01]=1
    p01_mismatch=1
  fi

  # A rollback the next deploy cannot see is the same defect as no deploy at
  # all: the checkout records the commit, the process runs the copy before it.
  executor_code=0
  executor_matches_previous_release || executor_code=$?
  case $executor_code in
    0) say 'EXECUTOR_RUNNING_CODE=MATCH' ;;
    2) say 'EXECUTOR_RUNNING_CODE=NOT_INSTALLED' ;;
    *)
      say 'EXECUTOR_RUNNING_CODE=DIFF_OR_UNVERIFIABLE'
      wanted[executor]=1
      executor_mismatch=1
      ;;
  esac

  # Same rule for the two services whose rollback is a link: a rollback the next
  # plan cannot see stays rolled back when the next commit misses their paths.
  chat_code=0
  chat_matches_previous_release || chat_code=$?
  case $chat_code in
    0) say 'CHAT_RUNNING_CODE=MATCH' ;;
    2) say 'CHAT_RUNNING_CODE=NOT_INSTALLED' ;;
    *)
      say 'CHAT_RUNNING_CODE=DIFF_OR_UNVERIFIABLE'
      wanted[chat]=1
      chat_mismatch=1
      ;;
  esac

  b14_code=0
  b14_matches_previous_release || b14_code=$?
  case $b14_code in
    0) say 'B14_RUNNING_CODE=MATCH' ;;
    2) say 'B14_RUNNING_CODE=NOT_INSTALLED' ;;
    *)
      say 'B14_RUNNING_CODE=DIFF_OR_UNVERIFIABLE'
      wanted[b14]=1
      b14_mismatch=1
      ;;
  esac

  # Same rule for the queue: its mirror is rsynced, so a rollback or a stale
  # copy cannot be seen through the checkout diff alone. Without this the plan
  # read queue:SKIP reason_files=0 whenever the checkout already sat at the
  # target, even though the running tree was behind.
  queue_code=0
  queue_matches_target || queue_code=$?
  case $queue_code in
    0) say 'QUEUE_RUNNING_CODE=MATCH' ;;
    2) say 'QUEUE_RUNNING_CODE=NOT_INSTALLED' ;;
    *)
      say 'QUEUE_RUNNING_CODE=DIFF_OR_UNVERIFIABLE'
      wanted[queue]=1
      queue_mismatch=1
      ;;
  esac

  # The diff base must be the code the host is running, not "whatever the ops
  # checkout HEAD happens to be". A dry run, an operator checkout or an earlier
  # run of the SAME sha leaves HEAD at $resolved; the diff is then empty and
  # every service reads reason_files=0 / NO_DEPLOY_PATHS even when the host is
  # still behind. Measured 2026-11-09: a #7243 plan printed p01:SKIP
  # reason_files=0 for exactly this reason. Fall back to the last applied sha,
  # then to the parent commit, and say which base was used.
  diff_base=$old
  if [[ $diff_base == "$resolved" ]]; then
    if [[ -s $state_dir/last_applied_sha ]]; then
      candidate=$(tr -d '\r\n' < "$state_dir/last_applied_sha") || candidate=''
      if [[ -n $candidate ]] \
        && "$git_bin" -C "$ops_checkout" rev-parse --verify --quiet "$candidate^{commit}" >/dev/null; then
        diff_base=$candidate
        say 'DIFF_BASE=LAST_APPLIED_SHA'
      fi
    fi
    if [[ $diff_base == "$resolved" ]]; then
      say 'DIFF_BASE=CHECKOUT_AT_TARGET'
    fi
  fi
  say "DIFF_BASE_SHA=$diff_base"

  changed=$("$git_bin" -C "$ops_checkout" diff --name-only "$diff_base" "$resolved") \
    || fail GIT_DIFF_FAILED
  while IFS= read -r line; do
    [[ -n $line ]] || continue
    say "CHANGED=$line"
    if [[ $line == deploy/host-com2/deploy_from_main.sh ]]; then
      deploy_script_changed=1
    fi
    if reason=$(deploy_path_exclusion "$line"); then
      case "$reason" in
        TEST_DIRECTORY|TEST_FILE) excluded_test=$((excluded_test + 1)) ;;
        DOCUMENTATION) excluded_docs=$((excluded_docs + 1)) ;;
        EXAMPLE_CONFIG) excluded_example=$((excluded_example + 1)) ;;
        REPO_META) excluded_meta=$((excluded_meta + 1)) ;;
      esac
      say "EXCLUDED=$line reason=$reason"
      continue
    fi
    mapped=$(service_for_path "$line")
    if [[ -z $mapped ]]; then
      excluded_unmapped=$((excluded_unmapped + 1))
      say "EXCLUDED=$line reason=NO_SERVICE_MAPPING"
      continue
    fi
    for service in $mapped; do
      case "$service" in
        chat|p01|b14|queue|executor)
          wanted[$service]=1
          reason_files[$service]=$((reason_files[$service] + 1))
          ;;
        *) fail INVALID_SERVICE_PATH_MAPPING ;;
      esac
    done
    # A module the queue imports selects it even when the path maps elsewhere:
    # the Chat tree and the shared packages are linked into the queue root.
    if [[ -n $queue_dependent ]] && (( ! wanted[queue] )) \
      && grep -Fqx -- "$line" <<<"$queue_dependent"; then
      wanted[queue]=1
      reason_files[queue]=$((reason_files[queue] + 1))
      say "QUEUE_IMPORTED=$line"
    fi
    # The executor stages kagent and the Core modules kagent imports, so the
    # same rule decides it: a path that maps elsewhere can still be its code.
    if [[ -n $executor_dependent ]] && (( ! wanted[executor] )) \
      && grep -Fqx -- "$line" <<<"$executor_dependent"; then
      wanted[executor]=1
      reason_files[executor]=$((reason_files[executor] + 1))
      say "EXECUTOR_IMPORTED=$line"
    fi
  done <<<"$changed"

  say "EXCLUDED_COUNTS=tests:$excluded_test docs:$excluded_docs env_example:$excluded_example repo_meta:$excluded_meta unmapped:$excluded_unmapped"
  for line in chat p01 b14 queue executor; do
    if (( wanted[$line] )); then
      services+="${services:+,}$line"
    fi
    state=SKIP
    reason=NO_DEPLOY_PATHS
    if (( wanted[$line] )); then
      state=REDEPLOY
      reason=CHANGED_PATHS
    fi
    mismatch=0
    case $line in
      p01) mismatch=$p01_mismatch ;;
      executor) mismatch=$executor_mismatch ;;
      chat) mismatch=$chat_mismatch ;;
      b14) mismatch=$b14_mismatch ;;
      queue) mismatch=$queue_mismatch ;;
    esac
    if (( mismatch )); then
      if (( reason_files[$line] )); then
        reason=CHANGED_PATHS+RUNNING_CODE_MISMATCH
      else
        reason=RUNNING_CODE_MISMATCH
      fi
    fi
    say "DECISION_${line^^}=$state reason_files=${reason_files[$line]} reason=$reason"
  done
  say "SERVICES=${services:-none}"
  # Reported only, and only when planning: the deploy does not judge from this.
  if (( ! apply )); then
    for line in chat p01 b14 queue executor; do
      case $line in
        chat) unit=$CHAT_UNIT ;;
        p01) unit=$P01_UNIT ;;
        b14) unit=$B14_UNIT ;;
        queue) unit=$QUEUE_UNIT ;;
        executor) unit=$EXECUTOR_UNIT ;;
      esac
      say "UNIT_STATE_${line^^}=$(unit_state "$unit")"
    done
  fi
  if [[ $old == "$resolved" ]] && [[ -z $services ]]; then
    say 'NOOP=YES'
    say 'SUMMARY=chat:SKIP p01:SKIP b14:SKIP queue:SKIP executor:SKIP'
    return 0
  fi

  status=0
  pending=$(pending_migrations) || status=$?
  if (( status != 0 )); then
    if (( status == 4 )); then
      if (( apply )); then fail CHAT_DB_UNREADABLE; fi
    elif (( apply )); then
      fail MIGRATION_CHECK_FAILED
    fi
    pending='__UNKNOWN__'
  fi
  if [[ $pending == '__UNKNOWN__' ]]; then
    say 'PENDING_MIGRATIONS=UNKNOWN'
  elif [[ -n $pending ]]; then
    say "PENDING_MIGRATIONS=$(printf '%s' "$pending" | paste -sd, -)"
    if (( apply )); then
      apply_pending_chat_migrations "$pending" || fail CHAT_MIGRATION_APPLY_FAILED
    else
      printf 'COM2_DEPLOY_MIGRATION_FIRST=YES\n' >&2
      printf '마이그레이션 먼저: %s\n' "$(printf '%s' "$pending" | paste -sd' ' -)" >&2
      printf 'COM2_DEPLOY=STOP\nCOM2_DEPLOY_REASON=MIGRATION_FIRST\n' >&2
      exit 3
    fi
  else
    say 'PENDING_MIGRATIONS=none'
  fi

  # Test/docs-only and unrelated changes must not move the production checkout
  # or mirrored source tree when no service was selected. The deploy script is
  # the exception: the next plan reads this checkout, so until it moves the host
  # keeps planning with the old script and a fix to the script itself never
  # reaches production (11-07: #7055's running-code comparison stayed unused).
  if [[ -z $services ]]; then
    if (( deploy_script_changed )); then
      if (( apply )); then
        move_checkout_to_target
        say 'CHECKOUT_ONLY=YES reason=DEPLOY_SCRIPT_CHANGED'
        say 'SUMMARY=chat:SKIP p01:SKIP b14:SKIP queue:SKIP executor:SKIP'
        return 0
      fi
      say 'CHECKOUT_ONLY=WOULD reason=DEPLOY_SCRIPT_CHANGED'
      printf '적용하면 체크아웃만 새 SHA로 넘어가고, 다음 계획부터 새 스크립트가 쓰입니다.\n'
    fi
    say 'NO_SERVICE_CHANGES=YES'
    say 'SUMMARY=chat:SKIP p01:SKIP b14:SKIP queue:SKIP executor:SKIP'
    return 0
  fi

  # Check the required QA capability before touching the checkout or services.
  # The operator can explicitly select --ai-check=warn on the next run.
  if (( apply )) && [[ $ai_check == required ]] && {
      [[ -z ${B66_CGI_ALPHA_USERNAME:-} ]] || [[ -z ${B66_CGI_ALPHA_PASSWORD:-} ]];
  }; then
    printf '%s\n' 'COM2_DEPLOY_AI_CHECK=REQUIRED_UNAVAILABLE' \
      'COM2_DEPLOY_AI_CHECK_ACTION=RERUN_WITH_CREDENTIALS_OR_EXPLICIT_WARN' >&2
    fail AI_CHECK_REQUIRED_CREDENTIALS_MISSING
  fi

  if ! (( apply )); then
    for line in chat p01 b14 queue executor; do
      if (( wanted[$line] )); then result[$line]=WOULD_DEPLOY; fi
    done
    say "SUMMARY=chat:${result[chat]} p01:${result[p01]} b14:${result[b14]} queue:${result[queue]} executor:${result[executor]}"
    return 0
  fi

  ensure_target_units_ready "$services"

  move_checkout_to_target

  # Nothing above touched a service; from here the host is being changed, so the
  # mirror and its permissions must already be proven.
  verify_staged_source

  local failed=0 ai_status=SKIP ai_code=none ai_output
  declare -A was_active=([chat]=0 [p01]=0 [b14]=0 [queue]=0 [executor]=0)
  for line in chat p01 b14 queue executor; do
    if (( ! wanted[$line] )); then continue; fi
    case "$line" in
      chat) if unit_running_or_restarting "$CHAT_UNIT"; then was_active[chat]=1; fi ;;
      p01) if unit_running_or_restarting "$P01_UNIT"; then was_active[p01]=1; fi ;;
      b14) if unit_running_or_restarting "$B14_UNIT"; then was_active[b14]=1; fi ;;
      queue) if unit_running_or_restarting "$QUEUE_UNIT"; then was_active[queue]=1; fi ;;
      executor) if unit_running_or_restarting "$EXECUTOR_UNIT"; then was_active[executor]=1; fi ;;
    esac
    if "deploy_$line"; then
      result[$line]=PASS
    elif "rollback_$line"; then
      result[$line]=ROLLBACK
      failed=1
    else
      result[$line]=ROLLBACK_FAILED
      failed=1
    fi
  done

  tools_serialization=SKIP
  if (( ! failed )) && [[ ${result[chat]} == PASS ]] && [[ -x "$chat_venv_python" ]]; then
    # The service's exact runtime: installed app root + its EnvironmentFile,
    # with the chat venv interpreter. ERROR (harness mismatch) continues the
    # deploy with a warning; FAIL (real serialization defect) stops it.
    tools_out=$("$chat_venv_python" "$staged/.github/scripts/post_deploy_tool_serialization_check.py" \
      --app-root "$chat_root" --env-file "$chat_env_file" 2>/dev/null) || true
    say "$tools_out"
    # #7155's check prints TOOLS_SERIALIZATION_ENV_FILE=... BEFORE the verdict.
    # Matching the raw multi-line output against a leading PASS*/FAIL* pattern
    # therefore never matched and every result became tools_serialization:ERROR
    # (measured on the 10th release, main c523d06a). Read the last bounded
    # verdict line instead; no verdict line means the check itself did not run.
    tools_verdict=$(printf '%s\n' "$tools_out" \
      | grep -E '^TOOLS_SERIALIZATION=(PASS|FAIL|ERROR)([[:space:]]|$)' \
      | tail -n 1 || true)
    case "$tools_verdict" in
      TOOLS_SERIALIZATION=PASS*) tools_serialization=PASS ;;
      TOOLS_SERIALIZATION=FAIL*) tools_serialization=FAIL; failed=1 ;;
      TOOLS_SERIALIZATION=ERROR*) tools_serialization=ERROR ;;
      *) tools_serialization=ERROR; say 'TOOLS_SERIALIZATION_ERROR=no_verdict_line' ;;
    esac
  fi

  if (( ! failed )); then
    ai_status=FAIL
    ai_code=ai_check_unavailable
    if ai_output=$("$python_bin" "$staged/.github/scripts/post_deploy_ai_answer_check.py" --base-url "$ai_base_url" 2>/dev/null); then
      if [[ $ai_output == 'ai:PASS' ]]; then ai_status=PASS; ai_code=none; fi
    elif [[ $ai_output =~ ^ai:FAIL\ error_code=([a-z][a-z0-9_]{0,80})$ ]]; then
      ai_code=${BASH_REMATCH[1]}
    fi
    # Two codes are raised before the check sends its request: no QA identity on
    # this host, or a base URL the canary refuses to sign in against. Nothing was
    # measured, so under --ai-check=warn the line says SKIP with the reason. On
    # 11-03 the run ended APPLY_EXIT=0 with "ai:FAIL error_code=qa_credential_missing",
    # which reads as a broken answer lane when the answer was never tried. Any code
    # from a check that did run (empty_answer, entitlement_unavailable,
    # qa_login_refused, ...) stays FAIL, and --ai-check=required keeps failing on
    # every code — there the operator asked for the guarantee, not the warning.
    if [[ $ai_status == FAIL && $ai_check == warn ]]; then
      case $ai_code in
        qa_credential_missing|invalid_chat_origin) ai_status=SKIP ;;
      esac
    fi
    if [[ $ai_status == FAIL && $ai_check == required ]]; then
      failed=1
      for line in queue b14 p01 chat; do
        [[ ${result[$line]} == PASS ]] || continue
        if (( ! was_active[$line] )); then
          result[$line]=ROLLBACK_REQUIRED
        elif "rollback_$line"; then
          result[$line]=ROLLBACK
        else
          result[$line]=ROLLBACK_FAILED
        fi
      done
    fi
  fi
  local ai_word="ai:$ai_status"
  if [[ $ai_status == FAIL ]]; then
    ai_word="ai:FAIL error_code=$ai_code"
  elif [[ $ai_status == SKIP && $ai_code != none ]]; then
    ai_word="ai:SKIP reason=$ai_code"
  fi
  # Reported only: an installer this run does not call may be behind the code.
  report_sidecar_drift || true
  say "SUMMARY=chat:${result[chat]} p01:${result[p01]} b14:${result[b14]} queue:${result[queue]} executor:${result[executor]} tools_serialization:$tools_serialization $ai_word"
  if (( extended_smoke )); then
    "$python_bin" "$staged/deploy/host-com2/post_deploy_smoke.py" \
      --base-url "$ai_base_url" --chat-db "$chat_db" \
      --ai-status "$ai_status" --ai-code "${ai_code:-none}" || true
  fi
  if (( failed )); then exit 1; fi
  return 0
}

if [[ "${BASH_SOURCE[0]:-}" == "$0" ]]; then
  main "$@"
fi
