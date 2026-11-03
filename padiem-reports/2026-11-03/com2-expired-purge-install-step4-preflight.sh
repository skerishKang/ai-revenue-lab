#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
env_path = Path("/opt/padiem/chat-com2/.env")
wanted = {
    "PADIEM_CHAT_CPYTHON_HOST",
    "PADIEM_LOCAL_DEV",
    "PADIEM_CHAT_LOCAL_DATA_DIR",
    "PADIEM_CHAT_EXPIRED_PURGE_GRACE_DAYS",
    "PADIEM_CHAT_EXPIRED_PURGE_BATCH",
}
values = {}
for raw in env_path.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key in wanted:
        values[key] = value.strip().strip("'").strip('"')
print("PURGE_ENV_FILE_CHECK=present")
print("PURGE_HOST_GATE=" + ("enabled" if values.get("PADIEM_CHAT_CPYTHON_HOST") == "1" or values.get("PADIEM_LOCAL_DEV") == "1" else "missing"))
print("PURGE_DATA_DIR=" + values.get("PADIEM_CHAT_LOCAL_DATA_DIR", "unset"))
print("PURGE_GRACE_DAYS=" + values.get("PADIEM_CHAT_EXPIRED_PURGE_GRACE_DAYS", "default"))
print("PURGE_BATCH=" + values.get("PADIEM_CHAT_EXPIRED_PURGE_BATCH", "default"))
PY
