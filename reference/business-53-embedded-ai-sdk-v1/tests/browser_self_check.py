from pathlib import Path
import base64,hashlib,http.server,json,re,socketserver,threading,urllib.request
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
states=['cover','host','contract','permissions','fallback','decision','mobile']
viewports=[(1440,1100),(768,1024),(390,844)]
assets=sorted((root/'assets/images').glob('*.svg'))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*_args): pass
handler=lambda *args,**kwargs:Quiet(*args,directory=str(root),**kwargs)
server=socketserver.TCPServer(('127.0.0.1',0),handler);port=server.server_address[1]
threading.Thread(target=server.serve_forever,daemon=True).start()
http_results={}
paths=[Path('index.html'),Path('styles/main.css'),Path('scripts/review.js'),*[a.relative_to(root) for a in assets]]
for path in paths:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/{path.as_posix()}',timeout=4) as response:
        body=response.read();http_results[path.as_posix()]={'status':response.status,'content_type':response.headers.get_content_type(),'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
server.shutdown();server.server_close()
html=(root/'index.html').read_text();css=(root/'styles/main.css').read_text();js=(root/'scripts/review.js').read_text()
for asset in assets:
    html=html.replace(f'assets/images/{asset.name}?v=eai-v1','data:image/svg+xml;base64,'+base64.b64encode(asset.read_bytes()).decode())
html=re.sub(r'<link[^>]+styles/main\.css[^>]*>',f'<style>{css}</style>',html)
html=re.sub(r'<script src="scripts/review\.js\?v=eai-v1-20260730"></script>',f'<script>{js}</script>',html)
failures=[];combos=[];console=[];page_errors=[];requests=[]
shots=root/'evidence/implementation-screenshots';shots.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page()
    page.on('console',lambda message:console.append(message.text) if message.type=='error' else None)
    page.on('pageerror',lambda error:page_errors.append(str(error)))
    page.on('request',lambda request:requests.append(request.url) if not request.url.startswith('data:') else None)
    for width,height in viewports:
        page.set_viewport_size({'width':width,'height':height});page.set_content(html,wait_until='load')
        for state in states:
            page.locator(f'[data-state-control="{state}"]').click()
            info=page.evaluate('''(state)=>{const tabs=[...document.querySelectorAll('[role="tab"]')],panels=[...document.querySelectorAll('[role="tabpanel"]')],visible=panels.filter(p=>!p.hidden&&getComputedStyle(p).display!=='none'),selected=tabs.filter(t=>t.getAttribute('aria-selected')==='true'),critical=[...document.querySelectorAll('[role="tabpanel"]:not([hidden]) img,[role="tabpanel"]:not([hidden]) .label,[role="tabpanel"]:not([hidden]) .station-tag,[role="tabpanel"]:not([hidden]) code')],bad=critical.map(e=>{const r=e.getBoundingClientRect();return {text:e.alt||e.textContent.trim(),left:r.left,right:r.right,width:r.width,height:r.height}}).filter(r=>r.left<-.5||r.right>innerWidth+.5||r.width<1||r.height<1),at=tabs.every(t=>{const p=document.getElementById(t.getAttribute('aria-controls'));return p&&p.getAttribute('aria-labelledby')===t.id}),images=[...document.querySelectorAll('[role="tabpanel"]:not([hidden]) img')].map(i=>({complete:i.complete,w:i.naturalWidth,h:i.naturalHeight}));return {visible:visible.map(p=>p.dataset.state),selected:selected.map(t=>t.dataset.stateControl),overflow:document.documentElement.scrollWidth-innerWidth,bad,at,images,state}}''',state)
            images_ok=all(i['complete'] and i['w']>0 and i['h']>0 for i in info['images'])
            if info['visible']!=[state] or info['selected']!=[state] or info['overflow']>0 or info['bad'] or not info['at'] or not images_ok: failures.append({'viewport':[width,height],'state':state,'info':info})
            combos.append({'viewport':[width,height],'state':state})
            if width==1440: page.screenshot(path=str(shots/f'{state}-1440.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1100});page.set_content(html,wait_until='load')
    page.locator('[data-state-control="cover"]').focus();page.keyboard.press('ArrowRight');arrow=page.locator('[data-state-control="host"]').get_attribute('aria-selected')=='true'
    page.keyboard.press('End');end=page.locator('[data-state-control="mobile"]').get_attribute('aria-selected')=='true'
    page.keyboard.press('Home');home=page.locator('[data-state-control="cover"]').get_attribute('aria-selected')=='true'
    page.locator('[data-state-control="contract"]').focus();page.keyboard.press('Enter');enter=page.locator('[data-state-control="contract"]').get_attribute('aria-selected')=='true'
    page.locator('[data-state-control="permissions"]').focus();page.keyboard.press('Space');space=page.locator('[data-state-control="permissions"]').get_attribute('aria-selected')=='true'
    page.locator('[data-state-control="decision"]').click();replay=page.locator('[data-motion-replay]');replay.focus();page.evaluate('window.scrollTo(0,120);window.__motionEvents=[];document.querySelector(".integration-spec-seal").addEventListener("animationend",e=>window.__motionEvents.push(e.animationName))')
    def run_once():
        before=page.evaluate('''()=>{const e=document.querySelector('.integration-spec-seal'),r=e.getBoundingClientRect();return {focus:document.activeElement===document.querySelector('[data-motion-replay]'),scrollY,rect:[r.x,r.y,r.width,r.height]}}''')
        replay.click();page.wait_for_function("document.querySelector('[data-integration-line]').dataset.motionState==='complete'",timeout=2500)
        after=page.evaluate('''()=>{const e=document.querySelector('.integration-spec-seal'),s=getComputedStyle(e),r=e.getBoundingClientRect();return {opacity:s.opacity,transform:s.transform,focus:document.activeElement===document.querySelector('[data-motion-replay]'),scrollY,rect:[r.x,r.y,r.width,r.height]}}''')
        return before,after,hashlib.sha256(page.screenshot()).hexdigest()
    replay.click();timing=page.evaluate('''()=>{const s=getComputedStyle(document.querySelector('.integration-spec-seal'));return {name:s.animationName,end:(parseFloat(s.animationDelay)+parseFloat(s.animationDuration))*1000}}''');page.wait_for_function("document.querySelector('[data-integration-line]').dataset.motionState==='complete'",timeout=2500)
    b1,a1,s1=run_once();b2,a2,s2=run_once();events=page.evaluate('window.__motionEvents')
    replay_equal=all(a1[k]==a2[k] for k in ['opacity','transform','rect']) and s1==s2
    focus_stable=all(x['focus'] for x in [b1,a1,b2,a2]);scroll_stable=abs(b1['scrollY']-a1['scrollY'])<1 and abs(b2['scrollY']-a2['scrollY'])<1;geometry_stable=a1['rect']==a2['rect']
    page.emulate_media(reduced_motion='reduce');replay.click();reduced=page.evaluate('''()=>({state:document.querySelector('[data-integration-line]').dataset.motionState,visible:[...document.querySelectorAll('.line-node,.integration-spec-seal')].every(e=>getComputedStyle(e).opacity==='1'),persistent:['PERMISSION REQUIRED — NOT GRANTED','INSTALLATION NOT PERFORMED','EXECUTION NOT PERFORMED','MODEL/PROVIDER — NOT CONNECTED'].every(x=>document.body.innerText.includes(x))})''')
    page.set_viewport_size({'width':390,'height':844});page.set_content(html,wait_until='load');page.locator('[data-state-control="mobile"]').click();page.locator('[data-state-control="mobile"]').focus()
    mobile=page.evaluate('''()=>{const p=document.querySelector('.phone-brief'),r=p.getBoundingClientRect(),text=p.innerText;return {left:r.left,right:r.right,width:r.width,required:['HOST PRODUCT','INPUT CONTRACT','OUTPUT CONTRACT','PERMISSION REQUIRED','FAIL-CLOSED','NOT PERFORMED','NOT CONNECTED'].every(x=>text.includes(x))}}''')
    page.evaluate("document.querySelector('.skip-link').style.display='none'");page.screenshot(path=str(shots/'mobile-390.png'),full_page=True);browser.close()
keyboard=arrow and home and end and enter and space;http_ok=all(v['status']==200 and v['bytes']>0 for v in http_results.values())
result={'status':'PASS','combinations':len(combos),'failures':failures,'http_files':http_results,'http_all_200_nonempty':http_ok,'console_errors':console,'page_errors':page_errors,'external_runtime_requests':requests,'keyboard':{'arrow':arrow,'home':home,'end':end,'enter':enter,'space':space},'motion':{'animation_name':timing['name'],'computed_end_ms':timing['end'],'actual_final_animationend':'integrationSpecComplete' in events,'replay_equal':replay_equal,'focus_stable':focus_stable,'scroll_stable':scroll_stable,'geometry_stable':geometry_stable},'reduced_motion':reduced,'mobile':mobile,'harness':'localhost HTTP byte/MIME check plus exact local HTML/CSS/JS/SVG bytes in network-free Chromium because loopback page navigation is blocked by this worker environment','gate':'IMPLEMENTATION_SELF_CHECK_ONLY'}
if failures or not http_ok or console or page_errors or requests or not keyboard or timing['name']!='integrationSpecComplete' or not 700<=timing['end']<=800 or not result['motion']['actual_final_animationend'] or not replay_equal or not focus_stable or not scroll_stable or not geometry_stable or reduced['state']!='complete' or not reduced['visible'] or not reduced['persistent'] or not mobile['required'] or mobile['left']<-.5 or mobile['right']>390.5: result['status']='FAIL'
(root/'evidence/browser-self-check.json').write_text(json.dumps(result,indent=2,ensure_ascii=False));print(json.dumps(result,indent=2,ensure_ascii=False));raise SystemExit(0 if result['status']=='PASS' else 1)
