from __future__ import annotations
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'index.html').read_text(encoding='utf-8');CSS=(ROOT/'styles/main.css').read_text(encoding='utf-8');JS=(ROOT/'scripts/app.js').read_text(encoding='utf-8')
required=['README.md','REFERENCE_NOTES.md','IMAGE_SOURCES.md','RIGHTS_PRIVACY_AND_REDACTION.md','MOTION_SPEC.md','index.html','styles/main.css','scripts/app.js']
states=['case','intake','chronology','claims','contradiction','folio','mobile'];notices=['SYNTHETIC CASE FILE','AI-ASSISTED DRAFT · HUMAN REVIEW REQUIRED','NOT LEGAL ADVICE','NO OFFICIAL FILING OR SUBMISSION'];truth=['VERIFIED SOURCE METADATA','PARTY STATEMENT','EDITORIAL INFERENCE','CONTRADICTION','UNCERTAIN METADATA','MISSING EVIDENCE','REDACTED INFORMATION','HUMAN-REVIEWED CONCLUSION']
errors=[]
for p in required:
 if not (ROOT/p).is_file():errors.append('missing:'+p)
for s in states:
 if f'data-state="{s}"' not in HTML:errors.append('state:'+s)
 if f'data-state-target="{s}"' not in HTML:errors.append('control:'+s)
for t in notices+truth:
 if t not in HTML:errors.append('text:'+t)
for ref in re.findall(r'(?:src|href)="([^"?#]+)',HTML):
 if ref.startswith('#'):continue
 if not (ROOT/ref).is_file():errors.append('local:'+ref)
runtime=''.join([HTML,CSS,JS])
for token in ['http://','https://','//cdn','fetch(','XMLHttpRequest','WebSocket','@import url']:
 if token in runtime:errors.append('runtime:'+token)
if '@media(prefers-reduced-motion:reduce)' not in CSS.replace(' ',''):errors.append('reduced-motion')
if '@media(max-width:520px)' not in CSS.replace(' ',''):errors.append('390-responsive')
if 'animationend' not in JS or 'review-seal' not in JS:errors.append('motion-completion')
manifest=(ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
for asset in (ROOT/'assets/images').glob('*.svg'):
 rel=asset.relative_to(ROOT).as_posix()
 if rel not in manifest:errors.append('undocumented:'+rel)
result={'status':'pass' if not errors else 'fail','states':states,'notices':notices,'assets':len(list((ROOT/'assets/images').glob('*.svg'))),'errors':errors,'scope':'reference/business-27-evidence-studio-v1/**','validation_boundary':'web static self-check only; Local Validator required'}
print(json.dumps(result,ensure_ascii=False,indent=2))
if errors:raise SystemExit(1)
