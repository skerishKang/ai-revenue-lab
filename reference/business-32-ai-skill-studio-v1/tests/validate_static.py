from pathlib import Path
import re, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'index.html').read_text(encoding='utf-8')
css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
manifest=(ROOT/'IMAGE_SOURCES.md').read_text(encoding='utf-8')
keys=['cover','brief','guided-run','evidence','review','skill-card','mobile']
labels=['SYNTHETIC WORK TASK','REQUIRED INPUT','AI-ASSISTED STEP','HUMAN ACTION','SOURCE EVIDENCE','MISSING EVIDENCE','EXCEPTION','REVIEW CORRECTION','NOT YET APPROVED','HUMAN-APPROVED','VERIFIED ORGANIZATIONAL AI SKILL','VISUAL REFERENCE ONLY','NO LIVE EXECUTION OR ENTERPRISE CONNECTION']
checks=[]
def check(name, cond):
    checks.append((name,bool(cond)))
for k in keys:
    check(f'state:{k}', html.count(f'data-state="{k}"')==2)
check('exact seven controls', html.count('role="tab"')==7)
check('exact seven panels', html.count('role="tabpanel"')==7)
check('local css', 'href="styles/main.css?v=20260729-b32-1"' in html)
check('local js', 'src="scripts/review.js?v=20260729-b32-1"' in html)
check('no external runtime', not re.search(r'https?://', html+css+js))
asset_paths=re.findall(r'(assets/images/[a-z0-9-]+\.svg)',html)
check('assets referenced', len(set(asset_paths))>=10)
check('all assets exist', all((ROOT/p).exists() for p in set(asset_paths)))
check('all assets documented', all(p in manifest for p in set(asset_paths)))
check('11 original svg', len(list((ROOT/'assets/images').glob('*.svg')))>=11)
for label in labels: check(f'label:{label}', label in html)
check('responsive 390', '@media(max-width:520px)' in css)
check('reduced motion', 'prefers-reduced-motion:reduce' in css and 'reduce.matches' in js)
check('roving tabindex', 'tab.tabIndex = selected ? 0 : -1' in js)
check('animationend authority', "addEventListener('animationend'" in js and "event.animationName !== 'skillSeal'" in js)
check('replay reset', "classList.remove('running','complete')" in js)
check('no fixed timeout', 'setTimeout' not in js and 'setInterval' not in js)
check('missing retained', 'MISSING EVIDENCE · 견적 B 보증조건' in html)
check('exception retained', 'EXCEPTION · 긴급 납기 시 규칙 재검토' in html)
node=subprocess.run(['node','--check',str(ROOT/'scripts/review.js')],capture_output=True,text=True)
check('javascript syntax',node.returncode==0)
failed=[n for n,v in checks if not v]
for n,v in checks: print(('PASS' if v else 'FAIL'),n)
if failed: print('FAILED',failed); sys.exit(1)
print('STATIC_SELF_CHECK_PASS',len(checks))
