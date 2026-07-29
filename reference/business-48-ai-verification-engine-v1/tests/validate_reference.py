from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
states=re.findall(r'data-state="([^"]+)"',html)
controls=re.findall(r'data-state-control="([^"]+)"',html)
expected=['cover','submission','claims','checks','evidence','decision','mobile']
labels=['SYNTHETIC ARTIFACT','SUBMITTED ARTIFACT','EXACT ARTIFACT VERSION','WORKER CLAIM — UNVERIFIED','IMPLEMENTATION SELF-CHECK','ACCEPTANCE CRITERIA','INDEPENDENT CHECK','PASSED CHECK','FAILED CHECK','SKIPPED — NOT PASSED','UNAVAILABLE EVIDENCE','EVIDENCE REFERENCE','EXACT VERSION MATCH','STALE EVIDENCE — DO NOT USE','EXCEPTION','RESIDUAL CONDITION','VALIDATOR VERDICT','HUMAN APPROVAL — SEPARATE AUTHORITY','APPROVAL SCOPE LIMITED','NO UNIVERSAL CERTIFICATION','DEPLOYMENT NOT AUTHORIZED','HUMAN-APPROVED VERIFICATION RECORD','VISUAL REFERENCE ONLY','NO LIVE TEST, REPOSITORY, MERGE, OR DEPLOYMENT CONNECTION']
assets=list((ROOT/'assets/images').glob('*.svg'))
manifest=(ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
checks={'states':states==expected,'controls':controls==expected,'assets':len(assets)>=8,'focal_assets':all((ROOT/'assets/images'/x).exists() for x in ['exact-version-calibration-plate.svg','independent-check-rig.svg','residual-condition-envelope.svg']),'labels':all(x in html for x in labels),'documented':all(a.name in manifest for a in assets),'local_runtime':not re.search(r'(?:src|href)="https?://|//cdn',html+css+js),'version':'ave-v1-20260729' in html,'animationend':'animationend' in js and 'briefComplete' in js,'no_timeout':'setTimeout' not in js,'reduced_motion':'prefers-reduced-motion' in css,'no_live_capabilities':not re.search(r'getUserMedia|geolocation|WebSocket|fetch\(|XMLHttpRequest|localStorage|sessionStorage',js)}
assert all(checks.values()),checks
out={'status':'PASS','checks':checks,'states':states,'assets':len(assets)}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
