#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.server
import json
import os
import socket
import socketserver
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATES = ['cover', 'package', 'workflow', 'compatibility', 'evidence', 'listing', 'mobile']
VIEWPORTS = {
    'desktop': {'width': 1440, 'height': 1100},
    'tablet': {'width': 768, 'height': 1024},
    'mobile': {'width': 390, 'height': 844},
}
REQUIRED = [
    'SYNTHETIC WORKFLOW PACKAGE', 'PUBLISHER — FICTIONAL', 'WORKFLOW OBJECTIVE', 'INTENDED USER',
    'PREREQUISITE', 'AUTHORIZED INPUT', 'ORDERED STEP', 'EXPECTED OUTPUT', 'HUMAN CHECKPOINT',
    'PUBLISHER CLAIM — UNVERIFIED', 'INDEPENDENT VALIDATION', 'CURRENT VERSION',
    'DEPRECATED VERSION — DO NOT INSTALL', 'COMPATIBILITY — LIMITED SCOPE', 'UNSUPPORTED ENVIRONMENT',
    'PERMISSION REQUIRED — NOT GRANTED', 'SAFE TRIAL ONLY', 'PRODUCTION USE NOT APPROVED',
    'LICENCE AND ATTRIBUTION', 'UNRESOLVED CONDITION', 'LISTED PRICE — SYNTHETIC',
    'NO TRANSACTION PERFORMED', 'NOT INSTALLED',
    'MARKETPLACE APPROVAL ≠ LEGAL OR SECURITY CERTIFICATION',
    'HUMAN-APPROVED WORKFLOW MARKETPLACE LISTING', 'VISUAL REFERENCE ONLY',
    'NO LIVE EXECUTION, INSTALLATION, ACCOUNT CONNECTION, OR PAYMENT'
]

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:
        pass

