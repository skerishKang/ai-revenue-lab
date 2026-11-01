#!/usr/bin/env bash
# Standard COM2 deployment after the 2026-10-31 cutover: merging to main no
# longer reaches the host by itself.
#
#   bash deploy_from_main.sh <main-sha>             plan only (the default)
#   bash deploy_from_main.sh <main-sha> --apply     move, reinstall, restart, health
#
# The production checkout is an operator setting, never a shared folder. The
# script refuses a SHA that is not origin/main, a checkout that is the staging
# checkout, a dirty tracked tree, a Chat database it cannot read, and a new
# migration — which it never applies by itself.
#
# It never edits .env or any secret, never touches Cloudflare, the tunnel or the
# Windows 18731 release, and never enables a unit.
#
# Configuration (environment; every path is the operator's, none is guessed):
#   PADIEM_COM2_OPS_CHECKOUT     production checkout (required)
#   PADIEM_COM2_STAGING_CHECKOUT staging checkout to stay apart (default below)
#   PADIEM_COM2_STATE_DIR        private execution state (default below)
#   PADIEM_COM2_PREVIOUS_DIR     root-owned, service-readable rollback worktrees
#   PADIEM_COM2_CHAT_HEALTH_ATTEMPTS / PADIEM_COM2_CHAT_HEALTH_INTERVAL
#   PADIEM_COM2_CHAT_HEALTH_TIMEOUT
#   PADIEM_COM2_CHAT_DB          Chat SQLite file holding the migration ledger
#   PADIEM_COM2_P01_APP          P01 install root (#6442 releases/rollback)
#   PADIEM_COM2_B14_APP          B14 app checkout
#   PADIEM_COM2_SYSTEMCTL        systemctl wrapper
#   PADIEM_COM2_PYTHON           python3
#   PADIEM_COM2_GIT              git
#   B66_CGI_ALPHA_USERNAME / B66_CGI_ALPHA_PASSWORD  existing QA account
#   PADIEM_COM2_AI_CHECK_BASE_URL  target Chat origin (default https://chat.padiem.net)
#   COM2_CHAT_HEALTH_URL / COM2_P01_HEALTH_URL / COM2_B14_HEALTH_URL
set -euo pipefail
umask 077

