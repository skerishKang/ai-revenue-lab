import datetime, json, os, re, subprocess
from zoneinfo import ZoneInfo
now=datetime.datetime.now(ZoneInfo('Asia/Seoul'))
start=now.replace(hour=11,minute=20,second=0,microsecond=0)
cmd=['journalctl','-u','padiem-chat-com2','--since',start.strftime('%Y-%m-%d %H:%M:%S'),'--until',now.strftime('%Y-%m-%d %H:%M:%S'),'--no-pager','-o','json']
r=subprocess.run(cmd,capture_output=True,text=True,errors='replace')
codes=('canonical_b54_session_unavailable','command_workspace_unavailable','engine_not_configured','composition_unavailable')
count=0
for raw in r.stdout.splitlines():
 try: x=json.loads(raw)
 except Exception: continue
 msg=str(x.get('MESSAGE',''))
 low=msg.lower()
 priority=str(x.get('PRIORITY',''))
 if not any((w in low for w in ('traceback','error','exception'))) and not any((c in low for c in codes)) and priority not in ('0','1','2','3'): continue
 tags=[c for c in codes if c in low]
 if 'traceback' in low: tags.append('Traceback')
 if 'error' in low: tags.append('ERROR')
 classes=list(dict.fromkeys(re.findall(r'(?<![A-Za-z0-9_])([A-Z][A-Za-z0-9]*(?:Error|Exception))(?![A-Za-z0-9_])',msg)))
 for key in ('EXCEPTION_TYPE','exception_type','exception.class'):
  if x.get(key):
   n=str(x[key]).split('.')[-1]
   if re.fullmatch(r'[A-Za-z_][A-Za-z0-9]*(?:Error|Exception)',n): classes.append(n)
 if classes: tags.append('exception='+classes[-1])
 frames=re.findall(r'File [\"\']([^\"\']+)[\"\'], line (\d+)',msg)
 if frames:
  for path,line in frames[-3:]: tags.append('frame='+os.path.basename(path)+':'+line)
 codefile=x.get('CODE_FILE') or x.get('code_file')
 codeline=x.get('CODE_LINE') or x.get('code_line')
 if codefile and codeline:
  tags.append('logger='+os.path.basename(str(codefile))+':'+str(codeline))
 ts=x.get('__REALTIME_TIMESTAMP')
 try: stamp=datetime.datetime.fromtimestamp(int(ts)/1e6,datetime.timezone.utc).astimezone(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S KST')
 except Exception: stamp='time-unknown'
 if not classes and not frames and not (codefile and codeline): tags.append('exception_location=not_in_journal')
 print(stamp+' '+' '.join(dict.fromkeys(tags)))
 count+=1
if count==0: print('no_error_or_traceback_records')
