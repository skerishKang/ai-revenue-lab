#!/usr/bin/env bash
set +e
export TZ=Asia/Seoul
OUT=/mnt/d/PADIEM/desktop-secret-wire-261103/step4-observation.txt
exec > >(tee "$OUT") 2>&1
PROGRESS=/mnt/d/PADIEM/desktop-secret-wire-261103/progress.md
now=$(date '+%F %T KST')
echo "- $now 4단계: 최신 presence disconnected 및 MeshCentral TCP 0 확인. MeshCentral/cloudflared 각 1회 재시작, 5분 관찰 시작." >> "$PROGRESS"
echo "RESTART_PHASE_BEGIN $now"
for svc in padiem-meshcentral cloudflared-padiem; do
 echo "RESTART_ONCE $svc"
 systemctl restart "$svc"
 rc=$?
 echo "restart_rc=$rc"
 active=0
 for i in $(seq 1 60); do
  if systemctl is-active --quiet "$svc"; then active=1; break; fi
  sleep 1
 done
 echo "active_after_restart=$active"
 systemctl show "$svc" -p ActiveState -p ActiveEnterTimestamp -p NRestarts --no-pager 2>/dev/null | tr '\n' ' '; echo
 done
probe_presence() {
 python3 - <<'PY'
import sqlite3,os,datetime
from urllib.parse import quote
p='/opt/padiem/mesh-queue/queue.sqlite3'; now=datetime.datetime.now(datetime.timezone.utc)
try:
 d=sqlite3.connect(f'file:{quote(p)}?mode=ro',uri=True,timeout=2);d.execute('PRAGMA query_only=ON')
 rows=list(d.execute('SELECT connected,received_at FROM mesh_device_presence'))
 connected=[];fresh=[];latest=None
 for c,s in rows:
  try:
   t=datetime.datetime.fromisoformat(str(s).replace('Z','+00:00'))
   if t.tzinfo is None:t=t.replace(tzinfo=datetime.timezone.utc)
   if latest is None or t>latest:latest=t; latest_c=c
   yes=c in (1,True,'1','true','connected')
   if yes:connected.append(t)
   if yes and (now-t).total_seconds()<=300:fresh.append(t)
  except:pass
 stamp=latest.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S KST') if latest else 'none'
 print(f'presence_rows={len(rows)} connected_rows={len(connected)} fresh_connected_5m={len(fresh)} latest_connected={str(latest_c in (1,True,"1","true","connected")).lower() if latest else "unknown"} latest_received={stamp}')
 d.close()
except Exception as e: print('presence_probe_error='+type(e).__name__)
PY
}
echo 'OBSERVATION_BEGIN duration=300s interval=30s'
for n in $(seq 0 10); do
 stamp=$(date '+%H:%M:%S KST')
 mc=$(systemctl is-active padiem-meshcentral 2>/dev/null); cf=$(systemctl is-active cloudflared-padiem 2>/dev/null)
 mpid=$(systemctl show padiem-meshcentral -p MainPID --value 2>/dev/null)
 sockets=0
 if [[ "$mpid" =~ ^[1-9][0-9]*$ ]]; then sockets=$(ss -Htnp state established 2>/dev/null | grep -F "pid=$mpid," | wc -l); fi
 echo "OBS $n time=$stamp meshcentral=$mc cloudflared=$cf meshcentral_established_tcp=$sockets $(probe_presence)"
 if [[ "$n" -lt 10 ]]; then sleep 30; fi
done
now=$(date '+%F %T KST')
echo "OBSERVATION_END $now"
echo "- $now 4단계: MeshCentral/cloudflared 각 1회 재시작 완료, 5분 관찰 기록 step4-observation.txt에 저장." >> "$PROGRESS"
