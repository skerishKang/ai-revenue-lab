#!/usr/bin/env bash
# Installs only the COM2 Chat parallel host package/units. Never starts or
# enables anything; never touches chat.padiem.net, its tunnel, or its Worker.
set -euo pipefail
umask 077
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_root=$(cd -- "$here/../../.." && pwd)
apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1; shift ;;
    --dry-run) apply=0; shift ;;
    --source-root) source_root=${2:?source root required}; shift 2 ;;
    *) echo 'CHAT_COM2_INSTALL=INVALID_ARGUMENT' >&2; exit 2 ;;
  esac
done
app=/opt/padiem/chat-com2
data=/mnt/d/padiem/chat-com2
unit=padiem-chat-com2.service
if (( ! apply )); then
  printf '%s\n' 'CHAT_COM2_INSTALL=DRY_RUN' "APP_ROOT=$app" "DATA_ROOT=$data" "UNIT=$unit" 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'TUNNEL_CHANGE=NO'
  exit 0
fi
fail() { echo "CHAT_COM2_INSTALL=$1" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
for required in \
  apps/padiem-chat/app/local_cpython.py \
  apps/padiem-chat/static/councillor/councillor.html \
  apps/padiem-council-apps/static/index.html \
  apps/padiem-council-apps/static/council-app.css \
  apps/padiem-council-apps/static/council-app.js \
  apps/padiem-chat/migrations \
  packages/padiem-ai-core/padiem_ai_core \
  packages/padiem-auth-verify/verify.py \
  packages/padiem-control-plane/padiem_control_plane \
  apps/korean-ai-code-agent/src/kagent \
  apps/padiem-ai-engine/clients/python/padiem_ai_engine_client; do
  [[ -e "$source_root/$required" ]] || fail SOURCE_MISSING
done
mountpoint -q /mnt/d || fail HDD_NOT_MOUNTED
if systemctl is-active --quiet "$unit"; then fail STOP_CHAT_COM2_BEFORE_UPDATE; fi
install -d -m 0755 "$app"
if ! getent passwd padiem-chat >/dev/null; then
  useradd --system --user-group --home-dir "$app" --shell /usr/sbin/nologin padiem-chat
fi
install -d -m 0700 -o padiem-chat -g padiem-chat "$data"
if [[ ! -x "$app/venv/bin/python" ]]; then (umask 022; python3 -m venv "$app/venv"); fi
(umask 022; "$app/venv/bin/python" -m pip --isolated install --index-url https://pypi.org/simple --disable-pip-version-check --require-hashes -r "$here/requirements.txt")
# The modules stay single-source: the service imports the same checkout the
# Worker and the tests use, through symlinks (never a drifting copy).
for pair in \
  "app:$source_root/apps/padiem-chat/app" \
  "padiem_ai_core:$source_root/packages/padiem-ai-core/padiem_ai_core" \
  "padiem_control_plane:$source_root/packages/padiem-control-plane/padiem_control_plane" \
  "padiem_auth_verify.py:$source_root/packages/padiem-auth-verify/verify.py" \
  "com2_edge_proof.py:$source_root/packages/padiem-control-plane/com2_edge_proof.py" \
  "kagent:$source_root/apps/korean-ai-code-agent/src/kagent" \
  "padiem_ai_engine_client:$source_root/apps/padiem-ai-engine/clients/python/padiem_ai_engine_client"; do
  link=${pair%%:*}; target=${pair#*:}
  ln -sfn "$target" "$app/$link"
done
install -m 0644 "$here/check_config.py" "$app/check_config.py"
install -m 0755 "$here/health.py" "$app/health.py"
install -m 0700 "$here/backup.py" "$app/backup.py"
if [[ ! -e "$app/.env" ]]; then install -m 0600 "$here/.env.example" "$app/.env"; fi
chown root:root "$app/.env"
chmod 0600 "$app/.env"
if ! runuser -u padiem-chat -- env "PADIEM_CHAT_LOCAL_DATA_DIR=$data" "$app/venv/bin/python" -c \
  "import os, pathlib, tempfile, uvicorn; fd, name=tempfile.mkstemp(dir=os.environ['PADIEM_CHAT_LOCAL_DATA_DIR']); os.close(fd); pathlib.Path(name).unlink()" >/dev/null 2>&1; then
  fail RUNTIME_OR_HDD_PERMISSION_FAILED
fi
# Prove the service user can import the app BEFORE systemd is asked to start it.
if ! (cd "$app" && runuser -u padiem-chat -- "$app/venv/bin/python" -c \
  "import app.local_cpython, app.local_cron"); then
  fail SERVICE_IMPORT_FAILED
fi
for unit_file in \
  padiem-chat-com2.service \
  padiem-chat-com2-health.service padiem-chat-com2-health.timer \
  padiem-chat-com2-backup.service padiem-chat-com2-backup.timer; do
  install -m 0644 "$here/$unit_file" "/etc/systemd/system/$unit_file"
done
systemctl daemon-reload
printf '%s\n' 'CHAT_COM2_INSTALL=PASS' 'START_SERVICE=NO' 'ENABLE_SERVICE=NO' 'TUNNEL_CHANGE=NO'
