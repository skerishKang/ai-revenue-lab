#!/usr/bin/env bash
# Stage the B14 COM2 runtime files (#5784 PR-3).
#
# Written by the authorized COM2 operator, never by CI and never by this
# repository: this script copies reviewed template files into their host
# locations, plus one canonical shared PC metrics module beside the operator's
# staged B14 app. Configuration files keep the foreign-target protection below.
# It does not enable, start, restart, or reload a running service
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

unit_is_ours() {
  # The live unit is the operator's file the moment it was edited in place — a
  # static identity, an added dependency. It is still PADIEM B14's unit when the
  # description and the interpreter entry point are ours. Aborting on that used to
  # leave the service stopped, so an ours-unit is adopted: kept as it is, never
  # rewritten. Every other configuration file keeps the foreign-target protection.
  grep -q '^Description=PADIEM B14' "$1" 2>/dev/null \
    && grep -qE '^ExecStart=[^ ]*venv/bin/python [^ ]*app/asgi\.py' "$1" 2>/dev/null
}

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

# The operator still stages B14's application checkout. Its one shared PC
# metrics contract must come from the same reviewed repository revision;
# copying the whole Core package is neither needed nor this installer's job.
PC_METRICS_SOURCE="$SRC_DIR/../../../packages/padiem-ai-core/padiem_ai_core/pc_work_metrics.py"
PC_METRICS_PACKAGE="$APP_ROOT/app/padiem_ai_core"
[ -f "$PC_METRICS_SOURCE" ] || fail "pc_metrics_source_missing"
if $DRY_RUN; then
  note "would_stage:pc_work_metrics"
else
  install -d -o root -g root -m 0755 "$PC_METRICS_PACKAGE"
  if [ ! -e "$PC_METRICS_PACKAGE/__init__.py" ]; then
    printf '%s\n' '"""Deployment-staged canonical Core modules."""' > "$PC_METRICS_PACKAGE/__init__.py"
    chmod 0644 "$PC_METRICS_PACKAGE/__init__.py"
  fi
  install -o root -g root -m 0644 "$PC_METRICS_SOURCE" "$PC_METRICS_PACKAGE/pc_work_metrics.py"
  (cd "$APP_ROOT/app" && "$APP_ROOT/venv/bin/python" -c \
    'from padiem_ai_core.pc_work_metrics import validate_pc_work_metrics') \
    || fail "pc_metrics_import_failed"
  note "staged:pc_work_metrics"
fi

write_staged() {
  # Copy only when the destination is absent or already identical. A foreign
  # destination is a decision the operator owns; silently replacing live host
  # configuration is not this script's authority. An $ours_pattern says the file
  # is unmistakably this service's own, so it is adopted rather than refused.
  local source="$1" target="$2" label="$3" ours_pattern="${4:-}"
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
  if [ -n "${ours_pattern:-}" ] && grep -qE "$ours_pattern" "$target" 2>/dev/null; then
    if $DRY_RUN; then note "would_adopt_local_$label"; return 0; fi
    note "adopted_local_$label"
    return 0
  fi
  if [ "$label" = unit ] && unit_is_ours "$target"; then
    if $DRY_RUN; then note 'would_adopt_local_unit'; return 0; fi
    note 'adopted_local_unit'
    return 0
  fi
  if $DRY_RUN; then note "would_refuse_foreign:$label"; return 0; fi
  fail "foreign_target:$label"
}

write_staged "$SRC_DIR/padiem-b14.service.example" "$UNIT_TARGET" unit
write_staged "$SRC_DIR/padiem-b14-admin.service.example" "$ADMIN_UNIT_TARGET" admin_unit

if ! $DRY_RUN; then install -d -o root -g root -m 0755 "$DROPIN_TARGET_DIR"; fi
# journald is the reviewed default, and the file-log drop-in is opt-in: installing
# it because the template exists silently moved a running service off journald and
# into a log path it may not own, which is how a deploy once put B14 in a restart
# loop. Only refresh a drop-in the operator already chose to install.
if [ -e "$DROPIN_TARGET_DIR/20-log-to-file.conf" ]; then
  write_staged "$SRC_DIR/20-log-to-file.conf.example" "$DROPIN_TARGET_DIR/20-log-to-file.conf" \
    dropin 'StandardOutput=append:[^ ]*b14'
else
  note "dropin_absent_journald_default"
fi

# Optional and explicitly inert until the operator installs it: the rotation file
# only matters for the file-log mode, and journald collection is the default.
write_staged "$SRC_DIR/logrotate.conf.example" "$LOGROTATE_TARGET" logrotate '/opt/padiem/b14/logs'

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
