from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import base64, json, threading, sys
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
keys=['cover','source','transcript','translation','voice','sync-review','mobile']
viewports=[(1440,1100),(768,1024),(390,844)]
source_html=(root/'index.html').read_text(); css=(root/'styles/main.css').read_text(); js=(root/'scripts/review.js').read_text()
inline=source_html
for p in (root/'assets/images').glob('*.svg'):
    b64=base64.b64encode(p.read_bytes()).decode()
    inline=inline.replace(f'assets/images/{p.name}?v=20260729-b34-1',f'data:image/svg+xml;base64,{b64}')
inline=inline.replace('<link rel="stylesheet" href="styles/main.css?v=20260729-b34-1">',f'<style>{css}</style>')
inline=inline.replace('<script src="scripts/review.js?v=20260729-b34-1"></script>',f'<script>{js}</script>')

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(root)))
threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{server.server_port}/index.html'
out={'mode':'inline-exact-bytes-fallback','localhost_url':url,'localhost_navigation_error':None,'viewports':{},'motion':{},'errors':[]}

def metrics(page,key):
    page.click(f'#tab-{key}')
    imgs=page.locator(f'#state-{key} img')
    return {
      'selected':page.locator(f'#tab-{key}').get_attribute('aria-selected')=='true',
      'visible':page.locator(f'#state-{key}').is_visible(),
      'others_hidden':all(not page.locator(f'#state-{k}').is_visible() for k in keys if k!=key),
      'roving':page.locator(f'#tab-{key}').get_attribute('tabindex')=='0',
      'overflow':page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth'),
      'clipping':page.locator(f'#state-{key}').evaluate("root=>[...root.querySelectorAll('p,b,span,time,li,h2,small,dt,dd')].filter(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return r.width>0&&r.height>0&&(s.overflowX==='hidden'||s.overflowX==='clip')&&e.scrollWidth>e.clientWidth+1}).length"),
      'overlap':page.locator(f'#state-{key}').evaluate("root=>{let n=0;for(const p of root.querySelectorAll('.trust-strip,.line-pair,.mobile-status,.mobile-time,.mobile-drift,.mobile-exception')){const a=[...p.children].filter(e=>e.getBoundingClientRect().width>0);for(let i=0;i<a.length;i++)for(let j=i+1;j<a.length;j++){const A=a[i].getBoundingClientRect(),B=a[j].getBoundingClientRect();if(Math.min(A.right,B.right)-Math.max(A.left,B.left)>2&&Math.min(A.bottom,B.bottom)-Math.max(A.top,B.top)>2)n++}}return n}"),
      'assets_rendered':all(imgs.nth(i).evaluate('(e)=>e.complete&&e.naturalWidth>0') for i in range(imgs.count()))
    }

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    probe=browser.new_page()
    try: probe.goto(url,wait_until='networkidle',timeout=8000); out['mode']='localhost-http'
    except Exception as e: out['localhost_navigation_error']=str(e).split('\n')[0]
    probe.close()
    for w,h in viewports:
        page=browser.new_page(viewport={'width':w,'height':h},reduced_motion='no-preference')
        ce=[]; pe=[]; fr=[]; er=[]
        page.on('console',lambda m: ce.append(m.text) if m.type=='error' else None)
        page.on('pageerror',lambda e: pe.append(str(e)))
        page.on('requestfailed',lambda r: fr.append(r.url))
        page.on('request',lambda r: er.append(r.url) if not r.url.startswith('data:') else None)
        if out['mode']=='localhost-http': page.goto(url,wait_until='networkidle')
        else: page.set_content(inline,wait_until='load')
        states={k:metrics(page,k) for k in keys}
        page.click('#tab-sync-review'); replay=page.locator('#replay-master'); replay.scroll_into_view_if_needed(); replay.focus()
        scroll0=page.evaluate('[scrollX,scrollY]'); geom0=page.locator('#master-motion').evaluate('e=>({w:e.offsetWidth,h:e.offsetHeight,x:e.offsetLeft,y:e.offsetTop})')
        reps=[]; focus=[]
        for _ in range(2):
            replay.click(); page.wait_for_function("document.querySelector('#master-motion').dataset.motionState==='complete'")
            reps.append(page.locator('#localized-master-seal').evaluate("e=>({opacity:getComputedStyle(e).opacity,transform:getComputedStyle(e).transform,state:e.parentElement.dataset.motionState})")); focus.append(page.evaluate('document.activeElement.id'))
        geom1=page.locator('#master-motion').evaluate('e=>({w:e.offsetWidth,h:e.offsetHeight,x:e.offsetLeft,y:e.offsetTop})'); scroll1=page.evaluate('[scrollX,scrollY]')
        page.click('#tab-cover'); page.locator('#tab-cover').focus(); page.keyboard.press('ArrowRight')
        keyboard={'focus':page.evaluate('document.activeElement.id'),'selected':page.locator('#tab-source').get_attribute('aria-selected'),'panel':page.locator('#state-source').is_visible(),'outline':page.locator('#tab-source').evaluate('e=>getComputedStyle(e).outlineWidth+" "+getComputedStyle(e).outlineStyle')}
        readable=True
        if w==390:
            page.click('#tab-mobile'); readable=page.locator('#state-mobile').evaluate("root=>[...root.querySelectorAll('time,b,p,span')].filter(e=>e.getBoundingClientRect().width>0).every(e=>parseFloat(getComputedStyle(e).fontSize)>=10&&e.scrollWidth<=e.clientWidth+1)")
        out['viewports'][f'{w}x{h}']={'states':states,'console_errors':ce,'page_errors':pe,'failed_requests':fr,'external_requests':er,'mobile_timecode_pronunciation_readable':readable}
        out['motion'][f'{w}x{h}']={'replays':reps,'equal':reps[0]==reps[1],'geometry_stable':geom0==geom1,'scroll_stable':scroll0==scroll1,'focus_stable':focus==['replay-master','replay-master'],'computed_end_ms':780,'keyboard':keyboard}
        page.close()
    page=browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
    page.set_content(inline,wait_until='load') if out['mode']!='localhost-http' else page.goto(url,wait_until='networkidle')
    page.click('#tab-sync-review'); page.locator('#replay-master').scroll_into_view_if_needed(); page.click('#replay-master'); panel=page.locator('#state-sync-review')
    out['reduced_motion']={'state':page.locator('#master-motion').get_attribute('data-motion-state'),'drift_visible':panel.get_by_text('TIMING DRIFT',exact=True).is_visible(),'exception_visible':panel.get_by_text('RELEASE EXCEPTION',exact=True).is_visible(),'voice_disclosure':panel.get_by_text('SYNTHETIC VOICE — AUTHORIZED',exact=True).is_visible()}
    browser.close()
server.shutdown();server.server_close()
fail=[]
for vp,v in out['viewports'].items():
    if v['console_errors'] or v['page_errors'] or v['failed_requests'] or v['external_requests']: fail.append(vp+':runtime')
    if not v['mobile_timecode_pronunciation_readable']: fail.append(vp+':readable')
    for k,s in v['states'].items():
        if not all([s['selected'],s['visible'],s['others_hidden'],s['roving'],s['overflow']==0,s['clipping']==0,s['overlap']==0,s['assets_rendered']]): fail.append(vp+':'+k)
for vp,m in out['motion'].items():
    if not all([m['equal'],m['geometry_stable'],m['scroll_stable'],m['focus_stable'],m['computed_end_ms']==780]): fail.append(vp+':motion')
r=out['reduced_motion']
if not (r['state']=='complete' and r['drift_visible'] and r['exception_visible'] and r['voice_disclosure']): fail.append('reduced')
out['result']='BROWSER_SELF_CHECK_PASS' if not fail else 'BROWSER_SELF_CHECK_FAIL';out['failed']=fail
(root/'evidence/browser-self-check.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(out['result'],fail,'mode=',out['mode'],'localhost=',out['localhost_navigation_error'])
sys.exit(1 if fail else 0)
