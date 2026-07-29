from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parents[1]
html = (root / 'index.html').read_text(encoding='utf-8')
css = (root / 'styles/main.css').read_text(encoding='utf-8')
js = (root / 'scripts/review.js').read_text(encoding='utf-8')
states = re.findall(r'data-state="([^"]+)"', html)
controls = re.findall(r'data-state-control="([^"]+)"', html)
expected = ['cover', 'host', 'capability', 'context', 'boundary', 'package', 'mobile']
assets = sorted((root / 'assets/images').glob('*.svg'))
manifest = (root / 'IMAGE_SOURCES.md').read_text(encoding='utf-8')
required = [
    'SYNTHETIC HOST APPLICATION', 'HOST PRODUCT — UNCHANGED', 'MOUNT POINT — PROPOSED',
    'EMBED SURFACE — STATIC REFERENCE', 'CAPABILITY MANIFEST — SYNTHETIC',
    'APPROVED CAPABILITY', 'PROHIBITED CAPABILITY', 'HOST CONTEXT — EXPLICITLY PROVIDED',
    'SOURCE DATA', 'DERIVED OUTPUT', 'NO DOM SCRAPING', 'NO HIDDEN CONTEXT COLLECTION',
    'EVENT CONTRACT — SYNTHETIC', 'CALLBACK HISTORY — SYNTHETIC',
    'PERMISSION REQUEST — NOT GRANTED', 'HOST ACTION — HUMAN CONFIRMATION REQUIRED',
    'ACTION ELIGIBLE — NOT EXECUTED', 'MODEL / PROVIDER — NOT SELECTED',
    'MODEL ROUTING — OUT OF SCOPE', 'CREDENTIAL — NOT PROVIDED', 'STORAGE — NOT CONNECTED',
    'TELEMETRY — OFF', 'VERSION COMPATIBILITY — REVIEW REQUIRED',
    'ACCESSIBILITY INHERITANCE — REVIEW REQUIRED', 'THEME ISOLATION', 'FAIL CLOSED',
    'FALLBACK TO HOST UI', 'INSTALLATION READINESS — NOT INSTALLED', 'NOT EXECUTED',
    'VISUAL REFERENCE ONLY', 'NO LIVE API, MODEL CALL, CREDENTIAL, STORAGE, TELEMETRY, OR HOST MUTATION',
    'HUMAN-APPROVED EMBEDDED AI INTEGRATION CONTRACT'
]

def reciprocal_at():
    pairs = []
    for state in expected:
        tab = re.search(rf'<button[^>]+id="tab-{state}"[^>]+aria-controls="panel-{state}"[^>]+data-state-control="{state}"', html)
        panel = re.search(rf'<section[^>]+id="panel-{state}"[^>]+role="tabpanel"[^>]+aria-labelledby="tab-{state}"[^>]+data-state="{state}"', html)
        pairs.append(bool(tab and panel))
    return all(pairs) and len(set(re.findall(r'id="([^"]+)"', html))) == len(re.findall(r'id="([^"]+)"', html))

svg_runtime = [re.sub(r'xmlns=\"http://www.w3.org/2000/svg\"', '', a.read_text(encoding='utf-8')) for a in assets]
runtime = '\n'.join([html, css, js] + svg_runtime)
checks = {
    'exact_states': states == expected,
    'exact_controls': controls == expected,
    'reciprocal_at_7_of_7': reciprocal_at(),
    'asset_count_at_least_9': len(assets) >= 9,
    'all_assets_documented': all(a.name in manifest for a in assets),
    'all_assets_referenced': all(a.name in html for a in assets),
    'required_labels': all(label in html for label in required),
    'deterministic_token': 'easdk-v1-20260730' in html,
    'no_external_runtime_urls': not re.search(r'https?://', runtime),
    'no_runtime_io': not re.search(r'\b(fetch|XMLHttpRequest|WebSocket|localStorage|sessionStorage|indexedDB)\b', js),
    'animationend_authority': 'animationend' in js and 'embedContractComplete' in js,
    'no_fixed_timeout': 'setTimeout' not in js and 'setInterval' not in js,
    'timing_invariant': 'animation:embedContractComplete .12s ease 660ms forwards' in css,
    'reduced_motion': 'prefers-reduced-motion:reduce' in css,
    'roving_keyboard': all(x in js for x in ['tabIndex', 'aria-selected', 'ArrowRight', 'ArrowLeft', 'Home', 'End']),
    'no_forms_or_embed_runtime': not re.search(r'<(form|iframe|input|textarea|select)\b', html),
    'line_limits': all(len(p.read_text(encoding='utf-8').splitlines()) <= 500 for p in root.rglob('*') if p.is_file() and p.suffix in {'.html','.css','.js','.py','.md','.svg'})
}
result = {
    'status': 'PASS' if all(checks.values()) else 'FAIL',
    'checks': checks,
    'states': states,
    'controls': controls,
    'assets': len(assets),
    'required_labels': len(required),
    'scope': 'reference/business-53-embedded-ai-sdk-v1/**',
    'declaration': 'IMPLEMENTATION_SELF_CHECK_ONLY'
}
(root / 'evidence/static-self-check.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps(result, indent=2, ensure_ascii=False))
sys.exit(0 if result['status'] == 'PASS' else 1)
