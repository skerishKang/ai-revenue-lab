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
rsync -a --delete \
  --exclude venv --exclude '__pycache__' --exclude '*.sqlite3*' --exclude 'queue.env' \
  --exclude 'service-secret.txt' --exclude 'ownership-map.json' \
  "$QUEUE_SRC/" "$ROOT/"
# The modules the queue imports are linked, not copied: app/, padiem_ai_core/ and
# padiem_control_plane/ stay the source of truth the Worker and the tests use, so a
# deployed queue cannot be running last week's copy of a rule it shares with Chat.
ln -sfn "$CHAT_SRC/app" "$ROOT/app"
ln -sfn "$REPO/packages/padiem-ai-core/padiem_ai_core" "$ROOT/padiem_ai_core"
ln -sfn "$REPO/packages/padiem-control-plane/padiem_control_plane" "$ROOT/padiem_control_plane"

echo "== environment"
cat > "$ROOT/queue.env" <<ENV
MESH_QUEUE_DB_PATH=$ROOT/queue.sqlite3
MESH_QUEUE_CHANNEL_SECRET_FILE=$CHANNEL_SECRET_FILE
MESH_QUEUE_OWNERSHIP_MAP_FILE=$ROOT/ownership-map.json
MESH_QUEUE_SERVICE_SECRET_FILE=$ROOT/service-secret.txt
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
"$MESH_QUEUE_VENV/bin/python" -c 'import service' \
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
