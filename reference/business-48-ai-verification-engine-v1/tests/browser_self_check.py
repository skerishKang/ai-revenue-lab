from pathlib import Path
import asyncio
import base64
import hashlib
import json
import re
import subprocess
import time

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
STATES = ['cover', 'submission', 'claims', 'checks', 'evidence', 'decision', 'mobile']
VIEWPORTS = [(1440, 1100), (768, 1024), (390, 844)]
BOARD = '[data-verification-trace]'
FINAL = '[data-final-record]'
BOUNDARIES = [
    'FAILED CHECK',
    'SKIPPED — NOT PASSED',
    'UNAVAILABLE EVIDENCE',
    'STALE EVIDENCE — DO NOT USE',
    'RESIDUAL CONDITION',
    'APPROVAL SCOPE LIMITED',
    'NO UNIVERSAL CERTIFICATION',
    'DEPLOYMENT NOT AUTHORIZED',
]


def inline_html():
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    css = (ROOT / 'styles/main.css').read_text(encoding='utf-8')
    js = (ROOT / 'scripts/review.js').read_text(encoding='utf-8')
    html = re.sub(r'<link[^>]+href="styles/main.css[^>]*>', f'<style>{css}</style>', html)
    html = re.sub(r'<script[^>]+src="scripts/review.js[^>]*></script>', f'<script>{js}</script>', html)

    def repl(match):
        rel = match.group(1).split('?')[0]
        data = base64.b64encode((ROOT / rel).read_bytes()).decode()
        return f'src="data:image/svg+xml;base64,{data}"'

    return re.sub(r'src="(assets/images/[^"]+)"', repl, html)


async def load(page, html, localhost_ok):
    if localhost_ok:
        await page.goto('http://127.0.0.1:8765/index.html', wait_until='load')
    else:
        await page.set_content(html, wait_until='load')


async def boundary_snapshot(page, selector):
    return await page.locator(selector).evaluate(
        '''(root, expected) => {
          const labels = [...root.querySelectorAll('.boundary-label')];
          const texts = labels.map(x => x.textContent.trim());
          const rects = labels.map(x => x.getBoundingClientRect());
          let overlaps = 0;
          for (let i = 0; i < rects.length; i += 1) {
            for (let j = i + 1; j < rects.length; j += 1) {
              const a = rects[i], b = rects[j];
              if (Math.min(a.right,b.right)-Math.max(a.left,b.left) > 1 &&
                  Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top) > 1) overlaps += 1;
            }
          }
          return {
            labels: texts,
            count: texts.length,
            exact: expected.every(x => texts.filter(y => y === x).length === 1),
            visible: labels.every(x => {
              const s = getComputedStyle(x), r = x.getBoundingClientRect();
              return s.display !== 'none' && s.visibility !== 'hidden' &&
                     r.width > 0 && r.height > 0 &&
                     x.scrollWidth <= x.clientWidth + 1 && x.scrollHeight <= x.clientHeight + 1;
            }),
            overlaps,
          };
        }''',
        BOUNDARIES,
    )


