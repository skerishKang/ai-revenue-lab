#!/usr/bin/env bash
set +e
ops=/opt/padiem/com2-deploy/ops
printf 'OPS_PATH='
readlink -f "$ops"
printf 'OPS_DIR='
if [ -d "$ops" ]; then echo present; else echo missing; fi
printf 'GIT_TOP='
git -C "$ops" rev-parse --show-toplevel 2>&1
printf 'GIT_TOP_RC=%s\n' "$?"
printf 'GIT_HEAD='
git -C "$ops" rev-parse HEAD 2>&1
printf 'GIT_HEAD_RC=%s\n' "$?"
git -C "$ops" merge-base --is-ancestor b280d17 HEAD
printf 'B280D17_ANCESTOR_RC=%s\n' "$?"
printf 'INSTALLED_CHAT_CANDIDATES\n'
find /opt/padiem/com2-deploy/src -mindepth 2 -maxdepth 4 -type f -path '*/app/expired_purge.py' -print 2>/dev/null
