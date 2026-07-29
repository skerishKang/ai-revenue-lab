from pathlib import Path
import json,re,threading,http.server,socketserver,urllib.request,base64
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
html=(root/'index.html').read_text(); css=(root/'styles/main.css').read_text(); js=(root/'scripts/review.js').read_text()
assets=sorted((root/'assets/images').glob('*.svg'))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
handler=lambda *a,**kw: Quiet(*a,directory=str(root),**kw)
server=socketserver.TCPServer(('127.0.0.1',0),handler); port=server.server_address[1]
thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
http_results={}
for a in assets:
    url=f'http://127.0.0.1:{port}/assets/images/{a.name}'
    with urllib.request.urlopen(url,timeout=3) as r: http_results[a.name]=r.status
server.shutdown(); server.server_close()
for a in assets:
    data=base64.b64encode(a.read_bytes()).decode()
    html=html.replace(f'assets/images/{a.name}?v=pdc-v1',f'data:image/svg+xml;base64,{data}')
html=re.sub(r'<link[^>]+styles/main\.css[^>]*>',f'<style>{css}</style>',html)
html=re.sub(r'<script src="scripts/review\.js\?v=pdc-v1-20260729"></script>',f'<script>{js}</script>',html)
states=['cover','catalog','source','schema','quality','package','mobile']
viewports=[(1440,1100),(768,1024),(390,844)]
failures=[]; combos=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page()
    console=[]; page_errors=[]; requests=[]
    page.on('console',lambda m: console.append(m.text) if m.type=='error' else None)
    page.on('pageerror',lambda e: page_errors.append(str(e)))
    page.on('request',lambda r: requests.append(r.url) if not r.url.startswith('data:') else None)
    for w,h in viewports:
        page.set_viewport_size({'width':w,'height':h}); page.set_content(html,wait_until='load')
        for state in states:
            page.locator(f'[data-state-control="{state}"]').click()
            info=page.evaluate('''(state)=>{const panels=[...document.querySelectorAll('[data-state]')];const visible=panels.filter(p=>!p.hidden&&getComputedStyle(p).display!=='none');const selected=[...document.querySelectorAll('[data-state-control]')].filter(b=>b.getAttribute('aria-selected')==='true');const body=document.body;const rects=[...document.querySelectorAll('[data-state]:not([hidden]) .authority,[data-state]:not([hidden]) .station-tag,[data-state]:not([hidden]) code')].map(e=>{const r=e.getBoundingClientRect();return {t:e.textContent.trim(),l:r.left,r:r.right,w:r.width,h:r.height}});return {visible:visible.map(x=>x.dataset.state),selected:selected.map(x=>x.dataset.stateControl),overflow:body.scrollWidth-document.documentElement.clientWidth,bad:rects.filter(r=>r.l<-.5||r.r>innerWidth+.5||r.w<1||r.h<1)}}''',state)
            if info['visible']!=[state] or info['selected']!=[state] or info['overflow']>0 or info['bad']:
                failures.append({'viewport':[w,h],'state':state,'info':info})
            combos.append({'viewport':[w,h],'state':state})
    page.set_viewport_size({'width':1440,'height':1100}); page.set_content(html)
    first=page.locator('[data-state-control="cover"]'); first.focus(); page.keyboard.press('ArrowRight')
    keyboard=page.locator('[data-state-control="catalog"]').get_attribute('aria-selected')=='true' and page.locator('[data-state-control="catalog"]').get_attribute('tabindex')=='0'
    page.locator('[data-state-control="package"]').click(); replay=page.locator('[data-motion-replay]'); replay.focus(); page.evaluate('window.scrollTo(0,120)')
    def run_once():
        before=page.evaluate('''()=>{const e=document.querySelector('.connector-spec-seal');const r=e.getBoundingClientRect();return {focus:document.activeElement===document.querySelector('[data-motion-replay]'),scrollY,rect:[r.x,r.y,r.width,r.height]}}''')
        replay.click(); page.wait_for_function("document.querySelector('[data-connector-line]').dataset.motionState==='complete'",timeout=2500)
        after=page.evaluate('''()=>{const e=document.querySelector('.connector-spec-seal');const s=getComputedStyle(e),r=e.getBoundingClientRect();return {opacity:s.opacity,transform:s.transform,w:r.width,h:r.height,focus:document.activeElement===document.querySelector('[data-motion-replay]'),scrollY,rect:[r.x,r.y,r.width,r.height]}}''')
        return before,after
    replay.click(); timing=page.evaluate('''()=>{const e=document.querySelector('.connector-spec-seal'),s=getComputedStyle(e);const d=parseFloat(s.animationDelay)*1000;const u=parseFloat(s.animationDuration)*1000;return {name:s.animationName,end:d+u}}'''); page.wait_for_function("document.querySelector('[data-connector-line]').dataset.motionState==='complete'",timeout=2500)
    b1,a1=run_once(); b2,a2=run_once()
    replay_equal=all(a1[k]==a2[k] for k in ['opacity','transform','w','h'])
    focus_stable=b1['focus'] and a1['focus'] and b2['focus'] and a2['focus']
    scroll_stable=abs(b1['scrollY']-a1['scrollY'])<1 and abs(b2['scrollY']-a2['scrollY'])<1
    geometry_stable=a1['rect']==a2['rect']
    import hashlib
    shot1=page.screenshot(); run_once(); shot2=page.screenshot(); screenshot_equal=hashlib.sha256(shot1).hexdigest()==hashlib.sha256(shot2).hexdigest()
    page.emulate_media(reduced_motion='reduce'); replay.click(); reduced=page.evaluate('''()=>({state:document.querySelector('[data-connector-line]').dataset.motionState,visible:[...document.querySelectorAll('.line-node,.connector-spec-seal')].every(e=>getComputedStyle(e).opacity==='1')})''')
    page.set_viewport_size({'width':390,'height':844}); page.set_content(html); page.locator('[data-state-control="mobile"]').click()
    mobile=page.evaluate('''()=>{const p=document.querySelector('.phone-brief'),r=p.getBoundingClientRect(),text=p.innerText;return {right:r.right,bottom:r.bottom,text,required:['SOURCE AUTHORITY','LICENCE','FRESHNESS','FIELD MAPPING','KNOWN LIMITATION','NOT CONNECTED','NO LIVE API'].every(x=>text.includes(x))}}''')
    page.screenshot(path=str(root/'evidence/mobile-390.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1100}); page.set_content(html); page.screenshot(path=str(root/'evidence/cover-1440.png'),full_page=True)
    page.locator('[data-state-control="schema"]').click(); page.screenshot(path=str(root/'evidence/schema-1440.png'),full_page=True)
    page.locator('[data-state-control="quality"]').click(); page.screenshot(path=str(root/'evidence/quality-1440.png'),full_page=True)
    page.locator('[data-state-control="package"]').click(); page.screenshot(path=str(root/'evidence/package-1440.png'),full_page=True)
    browser.close()
result={'status':'PASS','combinations':len(combos),'failures':failures,'http_assets':http_results,'http_assets_all_200':all(v==200 for v in http_results.values()),'console_errors':console,'page_errors':page_errors,'external_runtime_requests':requests,'keyboard_navigation':keyboard,'motion':{'computed_end_ms':timing['end'],'animation_name':timing['name'],'replay_equal':replay_equal,'screenshot_equal':screenshot_equal,'focus_stable':focus_stable,'scroll_stable':scroll_stable,'geometry_stable':geometry_stable,'finals':[a1,a2]},'reduced_motion':reduced,'mobile':mobile,'harness':'exact local bytes inline for Chromium; separate localhost HTTP asset 200 check'}
if failures or not result['http_assets_all_200'] or console or page_errors or requests or not keyboard or timing['name']!='connectorSpecComplete' or not (700<=timing['end']<=800) or not replay_equal or not screenshot_equal or not focus_stable or not scroll_stable or not geometry_stable or reduced['state']!='complete' or not reduced['visible'] or not mobile['required'] or mobile['right']>390.5:
    result['status']='FAIL'
(root/'evidence/browser-self-check.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
print(json.dumps(result,indent=2,ensure_ascii=False))
raise SystemExit(0 if result['status']=='PASS' else 1)
