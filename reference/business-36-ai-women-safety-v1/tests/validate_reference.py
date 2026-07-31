from pathlib import Path
import json,re,sys
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'index.html').read_text(encoding='utf-8')
JS=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
CSS=(ROOT/'styles/main.css').read_text(encoding='utf-8')
STATES=['cover','situation','signals','options','support','handoff','mobile']
LABELS=['SYNTHETIC PERSONAL-SAFETY SCENARIO','USER ACCOUNT — UNVERIFIED','OBSERVABLE CONTEXT — SYNTHETIC','INTERPRETATION — NOT VERIFIED FACT','UNCERTAIN CONCERN','MISSING EVIDENCE','USER CHOICE','BOUNDED RESPONSE OPTION','TRUSTED CONTACT','CHECK-IN PLAN','ACCESSIBILITY CONSTRAINT','EVIDENCE-PRESERVATION BOUNDARY','NO CRIME OR PERSON-RISK INFERENCE','NOT A GUARANTEE OF SAFETY','EMERGENCY RESPONSE OUT OF SCOPE','UNRESOLVED UNCERTAINTY','HUMAN-REVIEWED SAFETY RESPONSE BRIEF','VISUAL REFERENCE ONLY','NO LIVE LOCATION, SURVEILLANCE, OR EMERGENCY EXECUTION']
errors=[]
found_states=re.findall(r'data-state="([^"]+)"',HTML)
if found_states!=STATES: errors.append(f'exact states mismatch: {found_states}')
controls=re.findall(r'data-state-control="([^"]+)"',HTML)
if controls!=STATES: errors.append(f'control states mismatch: {controls}')
for label in LABELS:
    if label not in HTML: errors.append(f'missing label: {label}')
assets=re.findall(r'<img[^>]+src="([^"]+\.svg)(?:\?[^\"]+)?"',HTML)
unique=sorted(set(assets))
if len(unique)<11: errors.append(f'local svg count {len(unique)} < 11')
for rel in unique:
    if not (ROOT/rel).is_file(): errors.append(f'missing asset: {rel}')
for path in ROOT.rglob('*'):
    if path.is_file() and path.suffix in {'.html','.css','.js','.md','.py','.svg','.json'}:
        text=path.read_text(encoding='utf-8')
        if re.search(r'(?:src|href)=["\']https?://',text): errors.append(f'external runtime URL in {path.relative_to(ROOT)}')
if 'setTimeout' in JS: errors.append('fixed timeout present in review.js')
if "animationend" not in JS or "briefComplete" not in JS: errors.append('final animationend authority missing')
if '760ms' not in CSS: errors.append('760ms nominal duration missing')
for forbidden in ['risk score','danger score','face recognition','live location API']:
    if forbidden.lower() in HTML.lower(): errors.append(f'forbidden pattern: {forbidden}')
result={'status':'PASS' if not errors else 'FAIL','states':found_states,'svg_assets':len(unique),'required_labels':len(LABELS),'external_runtime_requests_declared':0,'errors':errors}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(1 if errors else 0)
