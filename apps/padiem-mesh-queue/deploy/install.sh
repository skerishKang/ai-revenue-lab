#!/bin/bash
# #5881 follow-on — put the 컴2 PC queue service on its feet.
#
# Orderly and re-runnable: material first (the files the service refuses to start
# without), then code, then the environment, then the units, then one read-only
# health check. It changes nothing about the Chat Worker: after this run the queue
# is installed and unused, which is the intended state until the Owner switches
# PC_QUEUE_BACKEND.
set -uo pipefail

ROOT=/opt/padiem/mesh-queue
REPO=${PADIEM_REPO:-/opt/padiem/oracle-mesh/repo}
CHAT_SRC=$REPO/apps/padiem-chat
QUEUE_SRC=$REPO/apps/padiem-mesh-queue
ACCOUNT=padiem-mesh
CHANNEL_SECRET_FILE=/opt/padiem/oracle-mesh/channel-secret.txt

echo "== material (never created empty: an absent file is reported, not guessed)"
[ -s "$ROOT/service-secret.txt" ] || echo "MESH_QUEUE_STEP=service_secret_missing"
[ -s "$CHANNEL_SECRET_FILE" ] || echo "MESH_QUEUE_STEP=channel_secret_missing"
[ -s "$ROOT/ownership-map.json" ] || echo "MESH_QUEUE_STEP=ownership_map_missing"

echo "== account"
id -u "$ACCOUNT" >/dev/null 2>&1 || useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin "$ACCOUNT"

echo "== code"
mkdir -p "$ROOT"
# backup.sh runs as the service user and writes into /opt/padiem/backups, which the host
# owns as root. Without this directory already being the service user's, every VACUUM
# INTO lands nowhere and the lane reports `MESH_QUEUE_BACKUP=FAILED reason=no-file`.
install -d -m 0700 -o "$ACCOUNT" -g "$ACCOUNT" /opt/padiem/backups/mesh-queue
# The queue's source may be a worktree checked out under $ROOT/src/. `--delete`
# would otherwise eat the very tree it is copying from on a re-run, so that worktree is
# excluded from deletion and any nested source outside it is refused. The source sits at
# $ROOT/src/apps/padiem-mesh-queue when PADIEM_REPO is the worktree, so the rule is the
# worktree prefix, not one exact directory.
case "$QUEUE_SRC/" in
  "$ROOT/src/"*) ;;
  "$ROOT/"*) echo "MESH_QUEUE_STEP=source_nested_refused"; exit 1 ;;
esac
rsync -a --delete \
  --exclude /src --exclude venv --exclude '__pycache__' --exclude '*.sqlite3*' \
  --exclude 'queue.env' --exclude 'service-secret.txt' --exclude 'ownership-map.json' \
  --exclude 'watch-read-secret.txt' \
  "$QUEUE_SRC/" "$ROOT/"
# The modules the queue imports are linked, not copied: app/, padiem_ai_core/ and
# padiem_control_plane/ stay the source of truth the Worker and the tests use, so a
# deployed queue cannot be running last week's copy of a rule it shares with Chat.
ln -sfn "$CHAT_SRC/app" "$ROOT/app"
ln -sfn "$REPO/packages/padiem-ai-core/padiem_ai_core" "$ROOT/padiem_ai_core"
ln -sfn "$REPO/packages/padiem-control-plane/padiem_control_plane" "$ROOT/padiem_control_plane"

echo "== environment"
# The read-only watch leg (#82) is optional at install time: with no file the queue
# simply keeps the channel-secret-only behaviour, and the monitor's own install hands
# that file later. An empty line in an EnvironmentFile is ignored, so absence is
# expressed by leaving the slot empty rather than by a second template.
# #5573 follow-up: a re-run must not undo a retirement decision. The value already in
# queue.env wins; a fresh install writes today's behaviour ("on").
LEGACY_MAP_LANE=$(grep -s '^MESH_QUEUE_LEGACY_MAP_LANE=' "$ROOT/queue.env" 2>/dev/null | cut -d= -f2)
LEGACY_MAP_LANE=${LEGACY_MAP_LANE:-on}
# Same rule for the store door's arrival log: a re-install must not turn off an instrument
# someone switched on for a cutover window. Absence is today's behaviour ("off").
REQUEST_LOG=$(grep -s '^MESH_QUEUE_REQUEST_LOG=' "$ROOT/queue.env" 2>/dev/null | cut -d= -f2)
REQUEST_LOG=${REQUEST_LOG:-off}
WATCH_LINE=""
if [ -s "$ROOT/watch-read-secret.txt" ]; then
  WATCH_LINE="MESH_QUEUE_WATCH_READ_SECRET_FILE=$ROOT/watch-read-secret.txt"
  echo "MESH_QUEUE_STEP=watch_secret_present"
