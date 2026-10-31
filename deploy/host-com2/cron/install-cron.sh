#!/usr/bin/env bash
# Renders the COM2 cron units for one profile. Dry-run by default.
#
# `--apply` copies the scripts into the app root and writes the two unit files,
# then runs daemon-reload. It never starts or enables the timer, never edits the
# env file it references, and never touches Cloudflare.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
profile=staging
schedule=""
render_dir=""
app_root=""
apply=0
user="padiem-chat"

usage() {
  echo "usage: install-cron.sh [--profile staging|production] --schedule '<OnCalendar>' [--render-dir DIR] [--app-root DIR] [--user NAME] [--apply]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) profile=$2; shift 2 ;;
    --schedule) schedule=$2; shift 2 ;;
    --render-dir) render_dir=$2; shift 2 ;;
    --app-root) app_root=$2; shift 2 ;;
    --user) user=$2; shift 2 ;;
    --dry-run) apply=0; shift ;;
    --apply) apply=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "CRON_INSTALL=REFUSED reason=unknown_argument arg=$1" >&2; exit 2 ;;
  esac
done

conf="$here/profiles/$profile.conf"
if [[ ! -f "$conf" ]]; then
  echo "CRON_INSTALL=REFUSED reason=profile_missing profile=$profile" >&2
  exit 2
fi

# shellcheck disable=SC1090
PROFILE=""; UNIT_NAME=""; APP_ROOT=""; DATA_ROOT=""; ENV_FILE=""; SERVICE_USER=""; QUEUE_ORIGIN=""; START_TIMEOUT=""; CRON_SCHEDULE=""
source "$conf"

[[ -n "$schedule" ]] || schedule=$CRON_SCHEDULE
if [[ -z "$schedule" ]]; then
  echo "CRON_INSTALL=REFUSED reason=CRON_SCHEDULE_REQUIRED profile=$profile" >&2
  echo "CRON_INSTALL_HINT=the deployed Cloudflare trigger is dashboard-owned; pass its period explicitly" >&2
  exit 2
fi

app_root=${app_root:-$APP_ROOT}
user=${user:-$SERVICE_USER}
render_dir=${render_dir:-/etc/systemd/system}

render() {
  local template=$1 destination=$2
  sed \
    -e "s|@PROFILE@|$PROFILE|g" \
    -e "s|@UNIT_NAME@|$UNIT_NAME|g" \
    -e "s|@APP_ROOT@|$app_root|g" \
    -e "s|@DATA_ROOT@|$DATA_ROOT|g" \
    -e "s|@ENV_FILE@|$ENV_FILE|g" \
    -e "s|@SERVICE_USER@|$user|g" \
    -e "s|@QUEUE_ORIGIN@|$QUEUE_ORIGIN|g" \
    -e "s|@START_TIMEOUT@|$START_TIMEOUT|g" \
    -e "s|@CRON_SCHEDULE@|$schedule|g" \
    "$template" > "$destination"
}

echo "CRON_INSTALL_PROFILE=$PROFILE"
echo "CRON_INSTALL_UNIT=$UNIT_NAME"
echo "CRON_INSTALL_SCHEDULE=$schedule"
echo "CRON_INSTALL_APP_ROOT=$app_root"
echo "CRON_INSTALL_DATA_ROOT=$DATA_ROOT"
echo "CRON_INSTALL_ENV_FILE=$ENV_FILE"
echo "CRON_INSTALL_QUEUE_ORIGIN=$QUEUE_ORIGIN"
echo "CLOUDFLARE_CHANGE=NO"
echo "ENV_FILE_EDIT=NO"

if [[ $apply -eq 0 ]]; then
  echo "CRON_INSTALL=DRY_RUN render_dir=$render_dir"
  echo "START_SERVICE=NO"
  echo "ENABLE_SERVICE=NO"
  echo "UNIT_SERVICE=$render_dir/$UNIT_NAME.service"
  echo "UNIT_TIMER=$render_dir/$UNIT_NAME.timer"
  exit 0
fi

mkdir -p "$render_dir" "$app_root"
install -m 0755 "$here/run-cron.sh" "$app_root/run-cron.sh"
install -m 0755 "$here/status-cron.sh" "$app_root/status-cron.sh"
install -m 0644 "$here/check_config_cron.py" "$app_root/check_config_cron.py"
install -m 0644 "$here/README.md" "$app_root/README-cron.md"
render "$here/padiem-chat-cron.service.template" "$render_dir/$UNIT_NAME.service"
render "$here/padiem-chat-cron.timer.template" "$render_dir/$UNIT_NAME.timer"
chmod 0644 "$render_dir/$UNIT_NAME.service" "$render_dir/$UNIT_NAME.timer"

if [[ "$render_dir" == "/etc/systemd/system" ]] && command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  echo "DAEMON_RELOAD=YES"
else
  echo "DAEMON_RELOAD=NO reason=render_dir_not_systemd"
fi

echo "CRON_INSTALL=APPLIED"
echo "START_SERVICE=NO"
echo "ENABLE_SERVICE=NO"
echo "UNIT_SERVICE=$render_dir/$UNIT_NAME.service"
echo "UNIT_TIMER=$render_dir/$UNIT_NAME.timer"
