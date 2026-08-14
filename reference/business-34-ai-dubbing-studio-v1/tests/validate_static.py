from pathlib import Path
import re, subprocess, json, sys
root=Path(__file__).resolve().parents[1]
html=(root/'index.html').read_text()
css=(root/'styles/main.css').read_text()
js=(root/'scripts/review.js').read_text()
keys=['cover','source','transcript','translation','voice','sync-review','mobile']
labels=['SYNTHETIC AUDIOVISUAL SOURCE','SOURCE RIGHTS VERIFIED — SYNTHETIC','SOURCE SPEAKER — FICTIONAL','MACHINE TRANSCRIPT','TRANSCRIPT CORRECTION','DRAFT TRANSLATION','HUMAN-REVIEWED TRANSLATION','SYNTHETIC VOICE — AUTHORIZED','NO REAL-PERSON VOICE CLONING','PRONUNCIATION NOTE','TIMING DRIFT','LIP-SYNC PREVIEW','RELEASE EXCEPTION','NOT APPROVED FOR RELEASE','HUMAN-APPROVED LOCALIZED MASTER','VISUAL REFERENCE ONLY','NO LIVE UPLOAD, GENERATION, OR VOICE CLONING']
checks={}
checks['exact_states']=re.findall(r'role="tab"[^>]*data-state="([^"]+)"',html)==keys
checks['exact_panels']=re.findall(r'role="tabpanel"[^>]*data-state="([^"]+)"',html)==keys
checks['seven_controls']=html.count('role="tab"')==7
checks['local_css_js']='styles/main.css?v=20260729-b34-1' in html and 'scripts/review.js?v=20260729-b34-1' in html
checks['no_external_runtime']=not re.search(r'https?://|//cdn|<iframe|<video|<audio',html+css+js,re.I)
checks['labels']=all(x in html for x in labels)
checks['trust_boundaries']=all(x in html for x in ['SOURCE RIGHTS VERIFIED — SYNTHETIC','SOURCE SPEAKER — FICTIONAL','SYNTHETIC VOICE — AUTHORIZED','NO REAL-PERSON VOICE CLONING'])
checks['asset_count']=len(list((root/'assets/images').glob('*.svg')))>=11
checks['assets_exist']=all((root/p).exists() for p in re.findall(r'(assets/images/[^?\"]+\.svg)',html))
manifest=(root/'IMAGE_SOURCES.md').read_text()
checks['assets_documented']=all(f'assets/images/{p.name}' in manifest for p in (root/'assets/images').glob('*.svg'))
checks['responsive']='@media(max-width:560px)' in css and '390' in html
checks['reduced_motion']='prefers-reduced-motion:reduce' in css and 'matchMedia' in js
checks['roving']='tabIndex=on?0:-1' in js
checks['replay_reset']="classList.remove('running','complete')" in js
checks['animationend']="addEventListener('animationend'" in js and "animationName!=='masterSeal'" in js
checks['no_timeout']='setTimeout' not in js and 'setInterval' not in js
checks['persistent']=all(x in html for x in ['TIMING DRIFT','RELEASE EXCEPTION','SYNTHETIC VOICE — AUTHORIZED'])
checks['timing']='690ms' in css and '90ms' in css
node=subprocess.run(['node','--check',str(root/'scripts/review.js')],capture_output=True,text=True)
checks['javascript_syntax']=node.returncode==0
bad=[k for k,v in checks.items() if not v]
result={'result':'STATIC_SELF_CHECK_PASS' if not bad else 'STATIC_SELF_CHECK_FAIL','checks':len(checks),'failed':bad,'javascript_syntax':'PASS' if node.returncode==0 else node.stderr}
(root/'evidence/static-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(1 if bad else 0)