else
  echo "MESH_QUEUE_STEP=watch_secret_absent_readonly_leg_refused"
fi
cat > "$ROOT/queue.env" <<ENV
MESH_QUEUE_DB_PATH=$ROOT/queue.sqlite3
MESH_QUEUE_CHANNEL_SECRET_FILE=$CHANNEL_SECRET_FILE
MESH_QUEUE_OWNERSHIP_MAP_FILE=$ROOT/ownership-map.json
MESH_QUEUE_SERVICE_SECRET_FILE=$ROOT/service-secret.txt
MESH_QUEUE_LEGACY_MAP_LANE=$LEGACY_MAP_LANE
MESH_QUEUE_REQUEST_LOG=$REQUEST_LOG
$WATCH_LINE
MESH_QUEUE_EXECUTION_MODE=mesh
PYTHONPATH=$ROOT
PATH=$ROOT/venv/bin:/usr/local/bin:/usr/bin:/bin
ENV
chmod 600 "$ROOT/queue.env"

echo "== venv"
if [ ! -x "$ROOT/venv/bin/python" ]; then
  python3 -m venv "$ROOT/venv" || echo "MESH_QUEUE_STEP=venv_create_failed"
fi
MESH_QUEUE_VENV=$ROOT/venv
"$MESH_QUEUE_VENV/bin/python" -m pip install --quiet --upgrade pip \
  && "$MESH_QUEUE_VENV/bin/python" -m pip install --quiet -r "$QUEUE_SRC/requirements.txt" \
  || echo "MESH_QUEUE_STEP=requirements_failed"

echo "== ownership (the service writes the database it reads, so it must own the tree)"
chown -R "$ACCOUNT:$ACCOUNT" "$ROOT"
chmod 700 "$ROOT"

echo "== import check (before systemd is asked to start a process that cannot import)"
PYTHONPATH="$ROOT" "$MESH_QUEUE_VENV/bin/python" -c 'import service' \
  && echo "MESH_QUEUE_IMPORT=OK" || echo "MESH_QUEUE_STEP=import_failed"

echo "== units"
install -m 0644 "$QUEUE_SRC/deploy/padiem-mesh-queue.service" /etc/systemd/system/
install -m 0644 "$QUEUE_SRC/deploy/padiem-mesh-queue-backup.service" /etc/systemd/system/
install -m 0644 "$QUEUE_SRC/deploy/padiem-mesh-queue-backup.timer" /etc/systemd/system/
install -m 0644 "$QUEUE_SRC/deploy/padiem-mesh-queue-health.service" /etc/systemd/system/
install -m 0644 "$QUEUE_SRC/deploy/padiem-mesh-queue-health.timer" /etc/systemd/system/
install -m 0755 "$QUEUE_SRC/deploy/backup.sh" "$ROOT/backup.sh"
install -m 0755 "$QUEUE_SRC/deploy/health_check.sh" "$ROOT/health_check.sh"
install -m 0755 "$QUEUE_SRC/deploy/provision_service_secret.sh" "$ROOT/provision_service_secret.sh"
systemctl daemon-reload
systemctl enable --now padiem-mesh-queue.service \
  padiem-mesh-queue-backup.timer padiem-mesh-queue-health.timer
sleep 3
systemctl is-active padiem-mesh-queue.service | sed 's/^/MESH_QUEUE_ACTIVE=/'
systemctl is-active padiem-mesh-queue-backup.timer | sed 's/^/MESH_QUEUE_TIMER_ACTIVE=/'
systemctl is-active padiem-mesh-queue-health.timer | sed 's/^/MESH_QUEUE_TIMER_ACTIVE=/'
curl -sS --max-time 10 http://127.0.0.1:8797/health | head -c 300; echo
