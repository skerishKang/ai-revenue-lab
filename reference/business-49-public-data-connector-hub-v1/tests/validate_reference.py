from pathlib import Path
import json,re,sys
root=Path(__file__).resolve().parents[1]
html=(root/'index.html').read_text()
css=(root/'styles/main.css').read_text()
js=(root/'scripts/review.js').read_text()
states=re.findall(r'data-state="([^"]+)"',html)
controls=re.findall(r'data-state-control="([^"]+)"',html)
expected=['cover','catalog','source','schema','quality','package','mobile']
labels=['SYNTHETIC PUBLIC DATASET','SOURCE AUTHORITY','OFFICIAL SOURCE — FICTIONAL','UNOFFICIAL MIRROR — NOT USED','ACCESS METHOD — SYNTHETIC','LICENCE STATEMENT — NOT LEGAL ADVICE','SOURCE FIELD','NORMALIZED FIELD','RAW VALUE','TRANSFORMED VALUE','FIELD LINEAGE','PUBLICATION DATE','RETRIEVAL DATE','FRESHNESS — CURRENT','FRESHNESS — STALE','FRESHNESS — UNKNOWN','MISSING ≠ ZERO','VALIDATION CHECK','KNOWN LIMITATION','COVERAGE INCOMPLETE','CONNECTOR READINESS — NOT CONNECTED','NO OFFICIAL ENDORSEMENT','HUMAN-REVIEWED PUBLIC DATA CONNECTOR SPEC','VISUAL REFERENCE ONLY','NO LIVE API, SCRAPING, CREDENTIAL, OR DATA INGESTION']
assets=sorted((root/'assets/images').glob('*.svg'))
checks={
'exact_states':states==expected,
'exact_controls':controls==expected,
'at_roles':html.count('role="tab"')==7 and html.count('role="tabpanel"')==7,
'at_relationship_setup':all(token in js for token in ['state-tab-${key}','state-panel-${key}',"setAttribute('aria-controls'","setAttribute('aria-labelledby'"]),
'asset_count':len(assets)>=8,
'all_assets_documented':all(a.name in (root/'IMAGE_SOURCES.md').read_text() for a in assets),
'required_labels':all(x in html for x in labels),
'asset_token':'pdc-v1-20260729' in html,
'local_runtime':not re.search(r'https?://',html),
'animationend':'animationend' in js and 'connectorSpecComplete' in js,
'no_fixed_timeout':'setTimeout' not in js,
'reduced_motion':'prefers-reduced-motion' in css,
'roving':'tabIndex' in js and 'aria-selected' in js,
'failure_boundaries':all(x in html for x in ['UNOFFICIAL MIRROR — NOT USED','MISSING ≠ ZERO','FRESHNESS — STALE','COVERAGE INCOMPLETE','CONNECTOR READINESS — NOT CONNECTED'])
}
out={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'states':states,'controls':controls,'assets':len(assets),'labels':len(labels)}
(root/'evidence/static-self-check.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))
print(json.dumps(out,indent=2,ensure_ascii=False))
sys.exit(0 if out['status']=='PASS' else 1)
