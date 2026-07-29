from pathlib import Path
import json, re, sys
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
states=['cover','brief','structure','variants','quality','kit','mobile']
required=['SYNTHETIC SOURCE BRIEF','SOURCE RIGHTS VERIFIED — SYNTHETIC','SOURCE MATERIAL','CONTENT STRUCTURE RULE','FORMAT TRANSFORMATION','GENERATED DRAFT — SYNTHETIC','DRAFT VARIANT','HUMAN-REVIEWED VARIANT','FACT CHECK NOT PERFORMED','UNSUPPORTED CLAIM — HOLD','STYLE IMITATION PROHIBITED','QUALITY CHECK','PUBLICATION AUTHORITY WITHHELD','NOT PUBLISHED','HUMAN-APPROVED CONTENT PRODUCTION KIT','VISUAL REFERENCE ONLY','NO LIVE GENERATION, CMS, OR PUBLICATION CONNECTION']
errors=[]
found=re.findall(r'data-state="([^"]+)"',html)
if found!=states: errors.append(f'exact states mismatch: {found}')
controls=re.findall(r'data-state-control="([^"]+)"',html)
if controls!=states: errors.append(f'controls mismatch: {controls}')
for label in required:
    if label not in html: errors.append(f'missing label: {label}')
assets=[p for p in (ROOT/'assets/images').iterdir() if p.suffix.lower() in {'.png','.svg','.jpg','.jpeg','.webp'}]
if len(assets)<8: errors.append('fewer than 8 assets')
focal_names={'foundry-cover-illustration.svg','structure-production-plate.svg','format-variants-proof-sheet.svg','quality-press-check.svg'}
if len(focal_names & {p.name for p in assets})<3: errors.append('fewer than 3 substantial editorial focal assets')
for p in assets:
    if f'assets/images/{p.name}' not in html: errors.append(f'undisplayed asset: {p.name}')
if 'animationend' not in js or 'kitComplete' not in js: errors.append('missing final animationend authority')
if re.search(r'setTimeout|setInterval',js): errors.append('fixed completion timer present')
if '760ms' not in css: errors.append('760ms motion duration missing')
if not re.search(r'prefers-reduced-motion\s*:\s*reduce',css) or "prefers-reduced-motion: reduce" not in js: errors.append('reduced motion incomplete')
if re.search(r'https?://',html+css+js): errors.append('external runtime URL found')
if '?v=ace-v1-20260729' not in html: errors.append('fixed asset version token missing')
manifest=(ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
for p in assets:
    if f'assets/images/{p.name}' not in manifest: errors.append(f'asset undocumented: {p.name}')
result={'status':'PASS' if not errors else 'FAIL','states':states,'state_count':len(states),'asset_count':len(assets),'substantial_focal_count':len(focal_names & {p.name for p in assets}),'required_labels':len(required),'external_runtime_requests':0 if not re.search(r'https?://',html+css+js) else 'found','errors':errors,'independent_local_validation':False}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(0 if not errors else 1)
