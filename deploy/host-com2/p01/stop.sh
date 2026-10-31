#!/usr/bin/env bash
# Stops the COM2 P01 Engine unit only. Never disables it.
set -euo pipefail
unit=padiem-p01.service
fail() { echo "P01_COM2_STOP=$1" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || fail ROOT_REQUIRED
if ! systemctl is-active --quiet "$unit"; then
  echo 'P01_COM2_STOP=NOT_ACTIVE'
  exit 0
fi
systemctl stop "$unit"
if systemctl is-active --quiet "$unit"; then fail STILL_ACTIVE; fi
echo 'P01_COM2_STOP=STOPPED ENABLED_STATE_UNCHANGED=YES'
