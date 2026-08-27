from pathlib import Path
import json
R=Path(__file__).resolve().parents[1]; errors=[]
required=['index.html','README.md','REFERENCE_NOTES.md','RIGHTS_AND_CONSENT_SPEC.md','VOICE_PROFILE_SPEC.md','MOTION_SPEC.md','IMAGE_SOURCES.md','styles.css','app.js']
for f in required:
 if not (R/f).is_file(): errors.append('missing:'+f)
h=(R/'index.html').read_text(); c=(R/'styles.css').read_text(); j=(R/'app.js').read_text()
for s in ['intake','evidence','profile','translation','generation','contract','trace']:
 if f'data-state="{s}"' not in h or f'data-target="{s}"' not in h: errors.append('state:'+s)
for t in ['업로드는 권리 증명이 아닙니다','REJECTED BY AUTHOR','NOT AUTHOR-APPROVED','CORPUS DELETION RECEIPT','PROFILE / ADAPTER RECEIPT','SOURCE FIDELITY DIVERGENCE','CONSENT SCOPE CHANGE']:
 if t not in h: errors.append('copy:'+t)
for t in ['http://','https://','//cdn','fetch(','gradient(']:
 if t in h+c+j: errors.append('forbidden:'+t)
if 'prefers-reduced-motion:reduce' not in c.replace(' ',''): errors.append('reduced')
result={'status':'pass' if not errors else 'fail','version':'personal-writing-voice-20260728-1','errors':errors}
(R/'evidence').mkdir(exist_ok=True);(R/'evidence/static-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(1 if errors else 0)