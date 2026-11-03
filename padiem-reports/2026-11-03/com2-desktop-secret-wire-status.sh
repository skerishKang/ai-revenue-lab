#!/usr/bin/env bash
set +e
export TZ=Asia/Seoul
echo "TIME $(date '+%F %T %Z')"
python3 - <<'PY'
import os
needles=(b'deploy_from_main.sh',b'migrate_093',b'migration_apply')
found=[]
for name in os.listdir('/proc'):
 if not name.isdigit():continue
 try:
  raw=open(f'/proc/{name}/cmdline','rb').read()
 except:continue
 if any(n in raw for n in needles):found.append(name)
print('deployment_or_migration_processes='+(','.join(found) if found else 'none'))
PY
for s in padiem-chat-com2 padiem-p01 padiem-mesh-queue padiem-b14; do
 systemctl show "$s" -p ActiveState -p SubState -p ActiveEnterTimestamp -p NRestarts --no-pager 2>/dev/null | tr '\n' ' '; echo " unit=$s"
done
for spec in 'chat http://127.0.0.1:8798/health' 'p01 http://127.0.0.1:8811/internal/v1/health'; do
 set -- $spec; printf '%s ' "$1"; curl -sS --max-time 5 -o /dev/null -w '%{http_code} %{time_total}\n' "$2" 2>/dev/null
done
for s in padiem-chat-com2 padiem-p01; do
 echo "LAST_START_LOG $s"
 journalctl -u "$s" -n 40 --no-pager -o short-iso 2>/dev/null | python3 -c '
import sys,re
for line in sys.stdin:
 low=line.lower()
 if any(k in low for k in ("started","stopped","claw_engine_desktop_secret","p01_config","traceback","error")):
  ts=line[:35].strip()
  tags=[]
  for code in ("claw_engine_desktop_secret=configured","claw_engine_desktop_secret=unconfigured","traceback","error","p01_config=ready","started","stopped"):
   if code in low:tags.append(code)
  if "p01_config" in low and not any(t.startswith("p01_config=") for t in tags):tags.append("p01_config")
  print(ts+" "+" ".join(tags))
'
done