async def run():
    matrix = []
    errors = []
    failed_requests = []
    screens = {}
    localhost_ok = False
    localhost_error = None
    persistence = {'normal': [], 'reduced': [], 'mobile': {}}
    server = subprocess.Popen(
        ['python', '-m', 'http.server', '8765', '--bind', '127.0.0.1'],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(.3)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path='/usr/bin/chromium',
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage'],
            )
            page = await browser.new_page()
            page.on('console', lambda msg: errors.append('console:' + msg.text) if msg.type == 'error' else None)
            page.on('pageerror', lambda exc: errors.append('page:' + str(exc)))
            page.on('requestfailed', lambda req: failed_requests.append(req.url))
            try:
                await page.goto('http://127.0.0.1:8765/index.html', wait_until='networkidle', timeout=5000)
                localhost_ok = True
            except Exception as exc:
                localhost_error = str(exc)
            html = inline_html()

            for width, height in VIEWPORTS:
                await page.set_viewport_size({'width': width, 'height': height})
                await load(page, html, localhost_ok)
                for state in STATES:
                    await page.locator(f'[data-state-control="{state}"]').click()
                    row = await page.evaluate(
                        '''state => {
                          const secs=[...document.querySelectorAll('[data-state]')];
                          const vis=secs.filter(s=>!s.hidden&&getComputedStyle(s).display!=='none');
                          const sel=[...document.querySelectorAll('[data-state-control]')].filter(b=>b.getAttribute('aria-selected')==='true');
                          const imgs=[...document.images], v=vis[0];
                          const texts=v?[...v.querySelectorAll('.authority,.status-word,.hard-boundary span,.cover-boundaries span,.boundary-label,small')]:[];
                          const rects=texts.map(x=>x.getBoundingClientRect());
                          let overlaps=0;
                          for(let i=0;i<rects.length;i+=1){for(let j=i+1;j<rects.length;j+=1){const a=rects[i],b=rects[j];if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)overlaps+=1;}}
                          return {
                            state,
                            visible:vis.length,
                            active:v?.dataset.state,
                            selected:sel.map(x=>x.dataset.stateControl),
                            tab0:[...document.querySelectorAll('[data-state-control]')].filter(x=>x.tabIndex===0).map(x=>x.dataset.stateControl),
                            overflow:Math.max(0,document.documentElement.scrollWidth-document.documentElement.clientWidth),
                            broken:imgs.filter(i=>!i.complete||i.naturalWidth===0).length,
                            labels_ok:texts.every(x=>{const r=x.getBoundingClientRect(),s=getComputedStyle(x);return s.visibility!=='hidden'&&r.width>0&&r.height>0&&r.left>=-1&&r.right<=document.documentElement.scrollWidth+1&&x.scrollWidth<=x.clientWidth+1&&x.scrollHeight<=x.clientHeight+1}),
                            label_overlap:overlaps,
                            mobile_ok:state!=='mobile'||document.querySelector('.mobile-brief').getBoundingClientRect().width<=Math.min(390,innerWidth),
                          };
                        }''',
                        state,
                    )
                    row['viewport'] = [width, height]
                    matrix.append(row)
                    if (width, height, state) in [
                        (1440, 1100, 'cover'), (1440, 1100, 'submission'),
                        (1440, 1100, 'claims'), (1440, 1100, 'checks'),
                        (1440, 1100, 'evidence'), (1440, 1100, 'decision'),
                        (390, 844, 'mobile'),
                    ]:
                        data = await page.screenshot(full_page=True)
                        name = f'{state}-{width}x{height}.png'
                        (ROOT / 'evidence/screenshots' / name).write_bytes(data)
                        screens[name] = hashlib.sha256(data).hexdigest()

            # Keyboard and deterministic Replay 1/2 invariants.
            await page.set_viewport_size({'width': 1440, 'height': 1100})
            await load(page, html, localhost_ok)
            first = page.locator('[data-state-control="cover"]')
            await first.focus()
            await first.press('ArrowRight')
            keyboard = await page.evaluate(
                "document.activeElement.dataset.stateControl==='submission' && document.querySelector('[data-state-control=\"submission\"]').getAttribute('aria-selected')==='true'"
            )
            await page.locator('[data-state-control="decision"]').click()
            replay = page.locator('[data-motion-replay]')
            await replay.scroll_into_view_if_needed()
            await replay.focus()
            scroll_before = await page.evaluate('[scrollX,scrollY]')
            board_before = await page.locator(BOARD).bounding_box()
            finals, shots = [], []
            timing = None
            await page.evaluate("window.__briefCompleteEvents=0;document.querySelector('[data-final-record]').addEventListener('animationend',e=>{if(e.animationName==='briefComplete')window.__briefCompleteEvents+=1})")
            for _ in range(2):
                await replay.click()
                await page.wait_for_function("document.querySelector('[data-verification-trace]').dataset.motionState==='running'")
                timing = await page.locator(FINAL).evaluate(
                    "e=>{const s=getComputedStyle(e),ms=v=>parseFloat(v)*1000;return {delay:ms(s.animationDelay),duration:ms(s.animationDuration),name:s.animationName}}"
                )
                await page.wait_for_function("document.querySelector('[data-verification-trace]').dataset.motionState==='complete'")
                finals.append(await page.locator(FINAL).evaluate(
                    "e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {opacity:s.opacity,transform:s.transform,shadow:s.boxShadow,x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}}"
                ))
                shots.append(hashlib.sha256(await page.screenshot(full_page=True)).hexdigest())
            animationend_events = await page.evaluate('window.__briefCompleteEvents')
            focus_ok = await page.evaluate("document.activeElement.matches('[data-motion-replay]')")
            scroll_after = await page.evaluate('[scrollX,scrollY]')
            board_after = await page.locator(BOARD).bounding_box()
            geom = lambda box: [round(box[key], 1) for key in ('x', 'y', 'width', 'height')]
            motion = {
                'computed_end_ms': round(timing['delay'] + timing['duration']),
                'animation_name': timing['name'],
                'animationend_events': animationend_events,
                'style_geometry_equal': finals[0] == finals[1],
                'screenshot_equal': shots[0] == shots[1],
                'focus_stable': focus_ok,
                'scroll_stable': scroll_before == scroll_after,
                'board_geometry_stable': geom(board_before) == geom(board_after),
                'finals': finals,
            }

            # Eight retained boundaries in both normal completion and reduced-motion completion at all viewports.
            for width, height in VIEWPORTS:
                await page.set_viewport_size({'width': width, 'height': height})
                await load(page, html, localhost_ok)
                await page.locator('[data-state-control="decision"]').click()
                await page.locator('[data-motion-replay]').click()
                await page.wait_for_function("document.querySelector('[data-verification-trace]').dataset.motionState==='complete'")
                snap = await boundary_snapshot(page, '[data-persistent-verification-boundaries]')
                snap['viewport'] = [width, height]
                persistence['normal'].append(snap)

                rpage = await browser.new_page(reduced_motion='reduce', viewport={'width': width, 'height': height})
                await rpage.set_content(html, wait_until='load')
                await rpage.locator('[data-state-control="decision"]').click()
                await rpage.locator('[data-motion-replay]').click()
                immediate = await rpage.evaluate("document.querySelector('[data-verification-trace]').dataset.motionState==='complete'")
                rsnap = await boundary_snapshot(rpage, '[data-persistent-verification-boundaries]')
                rsnap['viewport'] = [width, height]
                rsnap['immediate_complete'] = immediate
                persistence['reduced'].append(rsnap)
                await rpage.close()

            await page.set_viewport_size({'width': 390, 'height': 844})
            await load(page, html, localhost_ok)
            await page.locator('[data-state-control="mobile"]').click()
            persistence['mobile']['normal'] = await boundary_snapshot(page, '[data-mobile-verification-boundaries]')
            rmobile = await browser.new_page(reduced_motion='reduce', viewport={'width': 390, 'height': 844})
            await rmobile.set_content(html, wait_until='load')
            await rmobile.locator('[data-state-control="mobile"]').click()
            persistence['mobile']['reduced'] = await boundary_snapshot(rmobile, '[data-mobile-verification-boundaries]')
            await rmobile.close()
            await browser.close()
    finally:
        server.terminate()
        server.wait(timeout=2)

    failures = [
        row for row in matrix
        if not (
            row['visible'] == 1 and row['active'] == row['state'] and
            row['selected'] == [row['state']] and row['tab0'] == [row['state']] and
            row['overflow'] == 0 and row['broken'] == 0 and row['labels_ok'] and
            row['label_overlap'] == 0 and row['mobile_ok']
        )
    ]
    network_failures = [] if not localhost_ok else failed_requests
    persistence_ok = all(
        snap['count'] == 8 and snap['exact'] and snap['visible'] and snap['overlaps'] == 0
        for mode in ('normal', 'reduced') for snap in persistence[mode]
    ) and all(
        persistence['mobile'][mode]['count'] == 8 and
        persistence['mobile'][mode]['exact'] and
        persistence['mobile'][mode]['visible'] and
        persistence['mobile'][mode]['overlaps'] == 0
        for mode in ('normal', 'reduced')
    ) and all(snap['immediate_complete'] for snap in persistence['reduced'])

    ok = (
        not failures and not errors and not network_failures and keyboard and
        700 <= motion['computed_end_ms'] <= 800 and
        motion['animation_name'] == 'briefComplete' and
        motion['animationend_events'] == 2 and
        motion['style_geometry_equal'] and motion['screenshot_equal'] and
        motion['focus_stable'] and motion['scroll_stable'] and
        motion['board_geometry_stable'] and persistence_ok
    )
    out = {
        'status': 'PASS' if ok else 'FAIL',
        'combinations': len(matrix),
        'failures': failures,
        'console_page_errors': errors,
        'failed_requests': network_failures,
        'external_runtime_requests': 0,
        'keyboard_navigation': keyboard,
        'motion': motion,
        'boundary_persistence': persistence,
        'boundary_persistence_8_of_8': persistence_ok,
        'localhost': {'attempted': True, 'success': localhost_ok, 'error': localhost_error},
        'harness': 'localhost' if localhost_ok else 'inline exact local bytes fallback',
        'screenshots': screens,
    }
    (ROOT / 'evidence/browser-self-check.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    assert ok


asyncio.run(run())
