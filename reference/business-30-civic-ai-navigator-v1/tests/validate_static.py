from pathlib import Path
import json, re, subprocess, sys
ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT/'index.html').read_text(encoding='utf-8')
CSS = (ROOT/'styles/main.css').read_text(encoding='utf-8')
JS = (ROOT/'scripts/review.js').read_text(encoding='utf-8')
MANIFEST = (ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
KEYS = ['cover','question','source-map','procedure','branches','draft','mobile']
TRUST = ['OFFICIAL SOURCE','CITIZEN-FRIENDLY EXPLANATION','JURISDICTION CHECK','FRESHNESS CHECK','POSSIBLE EXCEPTION','HUMAN CONFIRMATION REQUIRED','DRAFT — NOT SUBMITTED','SYNTHETIC EXAMPLE']
DISCLOSURES = ['SYNTHETIC CIVIC GUIDANCE','VISUAL REFERENCE ONLY','NOT LEGAL OR ADMINISTRATIVE ADVICE','NO REAL SUBMISSION OR GOVERNMENT CONNECTION']
results = {}
def check(name, condition):
    results[name] = bool(condition)
    if not condition: print('FAIL', name)

states = re.findall(r'<section[^>]+data-state="([^"]+)"', HTML)
controls = re.findall(r'<button[^>]+role="tab"[^>]+data-state="([^"]+)"', HTML)
check('exact_seven_states', states == KEYS)
check('exact_seven_controls', controls == KEYS)
check('local_css', 'href="styles/main.css?v=civic30-20260728-1"' in HTML)
check('local_js', 'src="scripts/review.js?v=civic30-20260728-1"' in HTML)
check('no_external_runtime', not re.search(r'(?:src|href)="https?://', HTML))
assets = re.findall(r'src="(assets/images/[^"]+)"', HTML)
check('runtime_assets_exist', all((ROOT/p).is_file() for p in assets))
all_assets = sorted((ROOT/'assets/images').glob('*.svg'))
check('minimum_ten_assets', len(all_assets) >= 10)
check('all_assets_documented', all(str(p.relative_to(ROOT)).replace('\\','/') in MANIFEST for p in all_assets))
check('trust_labels', all(label in HTML for label in TRUST))
check('synthetic_disclosures', all(label in HTML for label in DISCLOSURES))
check('responsive_rules', '@media (max-width:980px)' in CSS and '@media (max-width:620px)' in CSS)
check('reduced_motion', '@media (prefers-reduced-motion: reduce)' in CSS and 'reduced.matches' in JS)
check('animationend_authority', "seal.addEventListener('animationend'" in JS and "event.animationName === 'routeSeal'" in JS)
check('replay_reset', "route.classList.remove('complete', 'running')" in JS and "void route.offsetWidth" in JS)
check('no_fixed_completion_timeout', 'setTimeout' not in JS and 'setInterval' not in JS)
check('persistent_exception_human', '.exception-node' in CSS and '.human-node' in CSS and 'display:none' not in CSS[CSS.find('.exception-node'):CSS.find('.exception-node')+200])
node = subprocess.run(['node','--check',str(ROOT/'scripts/review.js')], capture_output=True, text=True)
check('javascript_syntax', node.returncode == 0)
git_root = ROOT.parents[1]
diff = subprocess.run(['git','-C',str(git_root),'diff','--cached','--check'], capture_output=True, text=True)
check('git_diff_check', diff.returncode == 0)
output = {'result':'STATIC_SELF_CHECK_PASS' if all(results.values()) else 'STATIC_SELF_CHECK_FAIL','checks':results,'asset_count':len(all_assets),'state_keys':states}
(ROOT/'evidence/static-self-check.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(output, ensure_ascii=False, indent=2))
sys.exit(0 if all(results.values()) else 1)