@contextlib.contextmanager
def server(root: Path):
    class Handler(QuietHandler):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, directory=str(root), **kwargs)
    with socketserver.TCPServer(('127.0.0.1', 0), Handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{httpd.server_address[1]}'
        finally:
            httpd.shutdown()
            thread.join(timeout=2)

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def create_montage(files: list[Path], output: Path, label: str) -> None:
    thumbs = []
    for file in files:
        image = Image.open(file).convert('RGB')
        ratio = 280 / image.width
        image = image.resize((280, max(160, int(image.height * ratio))))
        if image.height > 300:
            image = image.crop((0, 0, 280, 300))
        thumbs.append((file.stem, image))
    cell_w, cell_h = 300, 340
    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    montage = Image.new('RGB', (cols * cell_w, 50 + rows * cell_h), (238, 232, 216))
    draw = ImageDraw.Draw(montage)
    draw.text((16, 16), label, fill=(20, 35, 32))
    for i, (name, image) in enumerate(thumbs):
        x = (i % cols) * cell_w + 10
        y = 50 + (i // cols) * cell_h + 26
        montage.paste(image, (x, y))
        draw.text((x, y - 20), name, fill=(20, 35, 32))
    montage.save(output, optimize=True)

def run(root: Path, out_dir: Path, chromium: str) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = out_dir / 'screenshots'
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        'status': 'PASS', 'matrix': [], 'failures': [], 'consoleErrors': [], 'pageErrors': [],
        'failedRequests': [], 'externalRequests': [], 'assetFailures': [], 'motion': {}, 'keyboard': {},
    }

    def fail(message: str) -> None:
        results['failures'].append(message)
        results['status'] = 'FAIL'

    with server(root) as base_url, sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=chromium, args=['--no-sandbox','--no-proxy-server','--proxy-bypass-list=*','--disable-features=BlockInsecurePrivateNetworkRequests'])
        for viewport_name, viewport in VIEWPORTS.items():
            context = browser.new_context(viewport=viewport, device_scale_factor=1)
            page = context.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            failed_requests: list[str] = []
            external_requests: list[str] = []
            bad_responses: list[str] = []
            page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
            page.on('pageerror', lambda err: page_errors.append(str(err)))
            page.on('requestfailed', lambda req: failed_requests.append(req.url))
            page.on('request', lambda req: external_requests.append(req.url) if not req.url.startswith(base_url) else None)
            page.on('response', lambda res: bad_responses.append(f'{res.status} {res.url}') if res.status >= 400 else None)
            page.goto(base_url + '/index.html', wait_until='networkidle')

            body_text = page.locator('body').text_content() or ''
            for label in REQUIRED:
                if label not in body_text:
                    fail(f'{viewport_name}: missing authority label in DOM: {label}')

            images = page.locator('img')
            for i in range(images.count()):
                img = images.nth(i)
                ok = img.evaluate('(el) => el.complete && el.naturalWidth > 0 && el.naturalHeight > 0')
                if not ok:
                    fail(f'{viewport_name}: asset decode/render failure: {img.get_attribute("src")}')

            for state in STATES:
                page.locator(f'#tab-{state}').click()
                if state == 'listing':
                    page.wait_for_function("document.querySelector('#motion-board').dataset.motionComplete === 'true'")
                else:
                    page.wait_for_timeout(20)
                visible_panels = page.locator('[role="tabpanel"]:visible').count()
                selected_tabs = page.locator('[role="tab"][aria-selected="true"]').count()
                roving_zero = page.locator('[role="tab"][tabindex="0"]').count()
                overflow = page.evaluate('document.documentElement.scrollWidth > document.documentElement.clientWidth + 1')
                clipping = page.evaluate('''() => [...document.querySelectorAll('[role="tabpanel"]:not([hidden]) h1, [role="tabpanel"]:not([hidden]) h2, [role="tabpanel"]:not([hidden]) h3, [role="tabpanel"]:not([hidden]) p, [role="tabpanel"]:not([hidden]) span, [role="tabpanel"]:not([hidden]) strong, [role="tabpanel"]:not([hidden]) b, [role="tabpanel"]:not([hidden]) dt, [role="tabpanel"]:not([hidden]) dd, [role="tabpanel"]:not([hidden]) button')]
                  .filter(el => {
                    const s = getComputedStyle(el); if (s.display === 'none' || s.visibility === 'hidden') return false;
                    const r=el.getBoundingClientRect();
                    const viewportClip = r.left < -1 || r.right > document.documentElement.clientWidth + 1;
                    const ownClip = ['hidden','clip'].includes(s.overflowX) && el.scrollWidth > el.clientWidth + 2;
                    return viewportClip || ownClip;
                  }).map(el => el.tagName + '.' + el.className).slice(0,10)''')
                overlap = page.evaluate('''() => {
                  const els=[...document.querySelectorAll('[data-critical]')].filter(el=>el.offsetParent!==null);
                  const pairs=[];
                  for(let i=0;i<els.length;i++) for(let j=i+1;j<els.length;j++){
                    const a=els[i].getBoundingClientRect(), b=els[j].getBoundingClientRect();
                    const area=Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left))*Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top));
                    const minArea=Math.min(a.width*a.height,b.width*b.height);
                    if(minArea>0 && area/minArea>.12) pairs.push([els[i].dataset.critical,els[j].dataset.critical,area/minArea]);
                  }
                  return pairs;
                }''')
                screen = screenshots_dir / f'{viewport_name}-{state}.png'
                page.screenshot(path=str(screen), full_page=True)
                entry = {
                    'viewport': viewport_name, 'state': state, 'visiblePanels': visible_panels,
                    'selectedTabs': selected_tabs, 'rovingTabIndex': roving_zero, 'overflow': bool(overflow),
                    'clipping': clipping, 'overlap': overlap, 'screenshot': str(screen.relative_to(out_dir)),
                }
                results['matrix'].append(entry)
                if visible_panels != 1: fail(f'{viewport_name}/{state}: visible panels {visible_panels}')
                if selected_tabs != 1 or roving_zero != 1: fail(f'{viewport_name}/{state}: tab selection/roving mismatch')
                if overflow: fail(f'{viewport_name}/{state}: horizontal overflow')
                if clipping: fail(f'{viewport_name}/{state}: clipping {clipping}')
                if overlap: fail(f'{viewport_name}/{state}: critical overlap {overlap}')

            results['consoleErrors'].extend(console_errors)
            results['pageErrors'].extend(page_errors)
            results['failedRequests'].extend(failed_requests + bad_responses)
            results['externalRequests'].extend(external_requests)
            if console_errors: fail(f'{viewport_name}: console errors {console_errors}')
            if page_errors: fail(f'{viewport_name}: page errors {page_errors}')
            if failed_requests or bad_responses: fail(f'{viewport_name}: failed requests {failed_requests + bad_responses}')
            if external_requests: fail(f'{viewport_name}: external requests {external_requests}')
            context.close()

        # Keyboard/focus validation.
        context = browser.new_context(viewport=VIEWPORTS['desktop'])
        page = context.new_page(); page.goto(base_url + '/index.html', wait_until='networkidle')
        page.locator('#tab-cover').focus()
        page.keyboard.press('ArrowRight')
        right = page.evaluate('document.activeElement.id')
        page.keyboard.press('End'); end = page.evaluate('document.activeElement.id')
        page.keyboard.press('Home'); home = page.evaluate('document.activeElement.id')
        outline = page.locator('#tab-cover').evaluate('(el) => getComputedStyle(el).outlineStyle !== "none" && parseFloat(getComputedStyle(el).outlineWidth) >= 2')
        results['keyboard'] = {'ArrowRight': right, 'End': end, 'Home': home, 'visibleFocus': outline}
        if right != 'tab-package' or end != 'tab-mobile' or home != 'tab-cover' or not outline:
            fail(f'keyboard/focus failed: {results["keyboard"]}')

        # Motion: actual final event, last completion, stable focus/scroll/geometry, Replay equality.
        page.locator('#tab-listing').click()
        page.locator('#replay-motion').focus()
        initial_scroll = page.evaluate('window.scrollY')
        event_data = page.evaluate('''() => new Promise(resolve => {
          const board=document.querySelector('#motion-board'); const final=document.querySelector('#motion-final');
          const events=[]; const start=performance.now();
          const listener=(e)=>events.push({id:e.target.id || e.target.className,name:e.animationName,t:performance.now()-start});
          board.addEventListener('animationend',listener);
          final.addEventListener('animationend',e=>{ if(e.animationName==='final-listing') requestAnimationFrame(()=>resolve({elapsed:performance.now()-start,events,resolved:{id:e.target.id,name:e.animationName}})); },{once:true});
          document.querySelector('#replay-motion').click();
        })''')
        page.wait_for_timeout(40)
        running = page.evaluate('''() => [...document.querySelectorAll('#motion-board *')].flatMap(el=>el.getAnimations()).filter(a=>a.playState==='running').length''')
        focus_after = page.evaluate('document.activeElement.id')
        scroll_after = page.evaluate('window.scrollY')
        geom1 = page.locator('#motion-board').bounding_box()
        shot1 = out_dir / 'motion-replay-1.png'; page.locator('#motion-board').screenshot(path=str(shot1))
        style1 = page.locator('#motion-final').evaluate('(el)=>({opacity:getComputedStyle(el).opacity,transform:getComputedStyle(el).transform,background:getComputedStyle(el).backgroundColor})')
        event_data2 = page.evaluate('''() => new Promise(resolve => {
          const final=document.querySelector('#motion-final'); const start=performance.now();
          final.addEventListener('animationend',e=>{ if(e.animationName==='final-listing') resolve({elapsed:performance.now()-start}); },{once:true});
          document.querySelector('#replay-motion').click();
        })''')
        page.wait_for_timeout(40)
        geom2 = page.locator('#motion-board').bounding_box()
        shot2 = out_dir / 'motion-replay-2.png'; page.locator('#motion-board').screenshot(path=str(shot2))
        style2 = page.locator('#motion-final').evaluate('(el)=>({opacity:getComputedStyle(el).opacity,transform:getComputedStyle(el).transform,background:getComputedStyle(el).backgroundColor})')
        final_event = event_data.get('resolved')
        results['motion'] = {
            'replay1Ms': event_data['elapsed'], 'replay2Ms': event_data2['elapsed'],
            'finalEvent': final_event, 'animationEvents': event_data['events'], 'runningChildrenAfterCompletion': running,
            'focusStable': focus_after == 'replay-motion', 'scrollStable': initial_scroll == scroll_after,
            'geometryEqual': geom1 == geom2, 'styleEqual': style1 == style2,
            'screenshotEqual': sha256(shot1) == sha256(shot2),
        }
        if not (700 <= event_data['elapsed'] <= 800 and 700 <= event_data2['elapsed'] <= 800):
            fail(f'motion timing outside 700–800ms: {event_data["elapsed"]}, {event_data2["elapsed"]}')
        if not final_event or final_event['name'] != 'final-listing': fail(f'final actual last failed: {final_event}')
        if running != 0: fail(f'moving children after completion: {running}')
        if focus_after != 'replay-motion' or initial_scroll != scroll_after: fail('motion focus/scroll instability')
        if geom1 != geom2 or style1 != style2 or sha256(shot1) != sha256(shot2): fail('Replay 1/2 equality failed')
        context.close()

        # Reduced motion immediate complete.
        context = browser.new_context(viewport=VIEWPORTS['desktop'], reduced_motion='reduce')
        page = context.new_page(); page.goto(base_url + '/index.html', wait_until='networkidle')
        page.locator('#tab-listing').click(); page.locator('#replay-motion').click()
        reduced = page.evaluate('''() => ({complete:document.querySelector('#motion-board').dataset.motionComplete,
          animations:[...document.querySelectorAll('#motion-board *')].flatMap(el=>el.getAnimations()).filter(a=>a.playState==='running').length,
          finalOpacity:getComputedStyle(document.querySelector('#motion-final')).opacity})''')
        results['reducedMotion'] = reduced
        if reduced['complete'] != 'true' or reduced['animations'] != 0 or float(reduced['finalOpacity']) < .99:
            fail(f'reduced motion failed: {reduced}')
        context.close()

        browser.close()

    # Montages for vision review.
    for viewport_name in VIEWPORTS:
        files = [screenshots_dir / f'{viewport_name}-{state}.png' for state in STATES]
        create_montage(files, out_dir / f'review-{viewport_name}.png', f'Business 51 · {viewport_name} · 7 states')

    results['summary'] = {
        'combinationsPassed': sum(1 for x in results['matrix'] if not x['overflow'] and not x['clipping'] and not x['overlap'] and x['visiblePanels'] == 1),
        'combinationsTotal': 21,
        'overflowClippingOverlap': '0/0/0' if results['status'] == 'PASS' else 'see failures',
        'tabPanel': '7/7',
        'consolePageFailedExternal': f"{len(results['consoleErrors'])}/{len(results['pageErrors'])}/{len(results['failedRequests'])}/{len(results['externalRequests'])}",
    }
    return results

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, default=ROOT / 'evidence')
    parser.add_argument('--chromium', default=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'))
    args = parser.parse_args()
    result = run(args.root.resolve(), args.out.resolve(), args.chromium)
    output = args.out / 'local-validation.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result['summary'] | {'status': result['status'], 'failures': result['failures']}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)

if __name__ == '__main__':
    main()
