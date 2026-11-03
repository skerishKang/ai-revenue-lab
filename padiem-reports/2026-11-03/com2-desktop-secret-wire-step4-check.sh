#!/usr/bin/env bash
set +e
export TZ=Asia/Seoul
OUT=/mnt/d/PADIEM/desktop-secret-wire-261103/step4-check.txt
exec > >(tee "$OUT") 2>&1
NOW=$(date '+%F %T %Z'); TODAY=$(date +%F)
echo "STEP4 READ_ONLY $NOW"
for unit in padiem-meshcentral cloudflared-padiem; do
 echo "UNIT $unit"
 systemctl show "$unit" -p ActiveState -p SubState -p ActiveEnterTimestamp -p NRestarts -p MainPID --no-pager 2>/dev/null | tr '\n' ' '; echo
 pid=$(systemctl show "$unit" -p MainPID --value 2>/dev/null)
 if [[ "$pid" =~ ^[1-9][0-9]*$ ]] && command -v ss >/dev/null 2>&1; then
  n=$(ss -Htnp state established 2>/dev/null | grep -F "pid=$pid," | wc -l)
  echo "$unit established_tcp=$n"
 fi
done
echo 'MESHCENTRAL AGENT EVENT TAGS since=10:17 KST'
journalctl -u padiem-meshcentral --since "$TODAY 10:17:00" --until "$NOW" --no-pager -o json 2>/dev/null | python3 -c '
import sys,json,datetime,re
for line in sys.stdin:
 try:x=json.loads(line)
 except:continue
 m=str(x.get("MESSAGE","")); low=m.lower()
 if not any(k in low for k in ("agent","connect","disconnect","websocket")):continue
 tags=[]
 if "agent" in low:tags.append("agent")
 if "connect" in low or "websocket" in low:tags.append("connect")
 if "disconnect" in low:tags.append("disconnect")
 try:t=datetime.datetime.fromtimestamp(int(x["__REALTIME_TIMESTAMP"])/1e6,datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%H:%M:%S KST")
 except:t="unknown-time"
 print(t+" event="+"/".join(dict.fromkeys(tags)))
'
echo 'QUEUE POLL/PRESENCE TAGS since=10:17 KST'
journalctl -u padiem-mesh-queue --since "$TODAY 10:17:00" --until "$NOW" --no-pager -o json 2>/dev/null | python3 -c '
import sys,json,datetime
for line in sys.stdin:
 try:x=json.loads(line)
 except:continue
 m=str(x.get("MESSAGE",""));low=m.lower(); tags=[k for k in ("presence","poll") if k in low]
 if tags:
  try:t=datetime.datetime.fromtimestamp(int(x["__REALTIME_TIMESTAMP"])/1e6,datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%H:%M:%S KST")
  except:t="unknown-time"
  print(t+" event="+"/".join(tags))
'
echo 'QUEUE PRESENCE DB read_only=mode_ro'
python3 - <<'PY'
import sqlite3,os,re,datetime
from urllib.parse import quote
p='/opt/padiem/mesh-queue/queue.sqlite3'
if not os.path.exists(p):print('queue_db=missing');raise SystemExit
try:
 d=sqlite3.connect(f'file:{quote(p)}?mode=ro',uri=True,timeout=2);d.execute('PRAGMA query_only=ON')
 cols=[r[1] for r in d.execute('PRAGMA table_info(mesh_device_presence)')]; low={c.lower():c for c in cols}
 count=d.execute('select count(*) from mesh_device_presence').fetchone()[0];print('presence_rows='+str(count))
 def pick(*names):return next((low[n] for n in names if n in low),None)
 dev=pick('device_id','mesh_device_id','id','device_key'); con=pick('connected','is_connected'); recv=pick('received_at','last_received_at','updated_at','last_seen_at'); refs=pick('account_refs_json')
 if not all((dev,con,recv)):print('presence_schema=detail_unavailable');raise SystemExit
 def q(x):return '"'+x.replace('"','""')+'"'
 fields=[dev,con,recv]+([refs] if refs else [])
 rows=list(d.execute('select '+','.join(q(c) for c in fields)+' from mesh_device_presence'))
 for row in rows:
  ident=re.sub(r'[^A-Za-z0-9_-]','',str(row[0]))[:8] or 'unknown'
  v=row[1]; conn='true' if v in (1,True,'1','true','connected') else 'false' if v in (0,False,'0','false','disconnected') else 'unknown'
  stamp=str(row[2])
  if re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z',stamp):
   try: stamp=datetime.datetime.fromisoformat(stamp.replace('Z','+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S KST')
   except: pass
  else: stamp='unrecognized'
  rs='unknown' if not refs else ('populated' if row[3] not in (None,'','[]','{}') else 'empty')
  print(f'device={ident} connected={conn} received_at={stamp} account_refs={rs}')
 d.close()
except Exception as e:print('presence_read_error='+type(e).__name__)
PY
echo 'CHAT TRACEBACK SAFE DETAILS 11:20..now'
journalctl -u padiem-chat-com2 --since "$TODAY 11:20:00" --until "$NOW" --no-pager -o json 2>/dev/null | python3 -c '
import sys,json,re,datetime
codes=("canonical_b54_session_unavailable","command_workspace_unavailable","engine_not_configured","composition_unavailable")
seen=0
for line in sys.stdin:
 try:x=json.loads(line)
 except:continue
 m=str(x.get("MESSAGE",""));low=m.lower()
 if not any(k in low for k in ("traceback","error","exception")) and not any(c in low for c in codes):continue
 tags=[c for c in codes if c in low]
 if "traceback" in low:tags.append("Traceback")
 if "error" in low:tags.append("ERROR")
 classes=list(dict.fromkeys(re.findall(r"(?<![A-Za-z0-9_])([A-Z][A-Za-z0-9]*(?:Error|Exception))(?![A-Za-z0-9_])",m)))
 if classes:tags.append("exception="+classes[-1])
 locs=re.findall(r"File \"[^\"]*[/\\]([^/\\\"]+\.py)\", line (\d+)",m)
 if locs:tags.append("frame="+locs[-1][0]+":"+locs[-1][1])
 if x.get("CODE_FILE"):tags.append("caller="+str(x['CODE_FILE']).replace('\\','/').split('/')[-1]+":"+str(x.get('CODE_LINE','?')))
 if not classes and not locs and not x.get('CODE_FILE'):tags.append('exception_location=not_in_journal_record')
 try:t=datetime.datetime.fromtimestamp(int(x["__REALTIME_TIMESTAMP"])/1e6,datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S KST")
 except:t="unknown-time"
 print(t+" "+" ".join(dict.fromkeys(tags)));seen+=1
if not seen:print('no_matching_records')
'
echo 'P01 START REGISTRATION MARKERS 11:30..now'
journalctl -u padiem-p01 --since "$TODAY 11:30:00" --until "$NOW" --no-pager -o json 2>/dev/null | python3 -c '
import sys,json,datetime
counts={k:0 for k in ("claw","pc_query","browser","registered","chat_binding")}
for line in sys.stdin:
 try:x=json.loads(line)
 except:continue
 m=str(x.get("MESSAGE",""));low=m.lower()
 if "claw" in low and "desktop" in low:counts["claw"]+=1
 if "pc" in low and ("query" in low or "drive" in low):counts["pc_query"]+=1
 if "browser" in low:counts["browser"]+=1
 if "registered" in low:counts["registered"]+=1
 if "padiem_chat_service" in low:counts["chat_binding"]+=1
for k,v in counts.items():print(f"{k}_marker_count={v}")
'
