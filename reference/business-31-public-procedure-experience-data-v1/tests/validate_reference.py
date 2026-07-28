from pathlib import Path
import re, json, sys
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
states=['cover','procedure','citizen','staff','evidence','improvement','mobile']
controls=re.findall(r'data-state-control="([^"]+)"',html)
panels=re.findall(r'data-state="([^"]+)"',html)
assert controls==states,controls
assert panels==states,panels
for notice in ['SYNTHETIC PUBLIC-PROCEDURE DATA','VISUAL REFERENCE ONLY','NO REAL CITIZEN OR STAFF RECORDS','NOT A GOVERNMENT PERFORMANCE ASSESSMENT']:
 assert notice in html,notice
for label in ['OFFICIAL PROCEDURE','CITIZEN EXPERIENCE — SYNTHETIC','STAFF EXPERIENCE — SYNTHETIC','FIELD EVIDENCE','EDITORIAL INFERENCE','UNVERIFIED','CONTRADICTION','MISSING EVIDENCE','IMPROVEMENT HYPOTHESIS','HUMAN-REVIEWED FOLLOW-UP']:
 assert label in html,label
assert '@media(prefers-reduced-motion:reduce)' in css
assert 'animationend' in js and 'followUpComplete' in js
assert 'setTimeout' not in js
assert "classList.remove('is-running','is-complete')" in js
assert 'https://' not in html and 'http://' not in html
assets=sorted(p.name for p in (ROOT/'assets/images').glob('*.svg'))
assert len(assets)>=10,len(assets)
manifest=(ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
for name in assets: assert name in manifest,name
refs=re.findall(r'(?:src|href)="([^"]+)"',html)
for ref in refs:
 if ref.startswith('#'): continue
 target=(ROOT/ref).resolve()
 assert target.exists(),ref
result={'status':'PASS','states':states,'controls':controls,'assets':len(assets),'external_runtime':0,'notices':4,'labels':10,'animationend_authority':True,'fixed_timeout':False}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
