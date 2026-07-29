from __future__ import annotations
import json,re,sys
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'index.html').read_text(encoding='utf-8')
CSS=''.join((ROOT/'styles'/n).read_text(encoding='utf-8') for n in ['main.css','layout.css','responsive.css'])
JS=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
MANIFEST=(ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
EXPECTED=['cover','work-order','roles','evidence','gates','decision','mobile']
LABELS=['SYNTHETIC SOFTWARE PROJECT','WORK ORDER','PRODUCT AUTHORITY','IMPLEMENTATION WORKER','INDEPENDENT VALIDATOR','HUMAN REVIEWER','EXPECTED BASE','EXACT HEAD','ALLOWED SCOPE','PROHIBITED SCOPE','IMPLEMENTATION REPORT — UNVERIFIED','INDEPENDENT EVIDENCE','STALE EVIDENCE — DO NOT USE','BLOCKER','GATE PENDING','UI APPROVAL','UX NOT AUTHORIZED','BACKEND FROZEN','DEPLOYMENT AUTHORIZED — NOT EXECUTED','MERGEABLE ≠ MERGE AUTHORIZED','NEXT RECOMMENDED ACTION','NEXT AUTHORIZED ACTION','HUMAN-APPROVED DEVELOPMENT CONTROL RECORD','VISUAL REFERENCE ONLY','NO LIVE REPOSITORY, CI, MERGE, OR DEPLOYMENT CONNECTION']

class P(HTMLParser):
    def __init__(self):super().__init__();self.tabs=[];self.panels=[];self.urls=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if a.get('role')=='tab' and 'data-state' in a:self.tabs.append(a['data-state'])
        if a.get('role')=='tabpanel' and 'data-state' in a:self.panels.append(a['data-state'])
        for key in ('src','href'):
            if key in a:self.urls.append(a[key])
p=P();p.feed(HTML)
assets=sorted((ROOT/'assets/images').glob('*.svg'))
checks={
'exact seven controls':p.tabs==EXPECTED,
'exact seven panels':p.panels==EXPECTED,
'exact state uniqueness':len(set(p.tabs))==7 and len(set(p.panels))==7,
'local css and js':all(x in HTML for x in ['styles/main.css?v=20260729-b42-1','scripts/review.js?v=20260729-b42-1']) and all(x in CSS for x in ['layout.css?v=20260729-b42-1','responsive.css?v=20260729-b42-1']),
'fixed asset token':'20260729-b42-1' in HTML and '20260729-b42-1' in CSS,
'no external runtime':not any(re.match(r'^(https?:)?//',u) for u in p.urls),
'eleven original svg assets':len(assets)>=11,
'all assets documented':all(f'`assets/images/{a.name}`' in MANIFEST for a in assets),
'all assets referenced':all(f'assets/images/{a.name}' in HTML for a in assets),
'required authority labels':all(label in HTML for label in LABELS),
'synthetic fixture':all(x in HTML for x in ['Aurora Notes','aurora-notes/app','4ab71d2','98f2c10']),
'role separation':all(x in HTML for x in ['implementation worker to be the independent validator','Cannot','INDEPENDENT VALIDATOR']),
'report not verification':'REPORT ≠ VERIFICATION' in HTML and 'Implementation report만으로 승인할 수 없습니다.' in HTML,
'stale exact head retained':'71dc9e2' in HTML and 'STALE EVIDENCE — DO NOT USE' in HTML,
'authorization execution distinction':'AUTHORIZATION ≠ EXECUTION' in HTML and '배포 완료를 뜻하지 않음' in HTML,
'responsive rules':all(x in CSS for x in ['@media(max-width:1100px)','@media(max-width:820px)','@media(max-width:420px)']),
'reduced motion':'@media(prefers-reduced-motion:reduce)' in CSS and 'reduced.matches' in JS,
'roving tabindex':"tab.tabIndex=selected?0:-1" in JS,
'replay reset':"classList.remove('running','complete')" in JS,
'animationend authority':"addEventListener('animationend'" in JS and "animationName!=='controlSeal'" in JS,
'no fixed completion timeout':'setTimeout' not in JS and 'setInterval' not in JS,
'persistent governance boundaries':all(x in HTML for x in ['STALE EVIDENCE — DO NOT USE','BLOCKER','UX NOT AUTHORIZED','BACKEND FROZEN','MERGEABLE ≠ MERGE AUTHORIZED','DEPLOYMENT AUTHORIZED — NOT EXECUTED']),
'no live runtime semantics':all(x not in HTML.lower() for x in ['<form','type="submit"','fetch(','websocket','iframe']),
}
failed=[k for k,v in checks.items() if not v]
out={'result':'STATIC_SELF_CHECK_PASS' if not failed else 'STATIC_SELF_CHECK_FAIL','checks':len(checks),'passed':sum(checks.values()),'failed':failed}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
sys.exit(1 if failed else 0)
