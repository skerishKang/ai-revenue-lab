from pathlib import Path
from html.parser import HTMLParser
import json,re,sys
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'index.html').read_text(encoding='utf-8')
CSS=(ROOT/'styles/main.css').read_text(encoding='utf-8')
JS=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
class P(HTMLParser):
 def __init__(self): super().__init__(); self.tags=[]
 def handle_starttag(self,tag,attrs): self.tags.append((tag,dict(attrs)))
p=P();p.feed(HTML)
tabs=[a for t,a in p.tags if a.get('role')=='tab']
panels=[a for t,a in p.tags if a.get('role')=='tabpanel']
states=['cover','schedule','inputs','run','exceptions','decision','mobile']
asset_refs=re.findall(r'(?:src|href)="([^"]+)"',HTML)
local_assets=[]
for ref in asset_refs:
 clean=ref.split('?')[0]
 if clean.startswith(('http:','https:','//','#')): continue
 if clean.endswith(('.css','.js','.svg')): local_assets.append(clean)
missing=[x for x in local_assets if not (ROOT/x).exists()]
required=['SYNTHETIC SCHEDULED OPERATION','OPERATION OWNER','TIMEZONE — SYNTHETIC CONFIGURATION','EXACT SCHEDULE','FLEXIBLE DELIVERY WINDOW','RECURRING CADENCE','CONDITION WATCH','NEXT PLANNED RUN','NOT SCHEDULED','NOT EXECUTED','AUTHORIZED INPUT','PROHIBITED INPUT','PERMISSION NOT GRANTED','PLANNED RUN','COMPLETED RUN — SYNTHETIC HISTORY','FAILED RUN','SKIPPED — NOT PASSED','CONDITION NOT MET — NOT A FAILURE','NOTIFICATION SUPPRESSED','NOTIFICATION ELIGIBLE — NOT SENT','BOUNDED RETRY','DUPLICATE RUN PROHIBITED','IDEMPOTENCY KEY — SYNTHETIC','STALE RUN EVIDENCE — DO NOT USE','PAUSE RECOMMENDED','PAUSE AUTHORITY — HUMAN ONLY','MANUAL OVERRIDE','EXECUTION WITHHELD','HUMAN-APPROVED SCHEDULED OPERATION RUNBOOK','VISUAL REFERENCE ONLY','NO LIVE SCHEDULING, BACKGROUND EXECUTION, ACCOUNT ACCESS, OR NOTIFICATION']
persistent=['NOT SCHEDULED','NOT EXECUTED','CONDITION NOT MET','SKIPPED — NOT PASSED','NOTIFICATION SUPPRESSED','DUPLICATE RUN PROHIBITED','PAUSE AUTHORITY — HUMAN ONLY','EXECUTION WITHHELD']
checks={
'exact_states': [x.get('data-state') for x in panels]==states,
'tabs_7':len(tabs)==7,'panels_7':len(panels)==7,
'unique_tab_ids':len({x.get('id') for x in tabs})==7,
'unique_panel_ids':len({x.get('id') for x in panels})==7,
'reciprocal_aria':all(t.get('aria-controls')==pnl.get('id') and pnl.get('aria-labelledby')==t.get('id') for t,pnl in zip(tabs,panels)),
'keyboard_contract':all(k in JS for k in ['ArrowRight','ArrowLeft','Home','End']),
'asset_count_at_least_8':len(list((ROOT/'assets/images').glob('*.svg')))>=8,
'local_assets_exist':not missing,
'external_runtime_zero':not re.search(r'(https?:)?//',HTML+CSS+JS),
'required_labels':all(x in HTML for x in required),
'persistent_8':all(x in HTML[HTML.index('data-persistent-boundaries'):] for x in persistent),
'final_animationend':"animationend" in JS and "runbookComplete" in JS,
'no_timeout_completion':'setTimeout' not in JS,
'nominal_780':'nominalMotionMs:780' in JS and '660ms' in CSS and '120ms' in CSS,
'reduced_motion':'prefers-reduced-motion:reduce' in CSS and 'reduce.matches' in JS,
'mobile_390':'390px' in HTML and 'width:min(390px,100%)' in CSS,
'manifest_columns':all(x in (ROOT/'IMAGE_SOURCES.md').read_text() for x in ['Asset type','Role','Source / ownership','Licence basis','Creation date','Intended use'])
}
result={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'missing':missing,'states':states,'asset_count':len(list((ROOT/'assets/images').glob('*.svg')))}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(0 if result['status']=='PASS' else 1)
