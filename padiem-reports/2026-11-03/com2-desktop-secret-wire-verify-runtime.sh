#!/usr/bin/env bash
set +e
export TZ=Asia/Seoul
echo "VERIFY_RUNTIME $(date '+%F %T %Z')"
python3 - <<'PY'
import os,hashlib,stat,re
files={"p01_env":"/opt/padiem/p01/env/p01.env","chat_env":"/opt/padiem/chat-com2/.env","secure":"/root/padiem-secure/claw-engine-desktop-secret-20261103.txt"}
name="CLAW_ENGINE_DESKTOP_SECRET"
def get_env(path,key):
 try:
  for line in open(path,encoding='utf-8',errors='ignore'):
   s=line.strip()
   if s.startswith('export '):s=s[7:].lstrip()
   if s.startswith(key+'='):
    v=s.split('=',1)[1].strip()
    if len(v)>=2 and v[0]==v[-1] and v[0] in "\"'":v=v[1:-1]
    return v
 except:pass
 return None
vals={k:get_env(p,name) for k,p in files.items() if k!='secure'}
try: vals['secure']=open(files['secure'],'r',encoding='utf-8').read().strip()
except: vals['secure']=None
present={k:(v is not None and len(v)>0) for k,v in vals.items()}
match=all(present.values()) and len({hashlib.sha256(v.encode()).hexdigest() for v in vals.values()})==1
print('secret_file_presence='+','.join(f'{k}:{str(present[k]).lower()}' for k in ('p01_env','chat_env','secure')))
print('secret_file_hash_match='+('yes' if match else 'no'))
for k,p in files.items():
 try:
  mode=stat.S_IMODE(os.stat(p).st_mode)
  print(f'{k}_mode={mode:04o}')
 except: print(f'{k}_mode=missing')
origin=get_env(files['p01_env'],'PADIEM_ENGINE_LOCAL_CHAT_ORIGIN')
print('p01_chat_origin_present='+str(bool(origin)).lower())
print('p01_chat_origin_expected='+str(origin=='http://127.0.0.1:8798').lower())
for unit in ('padiem-p01','padiem-chat-com2'):
 try:
  pid=os.popen(f'systemctl show {unit} -p MainPID --value').read().strip()
  raw=open(f'/proc/{pid}/environ','rb').read().split(b'\0') if pid.isdigit() else []
  env={}
  for item in raw:
   if b'=' in item:
    k,v=item.split(b'=',1);env[k.decode(errors='ignore')]=v.decode(errors='ignore')
  val=env.get(name)
  key_match=bool(val) and vals.get('p01_env') is not None and hashlib.sha256(val.encode()).hexdigest()==hashlib.sha256(vals['p01_env'].encode()).hexdigest()
  print(f'{unit}_pid_valid={str(bool(raw)).lower()}')
  print(f'{unit}_secret_process_present={str(bool(val)).lower()}')
  print(f'{unit}_secret_process_matches_p01_file={str(key_match).lower()}')
  if unit=='padiem-p01':
   o=env.get('PADIEM_ENGINE_LOCAL_CHAT_ORIGIN')
   print('p01_origin_process_present='+str(bool(o)).lower())
   print('p01_origin_process_expected='+str(o=='http://127.0.0.1:8798').lower())
 except Exception as e: print(f'{unit}_process_read={type(e).__name__}')
PY
for spec in 'chat http://127.0.0.1:8798/health' 'p01 http://127.0.0.1:8811/internal/v1/health' 'queue http://127.0.0.1:8797/health'; do
 set -- $spec; printf '%s ' "$1"; curl -sS --max-time 5 -o /dev/null -w '%{http_code} %{time_total}\n' "$2" 2>/dev/null
done
for unit in padiem-chat-com2 padiem-p01; do
 echo "SAFE_START_AND_ERROR_TAGS $unit"
 journalctl -u "$unit" --since '2026-11-03 11:30:00' --no-pager -o json 2>/dev/null | python3 -c '
import sys,json,re,datetime,os
codes=("canonical_b54_session_unavailable","command_workspace_unavailable","engine_not_configured","composition_unavailable","claw_engine_desktop_secret=configured","claw_engine_desktop_secret=unconfigured")
for line in sys.stdin:
 try:x=json.loads(line)
 except:continue
 m=str(x.get("MESSAGE","")); low=m.lower(); tags=[c for c in codes if c in low]
 if "p01_config" in low:tags.append("P01_CONFIG")
 if "registered" in low and any(k in low for k in ("claw","pc","desktop","browser")):tags.append("tools_registered_event")
 if any(k in low for k in ("claw.pc","desktop tool","pc tool","browser tool")):tags.append("pc_tool_event")
 if "traceback" in low:tags.append("Traceback")
 if re.search(r"\bERROR\b",m,re.I):tags.append("ERROR")
 ex=re.findall(r"\b([A-Z][A-Za-z0-9]*(?:Error|Exception))\b",m)
 if ex:tags.append("exception_class="+ex[-1])
 loc=re.findall(r"File \"[^\"]*[/\\]([^/\\\"]+\.py)\", line (\d+)",m)
 if loc:tags.append("frame="+loc[-1][0]+":"+loc[-1][1])
 if tags:
  try:t=datetime.datetime.fromtimestamp(int(x["__REALTIME_TIMESTAMP"])/1e6,datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S KST")
  except:t="unknown-time"
  print(t+" "+" ".join(dict.fromkeys(tags)))
'
done
