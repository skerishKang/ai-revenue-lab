#!/bin/bash
# Entry run by the Windows Scheduled Task (SYSTEM, AtStartup) inside WSL.
# Waits for systemd, then runs the boot self-check. Never restarts anything.
#
# 261105: "is-system-running --wait" can block past the unit's own
# TimeoutStartSec on a slow cold boot (measured: the 2026-11-02 boot finished
# startup in 11m41s and the self-check was TERM'd with no report or alert).
# The wait is now capped at 180 s so the python check always keeps a bounded
# slice of the unit budget; the verdict rules themselves are unchanged.
set -uo pipefail
timeout 180 systemctl is-system-running --wait >/dev/null 2>&1 || true
exec /usr/bin/python3 /opt/padiem/boot-recovery/boot_recovery.py boot --wait-seconds "${BOOT_RECOVERY_WAIT_SECONDS:-240}"
