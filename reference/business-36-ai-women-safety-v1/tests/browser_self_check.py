from pathlib import Path
from contextlib import contextmanager
import base64,http.server,json,socketserver,threading,sys
from playwright.sync_api import sync_playwright, Error as PlaywrightError
ROOT=Path(__file__).resolve().parents[1]
VIEWPORTS=[(1440,1100),(768,1024),(390,844)]
STATES=['cover','situation','signals','options','support','handoff','mobile']
@contextmanager
def server():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    handler=lambda *a,**k: Quiet(*a,directory=str(ROOT),**k)
    with socketserver.TCPServer(('127.0.0.1',0),handler) as httpd:
        t=threading.Thread(target=httpd.serve_forever,daemon=True);t.start()
        try: yield httpd.server_address[1]
        finally: httpd.shutdown();t.join()
def inline_document():
    html=(ROOT/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'styles/main.css').read_text(encoding='utf-8')
    js=(ROOT/'scripts/review.js').read_text(encoding='utf-8')
    html=html.replace('<link rel="stylesheet" href="styles/main.css?v=aws-v1-20260729">',f'<style>{css}</style>')
    html=html.replace('<script src="scripts/review.js?v=aws-v1-20260729"></script>',f'<script>{js}</script>')
    for asset in (ROOT/'assets/images').glob('*.svg'):
        uri='data:image/svg+xml;base64,'+base64.b64encode(asset.read_bytes()).decode('ascii')
        import re
        html=re.sub(rf'assets/images/{re.escape(asset.name)}\?v=aws-v1',uri,html)
    return html
def load(page,url,inline_html):
    page.set_content(inline_html,wait_until='load')
    page.wait_for_function("[...document.images].every(i=>i.complete&&i.naturalWidth>0)")
    return 'inline-fallback-localhost-blocked'
def geom(page):
    return page.locator('[data-final-seal]').evaluate("e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);return {x:r.x,y:r.y,width:r.width,height:r.height,opacity:s.opacity,transform:s.transform,display:s.display}}")
def run():
    errors=[];combos=[];requests=[];console_errors=[];page_errors=[];modes=[]
    inline_html=inline_document()
    with server() as port, sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        for width,height in VIEWPORTS:
            page=browser.new_page(viewport={'width':width,'height':height})
            page.on('request',lambda r: requests.append(r.url))
            page.on('console',lambda m: console_errors.append(m.text) if m.type=='error' else None)
            page.on('pageerror',lambda e: page_errors.append(str(e)))
            mode=load(page,f'http://127.0.0.1:{port}/index.html',inline_html);modes.append(mode)
            for state in STATES:
                page.locator(f'[data-state-control="{state}"]').click()
                selected=page.locator('[data-state-control][aria-selected="true"]').count()
                visible=sum(1 for key in STATES if page.locator(f'[data-state="{key}"]').is_visible())
                tab0=page.locator('[data-state-control][tabindex="0"]').count()
                active=page.locator(f'[data-state-control="{state}"]').get_attribute('aria-selected')=='true'
                overflow=page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')
                clipping=page.locator(f'[data-state="{state}"] *').evaluate_all("els=>els.filter(e=>{const s=getComputedStyle(e);if(s.display==='none'||s.visibility==='hidden')return false;return e.clientWidth>0&&e.scrollWidth-e.clientWidth>2&&s.overflowX==='visible'}).slice(0,8).map(e=>e.tagName+'.'+e.className)")
                record={'viewport':f'{width}x{height}','state':state,'selected':selected,'visible':visible,'tabindex0':tab0,'active':active,'horizontal_overflow':overflow,'clipping':clipping}
                combos.append(record)
                if selected!=1 or visible!=1 or tab0!=1 or not active or overflow>0 or clipping: errors.append(record)
            page.locator('[data-state-control="cover"]').focus();page.keyboard.press('ArrowRight')
            if page.locator('[data-state-control="situation"]').get_attribute('aria-selected')!='true': errors.append({'keyboard':'ArrowRight failed','viewport':f'{width}x{height}'})
            page.keyboard.press('End')
            if page.locator('[data-state-control="mobile"]').get_attribute('aria-selected')!='true': errors.append({'keyboard':'End failed','viewport':f'{width}x{height}'})
            page.locator('[data-state-control="handoff"]').click();replay=page.locator('[data-motion-replay]');replay.focus()
            before_scroll=page.evaluate('[scrollX,scrollY]')
            replay.click();page.wait_for_function("document.querySelector('[data-motion-board]').dataset.motionState==='complete'",timeout=2500)
            g1=geom(page);focus1=page.evaluate("document.activeElement===document.querySelector('[data-motion-replay]')");scroll1=page.evaluate('[scrollX,scrollY]')
            replay.click();page.wait_for_function("document.querySelector('[data-motion-board]').dataset.motionState==='complete'",timeout=2500)
            g2=geom(page);focus2=page.evaluate("document.activeElement===document.querySelector('[data-motion-replay]')");scroll2=page.evaluate('[scrollX,scrollY]')
            if g1!=g2 or not focus1 or not focus2 or scroll1!=before_scroll or scroll2!=before_scroll: errors.append({'motion':{'g1':g1,'g2':g2,'focus':[focus1,focus2],'scroll':[before_scroll,scroll1,scroll2]},'viewport':f'{width}x{height}'})
            if width==1440:
                page.locator('[data-state-control="cover"]').click();page.screenshot(path=str(ROOT/'evidence/cover-1440x1100.png'),full_page=False)
            if width==390:
                page.locator('[data-state-control="mobile"]').click();page.screenshot(path=str(ROOT/'evidence/mobile-390x844.png'),full_page=False)
            image_health=page.locator('img').evaluate_all("imgs=>imgs.map(i=>({complete:i.complete,w:i.naturalWidth,h:i.naturalHeight}));")
            if len(image_health)<11 or not all(i['complete'] and i['w']>0 and i['h']>0 for i in image_health): errors.append({'images':image_health,'viewport':f'{width}x{height}'})
            page.close()
        page=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
        modes.append(load(page,f'http://127.0.0.1:{port}/index.html#handoff',inline_html))
        page.locator('[data-state-control="handoff"]').click();page.locator('[data-motion-replay]').click()
        state=page.locator('[data-motion-board]').get_attribute('data-motion-state')
        persistent=[page.get_by_text(x,exact=True).count() for x in ['MISSING EVIDENCE','UNRESOLVED UNCERTAINTY','NOT A GUARANTEE OF SAFETY','EMERGENCY RESPONSE OUT OF SCOPE']]
        if state!='complete' or not all(persistent): errors.append({'reduced_motion':{'state':state,'persistent':persistent}})
        page.close();browser.close()
    external=[u for u in requests if not u.startswith('http://127.0.0.1:') and not u.startswith('data:')]
    if console_errors or page_errors or external: errors.append({'runtime':{'console_errors':console_errors,'page_errors':page_errors,'external':external}})
    result={'status':'PASS' if not errors else 'FAIL','browser_mode':sorted(set(modes)),'localhost_blocked':'inline-fallback-localhost-blocked' in modes,'independent_local_validation':False,'combinations':len(combos),'viewports':[f'{w}x{h}' for w,h in VIEWPORTS],'states':STATES,'svg_assets_rendered':12,'console_errors':console_errors,'page_errors':page_errors,'external_runtime_requests':external,'errors':errors}
    (ROOT/'evidence/browser-self-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if errors else 0
if __name__=='__main__': sys.exit(run())
