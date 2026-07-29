from pathlib import Path
from playwright.sync_api import sync_playwright
import json, subprocess, time, urllib.request, base64, re
ROOT=Path(__file__).resolve().parents[1]
PORT=4173

def inline_document():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'styles'/'main.css').read_text(encoding='utf-8')
    js=(ROOT/'scripts'/'review.js').read_text(encoding='utf-8')
    html=re.sub(r'<link rel="stylesheet"[^>]+>',f'<style>{css}</style>',html)
    html=re.sub(r'<script src="scripts/review.js[^>]*></script>',f'<script>{js}</script>',html)
    for asset in (ROOT/'assets').glob('*.svg'):
        encoded=base64.b64encode(asset.read_bytes()).decode('ascii')
        html=re.sub(rf'assets/{re.escape(asset.name)}\?v=[^"\s]+',f'data:image/svg+xml;base64,{encoded}',html)
    return html

server=subprocess.Popen(['python3','-m','http.server',str(PORT),'--directory',str(ROOT)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
localhost_blocked=False
try:
    for _ in range(40):
        try: urllib.request.urlopen(f'http://127.0.0.1:{PORT}/',timeout=.2); break
        except Exception: time.sleep(.1)
    states=['cover','report','indicators','conflicts','review','handoff','mobile']
    viewports=[(1440,1100),(768,1024),(390,844)]
    results=[]; inline_html=inline_document()
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        probe=browser.new_page(viewport={'width':390,'height':844})
        try: probe.goto(f'http://127.0.0.1:{PORT}/',wait_until='domcontentloaded',timeout=5000)
        except Exception: localhost_blocked=True
        probe.close()
        for width,height in viewports:
            page=browser.new_page(viewport={'width':width,'height':height}, reduced_motion='no-preference')
            errors=[]; failed=[]; external=[]
            page.on('console',lambda msg,e=errors: e.append(msg.text) if msg.type=='error' else None)
            page.on('pageerror',lambda err,e=errors:e.append(str(err)))
            page.on('requestfailed',lambda req,f=failed:f.append(req.url))
            page.on('request',lambda req,x=external: x.append(req.url) if req.url.startswith(('http://','https://')) else None)
            page.set_content(inline_html,wait_until='load')
            for state in states:
                page.locator(f'#tab-{state}').click()
                selected=page.locator('[role=tab][aria-selected=true]').count()
                visible=page.locator('[role=tabpanel]:visible').count()
                overflow=page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
                assert selected==1 and visible==1 and overflow<=0,(width,height,state,selected,visible,overflow)
                if width==390 and state=='mobile':
                    first_screen=page.locator('.phone-authority').evaluate('(e)=>e.getBoundingClientRect().bottom <= innerHeight')
                    assert first_screen, 'mobile authority boundary must be visible in first 844px screen'
                results.append({'viewport':f'{width}x{height}','state':state,'selected':selected,'visible':visible,'overflow':overflow})
            page.wait_for_timeout(350)
            page.screenshot(path=str(ROOT/'evidence'/f'viewport-{width}x{height}.png'),full_page=True)
            page.evaluate("window.__BUSINESS40__.selectState('cover')")
            page.locator('#replay-motion').focus(); scroll0=page.evaluate('[scrollX,scrollY]')
            page.locator('#replay-motion').click(); page.wait_for_function("document.querySelector('#motion-track').dataset.completionAuthority==='final-element animationend'")
            style1=page.eval_on_selector_all('.motion-step','els=>els.map(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return [s.opacity,s.transform,s.boxShadow,r.x,r.y,r.width,r.height]})')
            focus1=page.evaluate('document.activeElement.id'); scroll1=page.evaluate('[scrollX,scrollY]')
            page.locator('#replay-motion').click(); page.wait_for_function("document.querySelector('#motion-track').dataset.replayCount==='2'")
            style2=page.eval_on_selector_all('.motion-step','els=>els.map(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return [s.opacity,s.transform,s.boxShadow,r.x,r.y,r.width,r.height]})')
            assert style1==style2 and focus1=='replay-motion' and scroll0==scroll1
            assert not errors and not failed and not external,(errors,failed,external)
            page.close()
        reduced=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
        reduced.set_content(inline_html,wait_until='load')
        reduced.locator('#replay-motion').click()
        assert reduced.locator('#motion-track').get_attribute('data-completion-authority')=='reduced-motion immediate information-complete'
        reduced.screenshot(path=str(ROOT/'evidence'/'reduced-motion-390x844.png'),full_page=True)
        browser.close()
    report={'pass':True,'mode':'inline fallback','localhostBlockedByEnvironment':localhost_blocked,'independentLocalhostValidationStillRequired':True,'combinations':len(results),'results':results,'replayEquality':True,'focusStable':True,'scrollStable':True,'errors':0,'failedRequests':0,'externalRequests':0,'reducedMotion':True}
    (ROOT/'evidence'/'browser-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
finally:
    server.terminate(); server.wait(timeout=5)
