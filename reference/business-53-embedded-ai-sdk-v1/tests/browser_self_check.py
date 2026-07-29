from pathlib import Path
import base64
import hashlib
import http.server
import json
import socketserver
import threading
import urllib.request
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
assets = sorted((root / 'assets/images').glob('*.svg'))

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

handler = lambda *args, **kwargs: Quiet(*args, directory=str(root), **kwargs)
server = socketserver.TCPServer(('127.0.0.1', 0), handler)
port = server.server_address[1]
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

states = ['cover', 'host', 'capability', 'context', 'boundary', 'package', 'mobile']
viewports = [(1440, 1100), (768, 1024), (390, 844)]
http_results = {}
for path in ['index.html', 'styles/main.css', 'scripts/review.js'] + [f'assets/images/{a.name}' for a in assets]:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/{path}', timeout=5) as response:
        http_results[path] = response.status

html = (root / 'index.html').read_text(encoding='utf-8')
css = (root / 'styles/main.css').read_text(encoding='utf-8')
js = (root / 'scripts/review.js').read_text(encoding='utf-8')
for asset in assets:
    data = base64.b64encode(asset.read_bytes()).decode('ascii')
    html = html.replace(f'assets/images/{asset.name}?v=easdk-v1', f'data:image/svg+xml;base64,{data}')
html = html.replace('<link rel="stylesheet" href="styles/main.css?v=easdk-v1-20260730">', f'<style>{css}</style>')
html = html.replace('<script src="scripts/review.js?v=easdk-v1-20260730"></script>', f'<script>{js}</script>')

