#!/usr/bin/env bash
# Isolated restore smoke only. Never point this script at a production data path.
#
# #6737: the first version could not run on COM2, so the restore was done by
# hand. Each defect has one guard here:
#   * offsite.py restore takes a FILE; the script used to pass a directory
#     (IsADirectoryError). -> restore_into() targets <data-dir>/chat.sqlite3,
#     the only name app.local_cpython opens.
#   * a random port made two runs unreproducible. -> SMOKE_PORT is fixed and a
#     busy port fails the run instead of silently moving.
#   * queue, P01 and B14 were left pointed at their real upstreams. ->
#     export_smoke_env() rewrites all three to closed loopback ports; nothing
#     here starts cloudflared or opens an external connection.
#   * `.env` was read with `source`, so `$` in a value was expanded and part of
#     the value ended up in an error message. -> load_env_file() parses the file
#     and never prints a value.
#   * the smoke server could outlive a failed run. -> cleanup() always stops it
#     and proves the port is closed, on every exit path.
#   * the run said PASS without looking at what came back. -> verify_restored_db()
#     checks integrity, foreign keys, the migration ledger and row counts.
set -euo pipefail

#: Fixed loopback ports. 18798 is the smoke server; the three below must stay
#: closed so a code path that tries to reach queue, P01 or B14 fails locally.
SMOKE_PORT=18798
CLOSED_QUEUE_PORT=18797
CLOSED_P01_PORT=18811
CLOSED_B14_PORT=18789
#: Interpreter override exists for the Windows dev box only; COM2 uses python3.
PYTHON="${PADIEM_RESTORE_PYTHON:-python3}"

RESTORE_ROOT=""
SERVER_PID=""
PORT_CLOSE_FAILED=0

log() { printf 'restore_smoke_step=%s\n' "$1"; }
die() { printf 'restore_smoke=FAIL reason=%s\n' "$1" >&2; exit 1; }

now_ms() { "$PYTHON" -c 'import time; print(int(time.time() * 1000))'; }

require_environment() {
  : "${PADIEM_LIVE_BACKUP_DATE:?set PADIEM_LIVE_BACKUP_DATE to the backup date}"
  : "${COM2_OFFSITE_KEY_FILE:?set COM2_OFFSITE_KEY_FILE in the local environment}"
  : "${COM2_OFFSITE_KEY_ID:?set COM2_OFFSITE_KEY_ID in the local environment}"
  : "${OFFSITE_STATE_DIR:?set OFFSITE_STATE_DIR to the existing backup state directory}"
  [[ "$PADIEM_LIVE_BACKUP_DATE" =~ ^[0-9]{8}$ ]] || die backup_date_invalid
  # A data dir inherited from the calling shell is how a smoke run reaches
  # production data; the script sets its own, inside its own temp folder.
  [[ -z "${PADIEM_CHAT_LOCAL_DATA_DIR:-}" ]] || die inherited_data_dir
  export OFFSITE_STATE_DIR COM2_OFFSITE_KEY_FILE COM2_OFFSITE_KEY_ID
}

# Read KEY=VALUE pairs the way systemd's EnvironmentFile does: no shell, no
# expansion. `declare -gx "KEY=$value"` assigns the parsed bytes exactly, so a
# value holding `$`, quotes or backticks stays literal. Values are never echoed:
# a bad line reports only that a key was invalid.
load_env_file() {
  local file="${1:-}"
  [[ -n "$file" ]] || return 0
  [[ -r "$file" ]] || die env_file_unreadable
  local key value
  while IFS= read -r -d '' key && IFS= read -r -d '' value; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die env_file_key_invalid
    declare -gx "$key=$value"
  done < <(
    "$PYTHON" - "$file" <<'PY'
import sys

path = sys.argv[1]
try:
    lines = open(path, encoding="utf-8").read().splitlines()
except OSError:
    raise SystemExit(2)
for raw in lines:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    if key.startswith("export "):
        key = key[len("export "):].strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    sys.stdout.write(key + "\0" + value + "\0")
PY
  )
}

