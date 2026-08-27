from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
states=re.findall(r'data-state="([^"]+)"',html)
controls=re.findall(r'data-state-control="([^"]+)"',html)
expected=['cover','language','situation','location','critical','handoff','mobile']
assets=sorted((ROOT/'assets/images').glob('*.svg'))
labels=['SYNTHETIC EMERGENCY-REPORTING SCENARIO','FOREIGN-LANGUAGE USER — FICTIONAL','PREFERRED LANGUAGE — SYNTHETIC','LANGUAGE ASSISTANCE — NOT CERTIFIED INTERPRETATION','USER STATEMENT — UNVERIFIED','OBSERVABLE FACT — SYNTHETIC','UNKNOWN / UNCONFIRMED','LOCATION — PARTIALLY KNOWN','LOCATION — NOT LIVE OR VERIFIED','IMMEDIATE NEED — USER REPORTED','CRITICAL FACT','COMMUNICATION SUPPORT','ACCESSIBILITY NEED','PLAIN-LANGUAGE REPORTING SEQUENCE','REPORTING PREPARATION ONLY','NO URGENCY OR THREAT CLASSIFICATION','NO MEDICAL, POLICE, FIRE, OR LEGAL ADVICE','NO LIVE CALL, CHAT, LOCATION, OR DISPATCH','OFFICIAL EMERGENCY-SERVICE HANDOFF REQUIRED','HUMAN-READY EMERGENCY REPORTING BRIEF','VISUAL REFERENCE ONLY']
forbidden_runtime=['navigator.geolocation','getUserMedia','MediaRecorder','WebSocket','EventSource','fetch(','XMLHttpRequest','localStorage','sessionStorage','indexedDB']
checks={
 'states_exact':states==expected,
 'controls_exact':controls==expected,
 'selected_initial_exactly_one':html.count('aria-selected="true"')==1,
 'assets_exactly_11':len(assets)==11,
 'authority_labels':all(label in html for label in labels),
 'local_runtime':not re.search(r'https?://|//cdn',html+css+js),
 'no_external_api':not any(token in js for token in forbidden_runtime),
 'no_fixed_timeout':'setTimeout' not in js and 'setInterval' not in js,
 'reduced_motion':'prefers-reduced-motion' in css,
 'animationend_authority':'animationend' in js and 'briefComplete' in js and "complete('animationend')" in js,
 'nominal_770ms':'120ms 650ms' in css,
 'version_token':'fea-v1-20260729' in html,
 'semantic_tabs':all(token in html for token in ['role="tablist"','role="tab"','role="tabpanel"','aria-controls=','aria-labelledby=']),
 'multilingual_markup':all(token in html for token in ['lang="es"','lang="ko"']),
 'documented_assets':all(asset.name in (ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8') for asset in assets),
 'required_docs':all((ROOT/name).exists() for name in ['README.md','REFERENCE_NOTES.md','IMAGE_SOURCES.md','MOTION_SPEC.md']),
 'no_functional_call_button':not re.search(r'<button[^>]*>[^<]*(call|전화|신고)',html,re.I),
 'no_map_or_live_media_elements':not any(tag in html for tag in ['<audio','<video','<canvas','<iframe'])
}
assert all(checks.values()),checks
out={'status':'PASS','checks':checks,'states':states,'assets':len(assets),'asset_names':[a.name for a in assets]}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
