from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'index.html').read_text(encoding='utf-8')
CSS = (ROOT / 'styles/main.css').read_text(encoding='utf-8')
JS = (ROOT / 'scripts/review.js').read_text(encoding='utf-8')
MANIFEST = (ROOT / 'IMAGE_SOURCES.md').read_text(encoding='utf-8')
KEYS = ['cover', 'index', 'dossier', 'rationale', 'dissent', 'followup', 'mobile']

def check(name, condition):
    print(('PASS' if condition else 'FAIL'), name)
    if not condition:
        raise SystemExit(1)

states = re.findall(r'data-state-key="([^"]+)"', HTML)
controls = re.findall(r'role="tab"[^>]+data-state="([^"]+)"', HTML)
assets = sorted(set(re.findall(r'assets/images/[A-Za-z0-9._-]+', HTML + CSS)))
check('exact_seven_state_keys', states == KEYS)
check('exact_seven_controls', controls == KEYS)
check('local_css_js', 'styles/main.css?v=decision-archive-20260728-1' in HTML and 'scripts/review.js?v=decision-archive-20260728-1' in HTML)
check('no_external_runtime', not re.search(r'(https?:)?//', HTML) and '@import' not in CSS)
check('all_assets_exist', all((ROOT / asset).is_file() for asset in assets))
check('all_assets_documented', all(asset in MANIFEST for asset in assets))
check('asset_count_at_least_8', len(list((ROOT / 'assets/images').glob('*.svg'))) >= 8)
check('synthetic_disclosure', '모든 자료·인물·수치·발언은 합성' in HTML and '실제 조직·회의·서명·수치가 아닙니다' in HTML)
check('responsive_rules', '@media(max-width:560px)' in CSS and 'width:390px' in CSS)
check('reduced_motion', 'prefers-reduced-motion:reduce' in CSS and "reduced.matches ? 'complete'" in JS)
check('animationend_authority', "seal.addEventListener('animationend'" in JS and "event.animationName !== 'reasonSeal'" in JS)
check('replay_reset', "setMotionState(reduced.matches ? 'complete' : 'idle')" in JS and 'requestAnimationFrame' in JS)
check('no_fixed_timeout', 'setTimeout' not in JS and 'setInterval' not in JS)
check('visible_dissent_assumption_rejected', all(token in HTML for token in ['기각 이유', '반대 의견 여백', '미확인 가정']))
result = subprocess.run(['node', '--check', str(ROOT / 'scripts/review.js')], capture_output=True, text=True)
check('javascript_syntax', result.returncode == 0)
print(f'ASSETS {len(assets)} documented references; {len(list((ROOT / "assets/images").glob("*.svg")))} original SVG files')