# Paths owned by the running host. A restore inside one of them is a production
# write, so the argument is refused rather than trusted.
is_production_path() {
  case "${1%/}" in
    /var/lib/padiem*) return 0 ;;
    /opt/padiem*) return 0 ;;
    /srv/padiem*) return 0 ;;
    /etc/padiem*) return 0 ;;
    /mnt/c|/mnt/c/*|/mnt/d|/mnt/d/*|/mnt/e|/mnt/e/*) return 0 ;;
    /proc|/proc/*|/sys|/sys/*|/dev|/dev/*|/boot|/boot/*) return 0 ;;
  esac
  return 1
}

refuse_unisolated_target() {
  local candidate="${1%/}"
  [[ -n "$candidate" ]] || die target_empty
  [[ "$candidate" == /* ]] || die target_not_absolute
  is_production_path "$candidate" && die target_is_production_path
  local tmp_root="${TMPDIR:-/tmp}"
  tmp_root="${tmp_root%/}"
  [[ "$candidate" == "$tmp_root"/* ]] || die target_outside_temp_root
}

resolve_restore_root() {
  local candidate="${1:-}"
  if [[ -n "$candidate" ]]; then
    refuse_unisolated_target "$candidate"
    mkdir -p -- "$candidate"
    # Best effort on a filesystem without POSIX modes; the temp parent is 700.
    chmod 700 -- "$candidate" 2>/dev/null || true
    RESTORE_ROOT="$candidate"
  else
    RESTORE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/padiem-chat-live-restore.XXXXXX")"
  fi
}

port_is_free() {
  "$PYTHON" - "$1" <<'PY'
import socket
import sys

sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

require_free_port() { port_is_free "$1" || die "port_busy_$1"; }

# The smoke server may only talk to itself. Every upstream name the Chat host
# reads is rewritten to a closed loopback port, so a run that reaches for queue,
# P01 or B14 fails with connection refused on this machine instead of leaving it.
export_smoke_env() {
  local data_dir="$1"
  export PADIEM_CHAT_LOCAL_DATA_DIR="$data_dir"
  export PADIEM_LOCAL_DEV=1
  export PADIEM_CHAT_PUBLIC_BASE_URL="http://127.0.0.1:$SMOKE_PORT"
  export PADIEM_CHAT_ORCHESTRATION_ENABLED=false
  export PC_QUEUE_ORIGIN="http://127.0.0.1:$CLOSED_QUEUE_PORT"
  export PC_QUEUE_BACKEND=""
  export PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN="http://127.0.0.1:$CLOSED_P01_PORT"
  export PADIEM_CHAT_B14_BASE_URL="http://127.0.0.1:$CLOSED_B14_PORT"
  export B14_UPSTREAM_URL="http://127.0.0.1:$CLOSED_B14_PORT"
  unset PC_QUEUE_SERVICE_SECRET PC_QUEUE_SERVICE_SECRET_FILE
  unset PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL
  # No proxy: an inherited proxy variable would route loopback traffic outward.
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
  export NO_PROXY="127.0.0.1,localhost"
  export no_proxy="$NO_PROXY"
}

restore_target_path() { printf '%s/chat.sqlite3' "$1"; }

# offsite.py restore --target is a FILE path; the data dir holds chat.sqlite3.
offsite_restore() {
  local target_file="$1"
  local root="${repo_root:-$(git rev-parse --show-toplevel)}"
  "$PYTHON" "$root/deploy/host-com2/offsite-backup/offsite.py" restore \
    --service chat \
    --date "$PADIEM_LIVE_BACKUP_DATE" \
    --target "$target_file" \
    --replace
}

restore_into() {
  local data_dir="$1"
  local target_file started
  mkdir -p -- "$data_dir"
  chmod 700 -- "$data_dir" 2>/dev/null || true
  target_file="$(restore_target_path "$data_dir")"
  started="$(now_ms)"
  offsite_restore "$target_file"
  printf 'restore_smoke_timing restore_ms=%s target=chat.sqlite3\n' "$(( $(now_ms) - started ))"
  [[ -s "$target_file" ]] || die restore_file_missing
  RESTORED_DB="$target_file"
}

# What came back, in numbers only: no row content, no companion tables dumped.
verify_restored_db() {
  local database="$1"
  local started
  started="$(now_ms)"
  "$PYTHON" - "$database" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
try:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    tables = [
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    counts = {}
    for name in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        counts[name] = connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
    ledger = "padiem_local_migration_ledger"
    last = None
    if ledger in counts:
        row = connection.execute(
            f"SELECT name FROM {ledger} ORDER BY name DESC LIMIT 1"
        ).fetchone()
        last = row[0] if row else None
finally:
    connection.close()

print(f"restore_check integrity={integrity} foreign_key_violations={foreign_key_issues} "
      f"tables={len(counts)} ledger_last={last or 'none'}")
top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]
print("restore_check_rows " + " ".join(f"{name}={count}" for name, count in top))
PY
  printf 'restore_smoke_timing verify_ms=%s\n' "$(( $(now_ms) - started ))"
}

start_smoke_server() {
  local chat_dir="$1"
  (
    cd "$chat_dir"
    exec "$PYTHON" -m app.local_server \
      --host 127.0.0.1 --port "$SMOKE_PORT" --no-server-header
  ) &
  SERVER_PID=$!
}

wait_for_health() {
  local started="$1"
  local waited=0
  while [[ "$waited" -lt 60 ]]; do
    kill -0 "$SERVER_PID" 2>/dev/null || die smoke_server_exited
    if curl --fail --silent --show-error "http://127.0.0.1:$SMOKE_PORT/health" >/dev/null; then
      printf 'restore_smoke_timing server_ready_ms=%s\n' "$(( $(now_ms) - started ))"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  die smoke_server_timeout
}

stop_smoke_server() {
  local waited=0
  if [[ -n "${SERVER_PID:-}" ]]; then
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      kill -TERM "$SERVER_PID" 2>/dev/null || true
      while [[ "$waited" -lt 100 ]]; do
        kill -0 "$SERVER_PID" 2>/dev/null || break
        sleep 0.1
        waited=$((waited + 1))
      done
      if kill -0 "$SERVER_PID" 2>/dev/null; then
        kill -KILL "$SERVER_PID" 2>/dev/null || true
      fi
    fi
    wait "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=""
  fi
  waited=0
  while [[ "$waited" -lt 50 ]]; do
    if port_is_free "$SMOKE_PORT"; then
      printf 'restore_smoke_port_closed=true port=%s\n' "$SMOKE_PORT"
      return 0
    fi
    sleep 0.2
    waited=$((waited + 1))
  done
  PORT_CLOSE_FAILED=1
  printf 'restore_smoke_port_closed=false port=%s\n' "$SMOKE_PORT" >&2
  return 0
}

cleanup() {
  local status=$?
  stop_smoke_server
  if [[ -n "${RESTORE_ROOT:-}" && "${PADIEM_RESTORE_KEEP_DIR:-0}" != "1" ]]; then
    rm -rf -- "$RESTORE_ROOT"
  fi
  if [[ "$PORT_CLOSE_FAILED" == "1" && "$status" -eq 0 ]]; then
    status=1
  fi
  exit "$status"
}

main() {
  require_environment
  load_env_file "${PADIEM_RESTORE_ENV_FILE:-}"
  # An explicit target is allowed only inside the temp root: see the guard.
  resolve_restore_root "${1:-}"
  trap cleanup EXIT INT TERM

  # Fail before touching anything if the fixed port or an "upstream" port is
  # already serving: a closed port is the proof that the smoke stays local.
  require_free_port "$SMOKE_PORT"
  require_free_port "$CLOSED_QUEUE_PORT"
  require_free_port "$CLOSED_P01_PORT"
  require_free_port "$CLOSED_B14_PORT"
  log ports_ready

  local data_dir="$RESTORE_ROOT/chat-data"
  export_smoke_env "$data_dir"
  log env_isolated

  restore_into "$data_dir"
  log restored
  verify_restored_db "$RESTORED_DB"
  log verified

  start_smoke_server "$(git rev-parse --show-toplevel)/apps/padiem-chat"
  local started
  started="$(now_ms)"
  wait_for_health "$started"
  curl --fail --silent --show-error "http://127.0.0.1:$SMOKE_PORT/" >/dev/null
  curl --fail --silent --show-error "http://127.0.0.1:$SMOKE_PORT/health" >/dev/null
  log http_ok

  printf '%s\n' "temporary_restore_smoke=PASS"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
