#!/bin/bash
# Entry run by the Windows Scheduled Task (SYSTEM, AtStartup) inside WSL.
# Waits for systemd, then runs the boot self-check. Never restarts anything.
set -uo pipefail
systemctl is-system-running --wait >/dev/null 2>&1 || true
exec /usr/bin/python3 /opt/padiem/boot-recovery/boot_recovery.py boot --wait-seconds "${BOOT_RECOVERY_WAIT_SECONDS:-240}"
