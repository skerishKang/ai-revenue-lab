from pathlib import Path
import re
base=Path('/mnt/d/PADIEM/desktop-secret-wire-261103')
allow={'status','result','outcome','action','phase','migration','migration_first','code','main_sha','target_sha','commit','service','component','db','backup','deploy','apply','exit_code','return_code'}
for name in ('dryrun.log','apply.log','apply2.log'):
 p=base/name
 print(f'LOG {name} exists={p.exists()}')
 if not p.exists():continue
 hits=0
 for i,line in enumerate(p.read_text(errors='replace').splitlines(),1):
  if 'summary' not in line.lower() and not re.search(r'\bMIGRATION_FIRST\b|\b093\b',line):continue
  vals=[]
  for k,v in re.findall(r'([A-Za-z][A-Za-z0-9_-]*)\s*[:=]\s*([A-Za-z0-9._/-]+)',line):
   if k.lower() not in allow:continue
   if k.lower() in {'main_sha','target_sha','commit'} and not re.fullmatch(r'[0-9a-fA-F]{7,40}',v):continue
   if k.lower() not in {'main_sha','target_sha','commit'} and not re.fullmatch(r'[A-Za-z0-9._/-]{1,32}',v):continue
   vals.append(k+'='+v)
  # Print labels and allow-listed values only, never raw log text.
  if vals:
   print(f'line={i} '+' '.join(dict.fromkeys(vals)));hits+=1
 print('safe_summary_records='+str(hits))