ops_checkout=${PADIEM_COM2_OPS_CHECKOUT:-}
staging_checkout=${PADIEM_COM2_STAGING_CHECKOUT:-/mnt/d/work/ai-revenue-lab-staging-chat}
state_dir=${PADIEM_COM2_STATE_DIR:-/var/lib/padiem-com2-deploy}
previous_dir=${PADIEM_COM2_PREVIOUS_DIR:-/opt/padiem/com2-deploy/previous}
chat_health_attempts=${PADIEM_COM2_CHAT_HEALTH_ATTEMPTS:-31}
chat_health_interval=${PADIEM_COM2_CHAT_HEALTH_INTERVAL:-2}
chat_health_timeout=${PADIEM_COM2_CHAT_HEALTH_TIMEOUT:-60}
chat_db=${PADIEM_COM2_CHAT_DB:-/mnt/d/padiem/chat-com2/chat.sqlite3}
p01_root=${PADIEM_COM2_P01_APP:-/opt/padiem/p01}
b14_app=${PADIEM_COM2_B14_APP:-/opt/padiem/b14/app}
systemctl_bin=${PADIEM_COM2_SYSTEMCTL:-systemctl}
python_bin=${PADIEM_COM2_PYTHON:-python3}
git_bin=${PADIEM_COM2_GIT:-git}
chat_health_url=${PADIEM_COM2_CHAT_HEALTH_URL:-http://127.0.0.1:8798/health}
p01_health_url=${PADIEM_COM2_P01_HEALTH_URL:-http://127.0.0.1:8811/internal/v1/health}
b14_health_url=${PADIEM_COM2_B14_HEALTH_URL:-http://127.0.0.1:8789/health}
apply=0
ai_check=warn
extended_smoke=0
ai_base_url=${PADIEM_COM2_AI_CHECK_BASE_URL:-https://chat.padiem.net}
requested=''
resolved=''
old=''

CHAT_UNIT=padiem-chat-com2.service
P01_UNIT=padiem-p01.service
B14_UNIT=padiem-b14.service

fail() { printf 'COM2_DEPLOY=STOP\nCOM2_DEPLOY_REASON=%s\n' "$1" >&2; exit "${2:-2}"; }
say() { printf 'COM2_DEPLOY_%s\n' "$*"; }

usage() {
  cat >&2 <<'USAGE'
usage: deploy_from_main.sh <main-sha> [--apply] [--dry-run]
       [--ops-checkout PATH] [--state-dir PATH] [--chat-db PATH] [--ai-check=required|warn] [--smoke]
USAGE
}

parse_args() {
  while (($#)); do
    case "$1" in
      --apply) apply=1; shift ;;
      --dry-run) apply=0; shift ;;
      --smoke) extended_smoke=1; shift ;;
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

# The script moves the checkout it lives in, and bash keeps reading this file as
# it runs. Execute an immutable copy from the state directory instead.
main() {
  parse_args "$@"
  if [[ -n ${PADIEM_COM2_DEPLOY_REEXEC_COPY:-} ]]; then
    # This process is the immutable copy; remove it when the run ends.
    trap 'rm -f -- "$PADIEM_COM2_DEPLOY_REEXEC_COPY"' EXIT
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
  if (( apply )); then
    [[ $(uname -s) == Linux ]] || fail LINUX_REQUIRED
    [[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
    command -v -- "$systemctl_bin" >/dev/null 2>&1 || fail SYSTEMD_MISSING
  fi
  run_deploy "$requested"
}

# Which services a changed path belongs to. Shared P01 dependencies are also
# checked against its live release by p01_matches_target below.
service_for_path() {
  case "$1" in
    apps/padiem-chat/*|apps/padiem-council-apps/static/*|packages/*|deploy/host-com2/chat/*) echo chat ;;
    apps/padiem-ai-engine/*|deploy/host-com2/p01/*) echo p01 ;;
    apps/korean-ai-platform/*|deploy/host-com2/b14/*) echo b14 ;;
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

with_service_stopped() {
  local unit=$1
  if unit_active "$unit"; then "$systemctl_bin" stop "$unit" || return 1; fi
}

# Retry the real probe while the listener and app are starting. Every attempt
# must still pass the full health contract; STATUS=0 is not a success.
wait_chat_health() {
  local source=$1 attempt deadline remaining pause
  [[ $chat_health_attempts =~ ^[1-9][0-9]*$ && $chat_health_interval =~ ^[0-9]+$ && $chat_health_timeout =~ ^[1-9][0-9]*$ ]] || return 1
  deadline=$((SECONDS + chat_health_timeout))
  for ((attempt=1; attempt<=chat_health_attempts; attempt++)); do
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || return 1
    if timeout "${remaining}s" "$python_bin" "$source/deploy/host-com2/chat/health.py" --url "$chat_health_url"; then
      return 0
    fi
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || return 1
    if (( attempt < chat_health_attempts )); then
      pause=$chat_health_interval
      if (( pause > remaining )); then pause=$remaining; fi
      sleep "$pause"
    fi
  done
  return 1
}

# stage_code.sh copies these exact paths into the release selected by app.
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

deploy_chat() {
  local before_active=0
  if unit_active "$CHAT_UNIT"; then before_active=1; fi
  with_service_stopped "$CHAT_UNIT" || return 1
  bash "$ops_checkout/deploy/host-com2/chat/install.sh" \
    --apply --source-root "$ops_checkout" || return 1
  if (( before_active )); then
    "$systemctl_bin" start "$CHAT_UNIT" || return 1
    wait_chat_health "$ops_checkout"
  else
    say 'CHAT_START=SKIPPED_NOT_ACTIVE_BEFORE'
  fi
}

deploy_p01() {
  local before_active=0
  if unit_active "$P01_UNIT"; then before_active=1; fi
  with_service_stopped "$P01_UNIT" || return 1
  bash "$ops_checkout/deploy/host-com2/p01/install.sh" \
    --apply --source-root "$ops_checkout" || return 1
  if (( before_active )); then
    "$systemctl_bin" start "$P01_UNIT" || return 1
    "$python_bin" "$ops_checkout/deploy/host-com2/p01/health.py" --url "$p01_health_url"
  else
    say 'P01_START=SKIPPED_NOT_ACTIVE_BEFORE'
  fi
}

deploy_b14() {
  local before_active=0
  if unit_active "$B14_UNIT"; then before_active=1; fi
  with_service_stopped "$B14_UNIT" || return 1
  bash "$ops_checkout/deploy/host-com2/b14/install.sh" --reload || return 1
  if (( before_active )); then
    "$systemctl_bin" start "$B14_UNIT" || return 1
    "$python_bin" "$ops_checkout/deploy/host-com2/b14/health.py" --url "$b14_health_url"
  else
    say 'B14_START=SKIPPED_NOT_ACTIVE_BEFORE'
  fi
}

# Chat's live links point into a checkout, so its rollback is the previous
# checkout itself.
rollback_chat() {
  local previous="$previous_dir/$old"
  [[ -d $previous/deploy/host-com2/chat ]] || { say 'CHAT_ROLLBACK=NO_PREVIOUS_CHECKOUT'; return 1; }
  with_service_stopped "$CHAT_UNIT" || return 1
  bash "$previous/deploy/host-com2/chat/install.sh" \
    --apply --source-root "$previous" || return 1
  "$systemctl_bin" start "$CHAT_UNIT" || return 1
  wait_chat_health "$previous"
}

# P01's own installer snapshots the replaced app (#6442); rollback re-points the
# release link at that snapshot, exactly as deploy/host-com2/p01/README.md says.
rollback_p01() {
  local snapshot
  snapshot=$(ls -1dt "$p01_root"/rollback/p01.* 2>/dev/null | head -1 || true)
  [[ -n $snapshot ]] || { say 'P01_ROLLBACK=NO_SNAPSHOT'; return 1; }
  with_service_stopped "$P01_UNIT" || return 1
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
  "$python_bin" "$ops_checkout/deploy/host-com2/p01/health.py" --url "$p01_health_url"
}

# B14 code is an operator-staged checkout. When it is a link this script can
# restore it; when it is a copy the operator owns the rollback, and the script
# says so instead of guessing.
rollback_b14() {
  local previous="$previous_dir/$old/apps/korean-ai-platform"
  if [[ -L $b14_app ]]; then
    with_service_stopped "$B14_UNIT" || return 1
    ln -sfnT "$previous" "$b14_app" || return 1
    "$systemctl_bin" start "$B14_UNIT" || return 1
    "$python_bin" "$ops_checkout/deploy/host-com2/b14/health.py" --url "$b14_health_url"
    return
  fi
  printf 'COM2_DEPLOY_B14_ROLLBACK=MANUAL PREVIOUS=%s\n' "$previous" >&2
  return 1
}

run_deploy() {
  local sha=$1 origin changed='' services='' pending='' line status=0
  declare -A wanted=([chat]=0 [p01]=0 [b14]=0) result=([chat]=SKIP [p01]=SKIP [b14]=SKIP)

  "$git_bin" -C "$ops_checkout" fetch --quiet origin main || fail GIT_FETCH_FAILED
  origin=$("$git_bin" -C "$ops_checkout" rev-parse origin/main) || fail GIT_FETCH_FAILED
  resolved=$("$git_bin" -C "$ops_checkout" rev-parse --verify --quiet "$sha^{commit}") \
    || fail SHA_UNKNOWN
  [[ $resolved == "$origin" ]] || fail SHA_NOT_ORIGIN_MAIN
  old=$("$git_bin" -C "$ops_checkout" rev-parse HEAD) || fail GIT_FAILED

  say "MODE=$(if ((apply)); then echo APPLY; else echo DRY_RUN; fi)"
  say "SHA=$resolved"
  say "PREVIOUS=$old"

  if p01_matches_target; then
    say 'P01_RUNNING_CODE=MATCH'
  else
    say 'P01_RUNNING_CODE=DIFF_OR_UNVERIFIABLE'
    wanted[p01]=1
  fi
  if [[ $old == "$resolved" ]] && (( ! wanted[p01] )); then
    say 'NOOP=YES'
    say 'SUMMARY=chat:SKIP p01:SKIP b14:SKIP'
    return 0
  fi

  changed=$("$git_bin" -C "$ops_checkout" diff --name-only "$old" "$resolved") \
    || fail GIT_DIFF_FAILED
  while IFS= read -r line; do
    [[ -n $line ]] || continue
    say "CHANGED=$line"
    case "$(service_for_path "$line")" in
      chat) wanted[chat]=1 ;;
      p01) wanted[p01]=1 ;;
      b14) wanted[b14]=1 ;;
    esac
  done <<<"$changed"
  for line in chat p01 b14; do
    if (( wanted[$line] )); then services+="${services:+,}$line"; fi
  done
  say "SERVICES=${services:-none}"

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
    printf 'COM2_DEPLOY_MIGRATION_FIRST=YES\n' >&2
    printf '마이그레이션 먼저: %s\n' "$(printf '%s' "$pending" | paste -sd' ' -)" >&2
    printf 'COM2_DEPLOY=STOP\nCOM2_DEPLOY_REASON=MIGRATION_FIRST\n' >&2
    exit 3
  else
    say 'PENDING_MIGRATIONS=none'
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
    for line in chat p01 b14; do
      if (( wanted[$line] )); then result[$line]=WOULD_DEPLOY; fi
    done
    say "SUMMARY=chat:${result[chat]} p01:${result[p01]} b14:${result[b14]}"
    return 0
  fi

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

  local failed=0 ai_status=SKIP ai_code=none ai_output
  declare -A was_active=([chat]=0 [p01]=0 [b14]=0)
  for line in chat p01 b14; do
    if (( ! wanted[$line] )); then continue; fi
    case "$line" in
      chat) if unit_active "$CHAT_UNIT"; then was_active[chat]=1; fi ;;
      p01) if unit_active "$P01_UNIT"; then was_active[p01]=1; fi ;;
      b14) if unit_active "$B14_UNIT"; then was_active[b14]=1; fi ;;
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

  if (( ! failed )); then
    ai_status=FAIL
    ai_code=ai_check_unavailable
    if ai_output=$("$python_bin" "$ops_checkout/.github/scripts/post_deploy_ai_answer_check.py" --base-url "$ai_base_url" 2>/dev/null); then
      if [[ $ai_output == 'ai:PASS' ]]; then ai_status=PASS; ai_code=none; fi
    elif [[ $ai_output =~ ^ai:FAIL\ error_code=([a-z][a-z0-9_]{0,80})$ ]]; then
      ai_code=${BASH_REMATCH[1]}
    fi
    if [[ $ai_status == FAIL && $ai_check == required ]]; then
      failed=1
      for line in b14 p01 chat; do
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
  if [[ $ai_status == FAIL ]]; then
    say "SUMMARY=chat:${result[chat]} p01:${result[p01]} b14:${result[b14]} ai:FAIL error_code=$ai_code"
  else
    say "SUMMARY=chat:${result[chat]} p01:${result[p01]} b14:${result[b14]} ai:$ai_status"
  fi
  if (( extended_smoke )); then
    "$python_bin" "$ops_checkout/deploy/host-com2/post_deploy_smoke.py" \
      --base-url "$ai_base_url" --chat-db "$chat_db" \
      --ai-status "$ai_status" --ai-code "${ai_code:-none}" || true
  fi
  if (( failed )); then exit 1; fi
  return 0
}

if [[ "${BASH_SOURCE[0]:-}" == "$0" ]]; then
  main "$@"
fi
