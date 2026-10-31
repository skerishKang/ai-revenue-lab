#!/usr/bin/env bash
# Stage the B14 COM2 runtime files (#5784 PR-3).
#
# Written by the authorized COM2 operator, never by CI and never by this
# repository: this script copies reviewed template files into their host
# locations. It does not enable, start, restart, or reload a running service
# unless --reload is passed, and it refuses to overwrite a file it did not
# place there. Setting B14_UPSTREAM_MODE and deploying Chat/Engine is a separate,
# gated act recorded in docs/operations/B14_COM2_RUNBOOK.md, not something this
# script can do.
#
#   bash install.sh --dry-run     print decisions, write nothing
#   bash install.sh               stage unit, drop-in, logrotate and ingress files
#   bash install.sh --reload      also systemctl daemon-reload (still no start)
set -euo pipefail
set +x
umask 077

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT=/opt/padiem/b14
UNIT_TARGET=/etc/systemd/system/padiem-b14.service
ADMIN_UNIT_TARGET=/etc/systemd/system/padiem-b14-admin.service
DROPIN_TARGET_DIR=/etc/systemd/system/padiem-b14.service.d
LOGROTATE_TARGET=/etc/logrotate.d/padiem-b14
INGRESS_TARGET=/opt/padiem/cloudflared/config.yml
DRY_RUN=false
RELOAD=false

fail() { printf 'B14_COM2_INSTALL_ABORT=%s\n' "$*" >&2; exit 2; }
note() { printf 'B14_COM2_INSTALL=%s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --reload) RELOAD=true ;;
    *) fail "unknown_argument" ;;
  esac
  shift
done

if [ "$(uname -s)" != "Linux" ]; then fail "linux_required"; fi
if [ "$(id -u)" != "0" ]; then fail "root_required"; fi
if ! command -v systemctl >/dev/null 2>&1; then fail "systemd_missing"; fi
[ -d "$APP_ROOT/app" ] || fail "app_dir_missing"
[ -f "$APP_ROOT/app/asgi.py" ] || fail "asgi_entry_missing"
[ -x "$APP_ROOT/venv/bin/python" ] || fail "venv_python_missing"

write_staged() {
  # Copy only when the destination is absent or already identical. A foreign
  # destination is a decision the operator owns; silently replacing live host
  # configuration is not this script's authority.
  local source="$1" target="$2" label="$3"
  if [ ! -e "$target" ]; then
    if $DRY_RUN; then note "would_stage:$label"; return 0; fi
    install -o root -g root -m 0644 "$source" "$target"
    note "staged:$label"
    return 0
  fi
  if cmp -s "$source" "$target"; then
    note "already_current:$label"
    return 0
  fi
  if $DRY_RUN; then note "would_refuse_foreign:$label"; return 0; fi
  fail "foreign_target:$label"
}

write_staged "$SRC_DIR/padiem-b14.service.example" "$UNIT_TARGET" unit
write_staged "$SRC_DIR/padiem-b14-admin.service.example" "$ADMIN_UNIT_TARGET" admin_unit

if ! $DRY_RUN; then install -d -o root -g root -m 0755 "$DROPIN_TARGET_DIR"; fi
write_staged "$SRC_DIR/20-log-to-file.conf.example" "$DROPIN_TARGET_DIR/20-log-to-file.conf" dropin

# Optional and explicitly inert until the operator installs it: the rotation file
# only matters for the file-log mode, and journald collection is the default.
write_staged "$SRC_DIR/logrotate.conf.example" "$LOGROTATE_TARGET" logrotate

# The ingress config is shared with the file lane. Never write over one that
# exists; the operator adds the missing hostname block by hand and validates it
# offline.
if [ -e "$INGRESS_TARGET" ]; then
  if grep -q "hostname: b14.padiem.net" "$INGRESS_TARGET"; then
    note "ingress_entry_present"
  else
    note "ingress_add_manual_required:hostname=b14.padiem.net"
  fi
else
  write_staged "$SRC_DIR/cloudflared-config.example.yml" "$INGRESS_TARGET" ingress
fi

if ! $DRY_RUN; then
  install -d -o root -g root -m 0700 "$APP_ROOT/env"
  install -d -o padiem-b14 -g padiem-b14 -m 0700 "$APP_ROOT/ledger" "$APP_ROOT/logs" 2>/dev/null \
    || note "data_dirs_need_runtime_identity"
  cp -f "$SRC_DIR/../../../apps/korean-ai-platform/b14.env.example" "$APP_ROOT/env/b14.env.example" 2>/dev/null \
    || note "env_example_copy_skipped"
  # The secret and registry directories belong to systemd (StateDirectory), so
  # this script neither creates them nor touches their ownership: systemd assigns
  # them to the static padiem-b14 account at start. The registry is seeded from the
  # checkout only when the host has none, and never overwritten — what the
  # Owner registers on this machine survives the next deploy.
  REGISTRY_STATE="/var/lib/padiem-b14/b14-registry/b14_models.json"
  if [ -f "$REGISTRY_STATE" ]; then
    note "registry_seed_present"
  elif [ -f "$APP_ROOT/app/app/pilot/b14_models.json" ]; then
    note "registry_seed_manual:cp -n $APP_ROOT/app/app/pilot/b14_models.json $REGISTRY_STATE"
  else
    note "registry_seed_source_missing"
  fi
fi

if $RELOAD && ! $DRY_RUN; then
  systemctl daemon-reload
  note "daemon_reload_done"
fi

# Enabled and started state is reported, never changed.
note "unit_state:$(systemctl is-enabled padiem-b14.service 2>/dev/null || echo unknown)"
note "unit_active:$(systemctl is-active padiem-b14.service 2>/dev/null || echo unknown)"
note "NO_SERVICE_STARTED=YES"
note "NO_CREDENTIAL_WRITTEN=YES"
note "NO_UPSTREAM_MODE_CHANGED=YES"
