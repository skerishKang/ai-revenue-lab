from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread
import base64
import json
import os
import socket
import sys
import urllib.request
from playwright.sync_api import sync_playwright, Error as PlaywrightError

ROOT = Path(__file__).resolve().parents[1]
VIEWPORTS = [(1440, 1100), (768, 1024), (390, 844)]
KEYS = ['cover', 'question', 'source-map', 'procedure', 'branches', 'draft', 'mobile']


def free_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def inline_exact_bytes():
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    css = (ROOT / 'styles/main.css').read_text(encoding='utf-8')
    js = (ROOT / 'scripts/review.js').read_text(encoding='utf-8')
    html = html.replace('<link rel="stylesheet" href="styles/main.css?v=civic30-20260728-1">', f'<style>{css}</style>')
    html = html.replace('<script src="scripts/review.js?v=civic30-20260728-1"></script>', f'<script>{js}</script>')
    for asset in sorted((ROOT / 'assets/images').glob('*.svg')):
        rel = str(asset.relative_to(ROOT)).replace('\\', '/')
        encoded = base64.b64encode(asset.read_bytes()).decode('ascii')
        html = html.replace(rel, f'data:image/svg+xml;base64,{encoded}')
    return html


port = free_port()
os.chdir(ROOT)
server = ThreadingHTTPServer(('127.0.0.1', port), Quiet)
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f'http://127.0.0.1:{port}/'
readback_paths = ['', 'styles/main.css?v=civic30-20260728-1', 'scripts/review.js?v=civic30-20260728-1'] + [str(p.relative_to(ROOT)).replace('\\', '/') for p in sorted((ROOT / 'assets/images').glob('*.svg'))]
http_readback = []
for path in readback_paths:
    with urllib.request.urlopen(base + path, timeout=5) as response:
        http_readback.append({'path': path or 'index.html', 'status': response.status, 'bytes': len(response.read())})
inline_html = inline_exact_bytes()
report = {'harness': 'localhost-http', 'url': base, 'localhost_navigation_error': None, 'http_readback': http_readback, 'viewports': {}, 'motion': {}}


def load_page(page):
    if report['harness'] == 'localhost-http': page.goto(base, wait_until='networkidle')
    else: page.set_content(inline_html, wait_until='load')

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        probe_context = browser.new_context(viewport={'width': 390, 'height': 844})
        probe = probe_context.new_page()
        try: probe.goto(base, wait_until='networkidle')
        except PlaywrightError as error:
            report['harness'] = 'inline-exact-bytes-admin-fallback'
            report['localhost_navigation_error'] = str(error)
        probe_context.close()
        for width, height in VIEWPORTS:
            context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='no-preference')
            page = context.new_page()
            console_errors, page_errors, failed_requests, external_requests = [], [], [], []
            page.on('console', lambda msg, bag=console_errors: bag.append({'type': msg.type, 'text': msg.text}) if msg.type == 'error' else None)
            page.on('pageerror', lambda error, bag=page_errors: bag.append(str(error)))
            page.on('requestfailed', lambda request, bag=failed_requests: bag.append({'url': request.url, 'failure': request.failure}))
            page.on('request', lambda request, bag=external_requests: bag.append(request.url) if request.url.startswith(('http://', 'https://')) and not request.url.startswith(base) else None)
            load_page(page)
            matrix = {}
            for key in KEYS:
                page.locator(f'[role="tab"][data-state="{key}"]').click()
                page.wait_for_timeout(30)
                matrix[key] = page.evaluate("""(key) => { const states=[...document.querySelectorAll('[role=tabpanel]')]; const selected=[...document.querySelectorAll('[role=tab]')].filter(n=>n.getAttribute('aria-selected')==='true').map(n=>n.dataset.state); const active=states.filter(n=>!n.hidden&&getComputedStyle(n).display!=='none').map(n=>n.dataset.state); const images=[...document.images].filter(n=>!n.closest('[hidden]')); const textNodes=[...document.querySelectorAll('[role=tabpanel] h1,[role=tabpanel] h2,[role=tabpanel] h3,[role=tabpanel] p,[role=tabpanel] li,[role=tabpanel] strong,[role=tabpanel] span,[role=tabpanel] small')].filter(n=>n.offsetParent!==null); const clipping=textNodes.filter(n=>n.scrollWidth>n.clientWidth+2||n.scrollHeight>n.clientHeight+2).map(n=>n.textContent.trim().slice(0,60)); const trust=[...document.querySelectorAll('.trust')].every(n=>n.offsetWidth>0&&n.offsetHeight>0); return {key,selected,active,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,assets:images.map(image=>({src:image.getAttribute('src')?.slice(0,80),ok:image.complete&&image.naturalWidth>0})),clipping,trust}; }""", key)
            page.locator('[role="tab"][data-state="cover"]').focus(); page.keyboard.press('ArrowRight')
            keyboard = page.evaluate("""() => ({selected:document.querySelector('[role=tab][aria-selected=true]').dataset.state,focus:document.activeElement.dataset.state,outlineWidth:getComputedStyle(document.activeElement).outlineWidth,outlineStyle:getComputedStyle(document.activeElement).outlineStyle})""")
            report['viewports'][f'{width}x{height}']={'states':matrix,'keyboard':keyboard,'console_errors':console_errors,'page_errors':page_errors,'failed_requests':failed_requests,'external_requests':external_requests}
            context.close()
        context=browser.new_context(viewport={'width':1440,'height':1100}, reduced_motion='no-preference'); page=context.new_page(); load_page(page); page.locator('[data-state="source-map"][role="tab"]').click(); page.locator('#replay-route').focus()
        geometry_js="""() => { const ids=['route-motion','route-seal']; const classes=['official-node','office-node','procedure-node','exception-node','human-node','wrong-node']; const values={}; ids.forEach(id=>{const r=document.getElementById(id).getBoundingClientRect();values[id]=[r.x,r.y,r.width,r.height]}); classes.forEach(name=>{const r=document.querySelector('.'+name).getBoundingClientRect();values[name]=[r.x,r.y,r.width,r.height]}); return values;}"""
        geometry_before=page.evaluate(geometry_js); scroll_before=page.evaluate('scrollY'); runs=[]; timing=None
        for index in range(2):
            page.locator('#replay-route').click(); page.wait_for_function("document.querySelector('#route-motion').dataset.motionState === 'running'")
            if index==0: timing=page.evaluate("""() => { const s=getComputedStyle(document.querySelector('#route-seal')); const durations=s.animationDuration.split(',').map(v=>parseFloat(v)*1000); const delays=s.animationDelay.split(',').map(v=>parseFloat(v)*1000); return {animationName:s.animationName,durations,delays,maxEnd:Math.max(...durations.map((v,i)=>v+(delays[i]??delays[0]??0)))};}""")
            page.wait_for_function("document.querySelector('#route-motion').dataset.motionState === 'complete'", timeout=3000)
            runs.append(page.evaluate("""() => { const seal=getComputedStyle(document.querySelector('#route-seal')); const root=document.querySelector('#route-motion'); return {motion:root.dataset.motionState,sealOpacity:seal.opacity,sealTransform:seal.transform,exceptionVisible:getComputedStyle(document.querySelector('.exception-node')).display!=='none',humanVisible:getComputedStyle(document.querySelector('.human-node')).display!=='none',wrongVisible:getComputedStyle(document.querySelector('.wrong-node')).display!=='none'};}"""))
        report['motion']={'runs':runs,'final_equal':runs[0]==runs[1],'timing':timing,'geometry_equal':geometry_before==page.evaluate(geometry_js),'scroll_before':scroll_before,'scroll_after':page.evaluate('scrollY'),'focus_after':page.evaluate('document.activeElement.id')}; context.close()
        context=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce');page=context.new_page();load_page(page);page.locator('[data-state="source-map"][role="tab"]').click();page.locator('#replay-route').focus();page.locator('#replay-route').click();page.wait_for_timeout(30)
        report['reduced_motion']=page.evaluate("""() => ({state:document.querySelector('#route-motion').dataset.motionState,seal:getComputedStyle(document.querySelector('#route-seal')).opacity,human:getComputedStyle(document.querySelector('.human-node')).display,exception:getComputedStyle(document.querySelector('.exception-node')).display,wrong:getComputedStyle(document.querySelector('.wrong-node')).display,focus:document.activeElement.id})""");context.close();browser.close()
