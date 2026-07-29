from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / 'index.html').read_text(encoding='utf-8')
css = (ROOT / 'styles/main.css').read_text(encoding='utf-8')
js = (ROOT / 'scripts/review.js').read_text(encoding='utf-8')

states = re.findall(r'data-state="([^"]+)"', html)
controls = re.findall(r'data-state-control="([^"]+)"', html)
expected = ['cover', 'submission', 'claims', 'checks', 'evidence', 'decision', 'mobile']
labels = [
    'SYNTHETIC ARTIFACT', 'SUBMITTED ARTIFACT', 'EXACT ARTIFACT VERSION',
    'WORKER CLAIM — UNVERIFIED', 'IMPLEMENTATION SELF-CHECK', 'ACCEPTANCE CRITERIA',
    'INDEPENDENT CHECK', 'PASSED CHECK', 'FAILED CHECK', 'SKIPPED — NOT PASSED',
    'UNAVAILABLE EVIDENCE', 'EVIDENCE REFERENCE', 'EXACT VERSION MATCH',
    'STALE EVIDENCE — DO NOT USE', 'EXCEPTION', 'RESIDUAL CONDITION',
    'VALIDATOR VERDICT', 'HUMAN APPROVAL — SEPARATE AUTHORITY',
    'APPROVAL SCOPE LIMITED', 'NO UNIVERSAL CERTIFICATION',
    'DEPLOYMENT NOT AUTHORIZED', 'HUMAN-APPROVED VERIFICATION RECORD',
    'VISUAL REFERENCE ONLY', 'NO LIVE TEST, REPOSITORY, MERGE, OR DEPLOYMENT CONNECTION',
]
persistent_boundaries = [
    'FAILED CHECK', 'SKIPPED — NOT PASSED', 'UNAVAILABLE EVIDENCE',
    'STALE EVIDENCE — DO NOT USE', 'RESIDUAL CONDITION',
    'APPROVAL SCOPE LIMITED', 'NO UNIVERSAL CERTIFICATION',
    'DEPLOYMENT NOT AUTHORIZED',
]

def fragment(pattern: str) -> str:
    match = re.search(pattern, html, re.S)
    assert match, pattern
    return match.group(1)

decision_register = fragment(
    r'<aside class="verification-boundary-register"[^>]*data-persistent-verification-boundaries[^>]*>(.*?)</aside>'
)
mobile_register = fragment(
    r'<section class="mobile-boundary-register"[^>]*data-mobile-verification-boundaries[^>]*>(.*?)</section>'
)
assets = list((ROOT / 'assets/images').glob('*.svg'))
manifest = (ROOT / 'IMAGE_SOURCES.md').read_text(encoding='utf-8')

checks = {
    'states': states == expected,
    'controls': controls == expected,
    'assets_exactly_10': len(assets) == 10,
    'focal_assets': all(
        (ROOT / 'assets/images' / name).exists()
        for name in [
            'exact-version-calibration-plate.svg',
            'independent-check-rig.svg',
            'residual-condition-envelope.svg',
        ]
    ),
    'labels': all(label in html for label in labels),
    'decision_boundary_register_8_of_8': all(
        decision_register.count(label) == 1 for label in persistent_boundaries
    ),
    'mobile_boundary_register_8_of_8': all(
        mobile_register.count(label) == 1 for label in persistent_boundaries
    ),
    'semantic_distinctions': all(
        phrase in html
        for phrase in [
            'not the current validator verdict',
            'remains not passed',
            'unavailable is not failed',
            'unusable for the current exact artifact version',
        ]
    ),
    'persistent_register_styled': all(
        selector in css
        for selector in [
            '.verification-boundary-register',
            '.boundary-register-grid',
            '.mobile-boundary-register',
            '.boundary-label',
        ]
    ),
    'documented': all(asset.name in manifest for asset in assets),
    'local_runtime': not re.search(r'(?:src|href)="https?://|//cdn', html + css + js),
    'version': 'ave-v1-20260729' in html,
    'animationend': 'animationend' in js and 'briefComplete' in js,
    'no_timeout': 'setTimeout' not in js,
    'reduced_motion': 'prefers-reduced-motion' in css,
    'no_live_capabilities': not re.search(
        r'getUserMedia|geolocation|WebSocket|fetch\(|XMLHttpRequest|localStorage|sessionStorage', js
    ),
}
assert all(checks.values()), checks
out = {
    'status': 'PASS',
    'checks': checks,
    'states': states,
    'assets': len(assets),
    'persistent_boundaries': persistent_boundaries,
}
(ROOT / 'evidence/static-self-check.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8'
)
print(json.dumps(out, ensure_ascii=False))
