from pathlib import Path
from bs4 import BeautifulSoup
import json, re
ROOT = Path(__file__).resolve().parents[1]
html = (ROOT/'index.html').read_text(encoding='utf-8')
css = (ROOT/'styles/main.css').read_text(encoding='utf-8')
js = (ROOT/'scripts/review.js').read_text(encoding='utf-8')
soup = BeautifulSoup(html, 'html.parser')
expected = ['cover','requirement','patch','tests','validation','package','mobile']
states = [x.get('data-state') for x in soup.select('[data-state]')]
controls = [x.get('data-state-control') for x in soup.select('[data-state-control]')]
labels = ['SYNTHETIC SOFTWARE PROJECT','REQUIREMENT','ACCEPTANCE CRITERIA','ALLOWED SCOPE','PROHIBITED SCOPE','PATCH PLAN','GENERATED PATCH — SYNTHETIC','REVIEWED PATCH','CHANGED FILE MANIFEST','IMPLEMENTATION SELF-CHECK','TEST EVIDENCE — SYNTHETIC','FAILED CHECK','RERUN RESULT','INDEPENDENT VALIDATION','EXACT HEAD VERIFIED','UNRESOLVED CONDITION','DRAFT PR PACKAGE','NOT MERGED','DEPLOYMENT READINESS — NOT DEPLOYED','HUMAN REVIEW REQUIRED','HUMAN-VERIFIED SOFTWARE DELIVERY PACKAGE','VISUAL REFERENCE ONLY','NO LIVE REPOSITORY, CODE GENERATION, CI, MERGE, OR DEPLOYMENT CONNECTION']
svgs = sorted((ROOT/'assets/images').glob('*.svg'))
fail=[]
if states != expected: fail.append(f'states={states}')
if controls != expected: fail.append(f'controls={controls}')
if len(svgs) < 11: fail.append(f'svgs={len(svgs)}')
text = soup.get_text(' ', strip=True)
for label in labels:
    if label not in text: fail.append(f'missing label: {label}')
for img in soup.select('img[src]'):
    src=img['src'].split('?')[0]
    if not (ROOT/src).exists(): fail.append(f'missing asset: {src}')
if re.search(r'https?://', html+css+js): fail.append('external runtime reference')
if 'setTimeout' in js: fail.append('fixed completion timeout')
if "animationName === 'deliveryPackageComplete'" not in js: fail.append('missing animationend authority')
if '@media(prefers-reduced-motion:reduce)' not in css: fail.append('missing reduced motion')
if '--token:asf-v1-20260729' not in css: fail.append('missing deterministic token')
result={'status':'PASS' if not fail else 'FAIL','states':states,'controls':controls,'svg_count':len(svgs),'required_labels':len(labels),'external_runtime_refs':0 if not re.search(r'https?://',html+css+js) else 1,'failures':fail}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(1 if fail else 0)