failures = []
console_errors = []
page_errors = []
external_requests = []
keyboard = {}
motion = {}
reduced = {}
mobile = {}

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
    page = browser.new_page()
    page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
    page.on('pageerror', lambda exc: page_errors.append(str(exc)))
    page.on('request', lambda req: external_requests.append(req.url) if not req.url.startswith('data:') else None)

    for width, height in viewports:
        page.set_viewport_size({'width': width, 'height': height})
        page.set_content(html, wait_until='load')
        for state in states:
            page.locator(f'[data-state-control="{state}"]').click()
            info = page.evaluate("""state => {
              const panels=[...document.querySelectorAll('[data-state]')];
              const tabs=[...document.querySelectorAll('[data-state-control]')];
              const visible=panels.filter(p=>!p.hidden&&getComputedStyle(p).display!=='none');
              const selected=tabs.filter(t=>t.getAttribute('aria-selected')==='true');
              const active=visible[0];
              const rects=active?[...active.querySelectorAll('.label,.state-heading>span,code,.boundary-ledger span,.persistent-boundaries span')].map(e=>{const r=e.getBoundingClientRect();return {l:r.left,r:r.right,w:r.width,h:r.height,t:e.textContent.trim()}}):[];
              const at=tabs.every(t=>{const p=document.getElementById(t.getAttribute('aria-controls'));return p&&p.getAttribute('aria-labelledby')===t.id});
              return {visible:visible.map(p=>p.dataset.state),selected:selected.map(t=>t.dataset.stateControl),overflow:document.documentElement.scrollWidth-innerWidth,bad:rects.filter(r=>r.l<-.5||r.r>innerWidth+.5||r.w<1||r.h<1),at};
            }""", state)
            if info['visible'] != [state] or info['selected'] != [state] or info['overflow'] > 0 or info['bad'] or not info['at']:
                failures.append({'viewport': [width, height], 'state': state, 'info': info})

    page.set_viewport_size({'width': 1440, 'height': 1100})
    page.set_content(html, wait_until='load')
    page.locator('[data-state-control="cover"]').focus()
    page.keyboard.press('ArrowRight')
    arrow = page.locator('[data-state-control="host"]').get_attribute('aria-selected') == 'true'
    page.keyboard.press('End')
    end = page.locator('[data-state-control="mobile"]').get_attribute('aria-selected') == 'true'
    page.keyboard.press('Home')
    home = page.locator('[data-state-control="cover"]').get_attribute('aria-selected') == 'true'
    page.locator('[data-state-control="capability"]').focus(); page.keyboard.press('Enter')
    enter = page.locator('[data-state-control="capability"]').get_attribute('aria-selected') == 'true'
    page.locator('[data-state-control="context"]').focus(); page.keyboard.press('Space')
    space = page.locator('[data-state-control="context"]').get_attribute('aria-selected') == 'true'
    keyboard = {'arrow': arrow, 'end': end, 'home': home, 'enter': enter, 'space': space}

    page.locator('[data-state-control="package"]').click()
    replay = page.locator('[data-motion-replay]')
    replay.focus()
    page.evaluate('window.scrollTo(0, 120)')

    def run_once():
        before = page.evaluate("""() => {const e=document.querySelector('.integration-contract-binder'),r=e.getBoundingClientRect();return {focus:document.activeElement===document.querySelector('[data-motion-replay]'),scrollY,rect:[r.x,r.y,r.width,r.height]}}""")
        replay.click()
        page.wait_for_function("document.querySelector('[data-embed-trace]').dataset.motionState==='complete'", timeout=2500)
        after = page.evaluate("""() => {const e=document.querySelector('.integration-contract-binder'),s=getComputedStyle(e),r=e.getBoundingClientRect();return {opacity:s.opacity,transform:s.transform,focus:document.activeElement===document.querySelector('[data-motion-replay]'),scrollY,rect:[r.x,r.y,r.width,r.height],animations:document.getAnimations().filter(a=>a.playState==='running').length}}""")
        return before, after

    replay.click()
    timing = page.evaluate("""() => {const e=document.querySelector('.integration-contract-binder'),s=getComputedStyle(e);return {name:s.animationName,end:(parseFloat(s.animationDelay)+parseFloat(s.animationDuration))*1000}}""")
    page.wait_for_function("document.querySelector('[data-embed-trace]').dataset.motionState==='complete'", timeout=2500)
    b1, a1 = run_once(); shot1 = page.screenshot(); b2, a2 = run_once(); shot2 = page.screenshot()
    motion = {
        'animation_name': timing['name'],
        'computed_end_ms': timing['end'],
        'style_equal': all(a1[k] == a2[k] for k in ['opacity', 'transform']),
        'screenshot_equal': hashlib.sha256(shot1).hexdigest() == hashlib.sha256(shot2).hexdigest(),
        'geometry_equal': a1['rect'] == a2['rect'],
        'focus_stable': b1['focus'] and a1['focus'] and b2['focus'] and a2['focus'],
        'scroll_stable': abs(b1['scrollY']-a1['scrollY']) < 1 and abs(b2['scrollY']-a2['scrollY']) < 1,
        'completion_animations_running': a2['animations']
    }

    page.emulate_media(reduced_motion='reduce')
    replay.click()
    reduced = page.evaluate("""() => ({state:document.querySelector('[data-embed-trace]').dataset.motionState,visible:[...document.querySelectorAll('.trace-node,.integration-contract-binder')].every(e=>getComputedStyle(e).opacity==='1')})""")

    page.set_viewport_size({'width': 390, 'height': 844})
    page.set_content(html, wait_until='load')
    page.locator('[data-state-control="mobile"]').click()
    mobile = page.evaluate("""() => {const e=document.querySelector('.phone-brief'),r=e.getBoundingClientRect(),t=e.innerText;return {right:r.right,bottom:r.bottom,required:['HOST PRODUCT','MOUNT POINT','APPROVED CAPABILITY','HOST CONTEXT','NOT GRANTED','HUMAN CONFIRMATION','FAIL CLOSED','NOT INSTALLED','NOT EXECUTED'].every(x=>t.includes(x))}}""")
    browser.close()

server.shutdown(); server.server_close()

ok = (
    not failures and all(v == 200 for v in http_results.values()) and not console_errors and
    not page_errors and not external_requests and all(keyboard.values()) and
    motion.get('animation_name') == 'embedContractComplete' and 700 <= motion.get('computed_end_ms', 0) <= 800 and
    motion.get('style_equal') and motion.get('screenshot_equal') and motion.get('geometry_equal') and
    motion.get('focus_stable') and motion.get('scroll_stable') and motion.get('completion_animations_running') == 0 and
    reduced.get('state') == 'complete' and reduced.get('visible') and mobile.get('required') and mobile.get('right', 999) <= 390.5
)
result = {
    'status': 'PASS' if ok else 'FAIL',
    'declaration': 'IMPLEMENTATION_BROWSER_SELF_CHECK_ONLY',
    'harness': 'localhost HTTP 200 readback plus exact local bytes inline in Chromium because loopback navigation is administratively blocked',
    'matrix': {'states': 7, 'viewports': 3, 'combinations': 21, 'sizes': viewports},
    'failures': failures,
    'http_results': http_results,
    'console_errors': console_errors,
    'page_errors': page_errors,
    'external_requests': external_requests,
    'keyboard': keyboard,
    'motion': motion,
    'reduced_motion': reduced,
    'mobile': mobile
}
(root / 'evidence/browser-self-check.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps(result, indent=2, ensure_ascii=False))
raise SystemExit(0 if ok else 1)