finally:
    server.shutdown();server.server_close()
checks={}
for viewport,entry in report['viewports'].items():
    checks[viewport]={}
    for key,data in entry['states'].items(): checks[viewport][key]=(data['selected']==[key] and data['active']==[key] and data['overflow']<=1 and not data['clipping'] and all(a['ok'] for a in data['assets']) and data['trust'])
    checks[viewport]['errors']=(not entry['console_errors'] and not entry['page_errors'] and not entry['failed_requests'] and not entry['external_requests'])
    checks[viewport]['keyboard']=(entry['keyboard']['selected']=='question' and entry['keyboard']['focus']=='question' and entry['keyboard']['outlineWidth']=='3px' and entry['keyboard']['outlineStyle']=='solid')
motion=report['motion'];checks['motion']=(motion['final_equal'] and all(r['motion']=='complete' and r['exceptionVisible'] and r['humanVisible'] and r['wrongVisible'] for r in motion['runs']) and motion['timing']['animationName']=='routeSeal' and 700<=motion['timing']['maxEnd']<=780 and motion['geometry_equal'] and motion['scroll_before']==motion['scroll_after'] and motion['focus_after']=='replay-route')
checks['reduced_motion']=(report['reduced_motion']['state']=='complete' and report['reduced_motion']['seal']=='1' and report['reduced_motion']['human']!='none' and report['reduced_motion']['exception']!='none' and report['reduced_motion']['wrong']!='none' and report['reduced_motion']['focus']=='replay-route')
checks['http_readback']=all(i['status']==200 and i['bytes']>0 for i in report['http_readback'])
passed=all(all(v.values()) if isinstance(v,dict) else v for v in checks.values());report['checks']=checks;report['result']='BROWSER_SELF_CHECK_PASS' if passed else 'BROWSER_SELF_CHECK_FAIL'
(ROOT/'evidence/browser-self-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'result':report['result'],'harness':report['harness'],'localhost_navigation_error':report['localhost_navigation_error'],'checks':checks,'motion':report['motion'],'reduced_motion':report['reduced_motion']},ensure_ascii=False,indent=2));sys.exit(0 if passed else 1)
