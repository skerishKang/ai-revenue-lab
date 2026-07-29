from pathlib import Path
import json,re,sys
root=Path(__file__).resolve().parents[1]
html=(root/'index.html').read_text()
css=(root/'styles/main.css').read_text()
js=(root/'scripts/review.js').read_text()
expected=['cover','host','contract','permissions','fallback','decision','mobile']
states=re.findall(r'<section[^>]+data-state="([^"]+)"',html)
controls=re.findall(r'data-state-control="([^"]+)"',html)
tabs=re.findall(r'<button id="([^"]+)" role="tab"[^>]+data-state-control="([^"]+)"[^>]+aria-controls="([^"]+)"',html)
panels=re.findall(r'<section id="([^"]+)"[^>]+data-state="([^"]+)"[^>]+role="tabpanel" aria-labelledby="([^"]+)"',html)
labels=['HOST PRODUCT — FICTIONAL','EMBEDDED CAPABILITY — SYNTHETIC','HOST AUTHORITY','SDK INTEGRATION BOUNDARY','INPUT CONTRACT','OUTPUT CONTRACT','ACCEPTED INPUT','REJECTED INPUT','DATA MINIMIZATION','PERMISSION REQUIRED — NOT GRANTED','SDK VERSION — SYNTHETIC','HOST COMPATIBILITY — LIMITED','MODEL/PROVIDER — NOT CONNECTED','FAIL-CLOSED FALLBACK','TIMEOUT — NO HOST MUTATION','INSTALLATION NOT PERFORMED','EXECUTION NOT PERFORMED','HUMAN RELEASE AUTHORITY','HUMAN-APPROVED EMBEDDED AI INTEGRATION SPEC','VISUAL REFERENCE ONLY','NO LIVE HOST, SDK, MODEL, ACCOUNT, OR CREDENTIAL CONNECTION']
assets=sorted((root/'assets/images').glob('*.svg'))
manifest=(root/'IMAGE_SOURCES.md').read_text()
tab_map={state:(tab,panel) for tab,state,panel in tabs}
panel_map={state:(panel,tab) for panel,state,tab in panels}
reciprocal=all(state in tab_map and state in panel_map and tab_map[state][0]==panel_map[state][1] and tab_map[state][1]==panel_map[state][0] for state in expected)
forbidden=['INSTALLATION COMPLETE','PERMISSION GRANTED','MODEL CONNECTED','PROVIDER CONNECTED','EXECUTION COMPLETE','HOST MODIFIED','READY FOR PRODUCTION']
checks={
'exact_states':states==expected,
'exact_controls':controls==expected,
'at_relationships_7_of_7':len(tabs)==7 and len(panels)==7 and reciprocal,
'unique_ids':len({x[0] for x in tabs}|{x[0] for x in panels})==14,
'required_labels':all(x in html for x in labels),
'forbidden_implications_absent':not any(x in html for x in forbidden),
'asset_count':len(assets)>=8,
'all_assets_documented':all(a.name in manifest for a in assets),
'local_runtime':not re.search(r'(?:src|href)="https?://',html),
'animationend':'animationend' in js and 'integrationSpecComplete' in js,
'no_fixed_timeout':'setTimeout' not in js,
'timing_invariant':'650ms' in css and '.11s' in css,
'reduced_motion':'prefers-reduced-motion' in css,
'keyboard_contract':all(k in js for k in ['ArrowRight','ArrowLeft','Home','End','Enter',"event.key === ' '"]),
'persistent_boundaries':all(x in html for x in ['PERMISSION REQUIRED — NOT GRANTED','INSTALLATION NOT PERFORMED','EXECUTION NOT PERFORMED','MODEL/PROVIDER — NOT CONNECTED']),
'matrix_contract':all(x in (root/'README.md').read_text() for x in ['1440×1100','768×1024','390×844','21 combinations'])
}
out={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'states':states,'controls':controls,'assets':len(assets),'labels':len(labels)}
(root/'evidence/static-self-check.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
print(json.dumps(out,indent=2,ensure_ascii=False))
sys.exit(0 if out['status']=='PASS' else 1)
