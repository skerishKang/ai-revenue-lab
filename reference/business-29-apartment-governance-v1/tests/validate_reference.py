from pathlib import Path
import re, json
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
states=['cover','meeting','rules','spending','election','complaint','mobile']
notices=['방림명지로드힐 운영 데모','VISUAL REFERENCE ONLY','NOT LEGAL ADVICE','전자투표·계약·결제 기능은 현재 데모 범위 아님']
record_states=['PUBLIC NOTICE','COMMITTEE WORKING RECORD','PRIVATE / REDACTED','RULE BASIS','PROPOSED SPENDING','APPROVED SPENDING','DISSENT / OBJECTION','UNRESOLVED COMPLAINT','RESOLVED FOLLOW-UP','HUMAN-REVIEWED PUBLICATION']
errors=[]
required=['index.html','styles/main.css','scripts/review.js','README.md','REFERENCE_NOTES.md','IMAGE_SOURCES.md','MOTION_SPEC.md']
for p in required:
    if not (ROOT/p).is_file(): errors.append('missing '+p)
for s in states:
    if f'data-state="{s}"' not in html: errors.append('missing state '+s)
    if f'data-state-target="{s}"' not in html: errors.append('missing control '+s)
if len(re.findall(r'data-state="(?:cover|meeting|rules|spending|election|complaint|mobile)"',html))!=7: errors.append('state count')
if len(re.findall(r'data-state-target="(?:cover|meeting|rules|spending|election|complaint|mobile)"',html))!=7: errors.append('control count')
for token in notices+record_states:
    if token not in html: errors.append('missing disclosure '+token)
runtime_text='\n'.join([html,css,js])
for token in ['http://','https://','//cdn','@import','fetch(','XMLHttpRequest','WebSocket']:
    if token in runtime_text: errors.append('external/runtime token '+token)
identity_forbidden=['솔빛마루','Solbit','fictional community','가상 단지','합성 단지','synthetic apartment identity','all community details are synthetic','SYNTHETIC APARTMENT RECORDS']
for token in identity_forbidden:
    if token in runtime_text: errors.append('forbidden identity reference '+token)
identity_required=['방림명지로드힐','192세대','101동','102동','김경애','제5기 입주자대표회의']
for token in identity_required:
    if token not in html: errors.append('missing identity '+token)
if '420' in runtime_text: errors.append('forbidden households 420')
if '데모 예시' not in html: errors.append('missing demo example marker')
refs=re.findall(r'(?:src|href)="([^"?#]+)',html)
for ref in refs:
    if ref.startswith('#'): continue
    if not (ROOT/ref).is_file(): errors.append('missing local ref '+ref)
manifest=(ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
for img in (ROOT/'assets/images').glob('*'):
    rel=img.relative_to(ROOT).as_posix()
    if rel not in manifest: errors.append('undocumented '+rel)
if len(list((ROOT/'assets/images').glob('*.svg')))<8: errors.append('fewer than 8 svg assets')
for token in ['@media(max-width:520px)','prefers-reduced-motion:reduce','publicNoticeComplete']:
    if token.replace(' ','') not in (css+js).replace(' ',''): errors.append('missing '+token)
for token in ["animationend","classList.remove('is-running', 'is-complete')"]:
    if token not in js: errors.append('missing motion contract '+token)
result={'status':'pass' if not errors else 'fail','states':states,'local_refs':len(refs),'svg_assets':len(list((ROOT/'assets/images').glob('*.svg'))),'errors':errors}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(1 if errors else 0)
